#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = [
#   "beautifulsoup4>=4.12.0,<5.0.0",
#   "fastmcp>=3.3.1,<4.0.0",
#   "httpx>=0.27.0,<1.0.0",
#   "lxml>=5.0.0,<7.0.0",
#   "markdownify>=0.13.0,<2.0.0",
#   "mistune>=3.0.0,<4.0.0",
#   "python-dotenv>=1.0.0,<2.0.0",
# ]
# ///
from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from bs4 import BeautifulSoup
from fastmcp import FastMCP
import httpx
from markdownify import markdownify as html_to_markdown
import mistune


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import (
    IMAGE_EXTENSIONS,
    UnsafePathError,
    atomic_write_text,
    manual_cookie_hint,
    prepare_output_dir,
    read_config,
    update_config_atomic,
)
from tower_auth import (
    TowerLoginError,
    cookies_from_header,
    is_login_response,
    login_tower,
)


TOWER_BASE = "https://tower.im"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

mcp = FastMCP("SpecWeaver Tower Reader")
_client: httpx.AsyncClient | None = None
_client_cookie_fingerprint = ""
_runtime_cookie = ""
_login_lock: asyncio.Lock | None = None
markdown_to_html = mistune.create_markdown(
    escape=True,
    hard_wrap=True,
    plugins=["strikethrough", "table", "task_lists", "url"],
)
URL_PATTERN = re.compile(r"https?://[^\s<>()\[\]{}\"']+")
BUG_TAGS = {"bug"}


class TowerSessionError(RuntimeError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def tower_cookie() -> str:
    return _runtime_cookie or read_config()["TOWER_COOKIE"]


def login_lock() -> asyncio.Lock:
    global _login_lock
    if _login_lock is None:
        _login_lock = asyncio.Lock()
    return _login_lock


async def get_client() -> httpx.AsyncClient:
    global _client, _client_cookie_fingerprint
    configured_cookie = tower_cookie()
    fingerprint = hashlib.sha256(configured_cookie.encode()).hexdigest()
    if _client is None or _client_cookie_fingerprint != fingerprint:
        if _client is not None:
            await _client.aclose()
        _client = httpx.AsyncClient(
            timeout=30,
            follow_redirects=False,
            cookies=cookies_from_header(configured_cookie),
        )
        _client_cookie_fingerprint = fingerprint
    return _client


async def refresh_tower_session(
    validation_url: str,
    stale_fingerprint: str,
) -> None:
    global _runtime_cookie
    async with login_lock():
        current_cookie = tower_cookie()
        current_fingerprint = hashlib.sha256(current_cookie.encode()).hexdigest()
        if current_fingerprint != stale_fingerprint:
            return
        config = read_config()
        email = config["TOWER_EMAIL"]
        password = config["TOWER_PASSWORD"]
        if not email or not password:
            raise TowerSessionError(
                "auth_expired",
                "Tower Cookie 已过期，且未配置邮箱密码；"
                "请运行 specweaver configure tower",
            )
        try:
            renewed_cookie = await asyncio.to_thread(
                login_tower,
                email,
                password,
                validation_url=validation_url,
            )
        except TowerLoginError as error:
            if error.kind == "credentials":
                status = "auth_expired"
                message = "Tower 邮箱或密码已失效"
            elif error.kind == "verification":
                status = "verification_required"
                message = "Tower 要求验证码或二次验证"
            elif error.kind == "network":
                status = "network_error"
                message = "Tower 登录网络异常"
            else:
                status = "compatibility_error"
                message = "Tower 网页登录流程暂时不可用"
            raise TowerSessionError(
                status,
                f"{message}；{manual_cookie_hint('tower', 'TOWER_COOKIE')}",
            ) from error
        update_config_atomic({"TOWER_COOKIE": renewed_cookie})
        _runtime_cookie = renewed_cookie
        await get_client()


async def request_once(
    url: str,
    *,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    current = urljoin(TOWER_BASE, url)
    client = await get_client()
    for _ in range(6):
        parsed = urlparse(current)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {
            "tower.im",
            "www.tower.im",
            "attachments.tower.im",
            "tower3-downloads.tower.im",
        }:
            raise ValueError("Tower 请求或重定向目标不是受信任的 HTTPS 域名")
        response = await client.get(
            current,
            headers={**HEADERS, **(extra_headers or {})},
            follow_redirects=False,
        )
        if not response.is_redirect:
            response.raise_for_status()
            return response
        location = response.headers.get("location")
        if not location:
            break
        current = urljoin(str(response.url), location)
    raise RuntimeError(f"Tower 资源重定向次数过多: {url}")


async def request(
    url: str,
    *,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    stale_cookie = tower_cookie()
    response = (
        await request_once(url)
        if extra_headers is None
        else await request_once(url, extra_headers=extra_headers)
    )
    if not is_login_page(response):
        return response
    stale_fingerprint = hashlib.sha256(stale_cookie.encode()).hexdigest()
    await refresh_tower_session(urljoin(TOWER_BASE, url), stale_fingerprint)
    response = (
        await request_once(url)
        if extra_headers is None
        else await request_once(url, extra_headers=extra_headers)
    )
    if is_login_page(response):
        raise TowerSessionError(
            "auth_expired",
            "Tower 自动续期后仍需要登录；"
            + manual_cookie_hint("tower", "TOWER_COOKIE"),
        )
    return response


def text_of(element) -> str:
    return element.get_text(" ", strip=True) if element else ""


def is_tower_attachment_url(value: str) -> bool:
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    return (
        host in {
            "attachments.tower.im",
            "tower.im",
            "www.tower.im",
            "tower3-downloads.tower.im",
        }
        and (
            host in {"attachments.tower.im", "tower3-downloads.tower.im"}
            or "/attfiles/" in path
        )
    )


def attachment_kind(name: str, source_url: str) -> tuple[str, str]:
    media_type = (
        mimetypes.guess_type(name)[0]
        or mimetypes.guess_type(urlparse(source_url).path)[0]
        or ""
    )
    if media_type.startswith("image/"):
        return "image", media_type
    if media_type.startswith("video/"):
        return "video", media_type
    if media_type in {
        "application/zip",
        "application/x-7z-compressed",
        "application/x-rar-compressed",
        "application/x-tar",
        "application/gzip",
    }:
        return "archive", media_type
    return "file", media_type


def parse_ordered_content(element) -> dict:
    soup = BeautifulSoup(str(element), "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    images = []
    attachments = []
    links = []
    handled_images: set[int] = set()
    for item in list(soup.find_all(["a", "img"])):
        if item.name == "a":
            raw_href = str(item.get("href") or "").strip()
            if not raw_href:
                continue
            href = urljoin(TOWER_BASE, raw_href)
            item["href"] = href
            label = text_of(item) or str(item.get("download") or "")
            links.append({"text": label, "url": href})
            if not is_tower_attachment_url(href):
                continue
            name = (
                str(item.get("download") or "").strip()
                or label
                or Path(urlparse(href).path).name
                or "未提供"
            )
            kind, media_type = attachment_kind(name, href)
            attachments.append({
                "position": len(attachments) + 1,
                "source_url": href,
                "name": name,
                "kind": kind,
                "media_type": media_type,
                "size": str(item.get("data-size") or "未提供"),
            })
            nested_images = item.find_all("img")
            handled_images.update(id(image) for image in nested_images)
            continue

        image = item
        raw_src = str(image.get("src") or "").strip()
        alt = image.get("alt", "")
        if not raw_src:
            image.replace_with(alt)
            continue
        src = urljoin(TOWER_BASE, raw_src)
        image["src"] = src
        images.append({
            "position": len(images) + 1,
            "source_url": src,
            "alt": alt,
        })
        if id(image) not in handled_images and is_tower_attachment_url(src):
            name = alt or Path(urlparse(src).path).name or "未提供"
            kind, media_type = attachment_kind(name, src)
            attachments.append({
                "position": len(attachments) + 1,
                "source_url": src,
                "name": name,
                "kind": kind,
                "media_type": media_type,
                "size": str(image.get("data-size") or "未提供"),
            })
    markdown = html_to_markdown(
        str(soup),
        heading_style="ATX",
        bullets="-",
    ).strip()
    return {
        "text": re.sub(r"\n{3,}", "\n\n", markdown),
        "images": images,
        "attachments": attachments,
        "links": links,
    }


def clean_html(element) -> str:
    return parse_ordered_content(element)["text"]


def validate_tower_todo_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "请提供 Tower HTTPS 任务链接"
    if parsed.netloc.lower() not in {"tower.im", "www.tower.im"} or "/todos/" not in parsed.path:
        return "请提供有效的 Tower 任务链接"
    return None


def is_login_page(response: httpx.Response) -> bool:
    return is_login_response(response)


def parse_comment_meta(soup: BeautifulSoup) -> dict[str, str]:
    page = soup.select_one(".page-inner")
    project_guid = page.get("data-project-guid", "") if page else ""
    todo_guid = page.get("data-page-guid", "") if page else ""
    form = soup.select_one("form[action*='/comments']")
    action = form.get("action", "") if form else ""
    match = re.search(
        r"/projects/([0-9a-f]{32})/todos/([0-9a-f]{32})/comments",
        action,
        re.I,
    )
    if match:
        project_guid, todo_guid = match.groups()
    if not todo_guid:
        todo_page = soup.select_one("tr-todo-page[todo-guid]")
        todo_guid = todo_page.get("todo-guid", "") if todo_page else ""
    csrf = soup.select_one("meta[name='csrf-token']")
    return {
        "project_guid": project_guid,
        "todo_guid": todo_guid,
        "csrf_token": csrf.get("content", "") if csrf else "",
        "action": action,
    }


def adapt_tower_comment_html(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    for deleted in soup.find_all("del"):
        deleted.name = "s"
    for item in soup.select("li.task-list-item"):
        checkbox = item.find("input", attrs={"type": "checkbox"})
        if checkbox:
            checkbox.replace_with("☑ " if checkbox.has_attr("checked") else "☐ ")
        item.attrs.pop("class", None)
    return str(soup).strip()


def text_to_comment_html(content: str) -> str:
    value = content.strip()
    if not value:
        raise ValueError("评论内容不能为空")
    if value.startswith("<"):
        return adapt_tower_comment_html(value)
    return adapt_tower_comment_html(markdown_to_html(value))


async def post_comment(
    meta: dict[str, str],
    comment_html: str,
    referer: str,
) -> httpx.Response:
    action = meta["action"] or (
        f"/projects/{meta['project_guid']}/todos/{meta['todo_guid']}/comments?is_html=1"
    )
    response = await (await get_client()).post(
        urljoin(TOWER_BASE, action),
        data={
            "conn_guid": str(uuid4()),
            "utf8": "✓",
            "comment[content]": comment_html,
            "attach_guids": "",
        },
        headers={
            **HEADERS,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-CSRF-Token": meta["csrf_token"],
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
            "Origin": TOWER_BASE,
        },
        follow_redirects=False,
    )
    if response.status_code in {401, 403} or response.is_redirect:
        raise RuntimeError("Tower 登录态或 CSRF 校验已失效")
    if not 200 <= response.status_code < 300:
        message = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)[:200]
        raise RuntimeError(f"Tower 返回 {response.status_code}: {message or '未知错误'}")
    return response


def parse_comments(soup: BeautifulSoup) -> list[dict]:
    comments = []
    for content in soup.select("tr-editor-output-renderer .comment-content"):
        if content.find_parent(class_="desc-content"):
            continue
        wrapper = content.find_parent(class_="comment")
        if wrapper is None:
            continue
        body_soup = BeautifulSoup(str(content), "html.parser")
        body = body_soup.select_one(".comment-content") or body_soup
        quotes = []
        for quote in body.select("blockquote, .quote, .comment-quote"):
            quote_text = text_of(quote)
            if quote_text and quote_text not in quotes:
                quotes.append(quote_text)
            quote.decompose()
        ordered_content = parse_ordered_content(body)
        if not ordered_content["text"] and not quotes:
            continue
        author = text_of(wrapper.select_one("a.author"))
        comment_id = ""
        created_at = ""
        reply_to = ""
        comment_id = next((
            str(wrapper.get(name) or "").strip()
            for name in ("data-comment-guid", "data-comment-id", "data-guid", "id")
            if wrapper.get(name)
        ), "")
        time_element = wrapper.select_one("time, [datetime], .time, .date")
        if time_element:
            created_at = next((
                str(time_element.get(name) or "").strip()
                for name in ("datetime", "title", "data-tooltip")
                if time_element.get(name)
            ), "") or text_of(time_element)
        reply_to = next((
            str(wrapper.get(name) or "").strip()
            for name in ("data-reply-to", "data-reply-comment-id")
            if wrapper.get(name)
        ), "")
        if not reply_to:
            reply_to = text_of(
                wrapper.select_one(".reply-to, .comment-reply, .comment-ref")
            )
        comments.append({
            "id": comment_id,
            "author": author,
            "created_at": created_at,
            "reply_to": reply_to,
            "quote": "\n\n".join(quotes),
            "text": ordered_content["text"],
            "images": ordered_content["images"],
            "attachments": ordered_content["attachments"],
            "links": ordered_content["links"],
        })
    return comments


def build_image_occurrences(data: dict) -> list[dict]:
    occurrences = []

    def append(scope: str, scope_index: int, images: list[dict]) -> None:
        for image in images:
            occurrences.append({
                "occurrence_index": len(occurrences) + 1,
                "scope": scope,
                "scope_index": scope_index,
                **image,
            })

    append("description", 1, data.get("description_images", []))
    for comment_index, comment in enumerate(data.get("comments", []), 1):
        append("comment", comment_index, comment.get("images", []))
    return occurrences


def build_attachment_occurrences(data: dict) -> list[dict]:
    occurrences = []

    def append(scope: str, scope_index: int, attachments: list[dict]) -> None:
        for attachment in attachments:
            occurrences.append({
                "occurrence_index": len(occurrences) + 1,
                "scope": scope,
                "scope_index": scope_index,
                **attachment,
            })

    append("description", 1, data.get("description_attachments", []))
    for comment_index, comment in enumerate(data.get("comments", []), 1):
        append("comment", comment_index, comment.get("attachments", []))
    return occurrences


def unique_attachments(occurrences: list[dict]) -> list[dict]:
    items = []
    seen: set[str] = set()
    for occurrence in occurrences:
        source_url = occurrence["source_url"]
        if source_url in seen:
            continue
        seen.add(source_url)
        items.append({
            key: occurrence[key]
            for key in ("source_url", "name", "kind", "media_type", "size")
        })
    return items


def classify_external_url(value: str) -> str | None:
    parsed = urlparse(value.rstrip(".,;:!?，。；：！？"))
    host = (parsed.hostname or "").lower()
    if not host or host in {
        "tower.im",
        "www.tower.im",
        "attachments.tower.im",
        "tower3-downloads.tower.im",
    }:
        return None
    if host == "lanhuapp.com" or host.endswith(".lanhuapp.com"):
        return "lanhu"
    eolink_shape = (
        "projectid=" in parsed.fragment.lower()
        and "api" in parsed.fragment.lower()
    )
    if "eolink" in host or eolink_shape:
        return "eolink"
    return "other"


def discover_external_sources(data: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {"lanhu": [], "eolink": [], "other": []}
    candidates = []
    candidates.extend(data.get("description_links", []))
    for comment in data.get("comments", []):
        candidates.extend(comment.get("links", []))
    for text in [
        data.get("description", ""),
        *(comment.get("text", "") for comment in data.get("comments", [])),
    ]:
        candidates.extend({"url": match.group(0)} for match in URL_PATTERN.finditer(text))
    for item in candidates:
        value = str(item.get("url") or "").rstrip(".,;:!?，。；：！？")
        source = classify_external_url(value)
        if source and value not in result[source]:
            result[source].append(value)
    return result


def parse_images(soup: BeautifulSoup) -> list[str]:
    urls = []
    for element in soup.select("img[src], a[href]"):
        value = urljoin(
            TOWER_BASE,
            element.get("src") or element.get("href") or "",
        )
        kind, _ = attachment_kind(text_of(element), value)
        if is_tower_attachment_url(value) and kind == "image" and value not in urls:
            urls.append(value)
    return urls


def parse_project_sections(soup: BeautifulSoup) -> list[dict[str, str]]:
    sections = []
    for item in soup.select("tr-todo-section-links-field-detail-item.section-link"):
        value = {
            "category": text_of(item.select_one("a.container-name")),
            "section": text_of(item.select_one("a.sectionable-name")),
        }
        if (value["category"] or value["section"]) and value not in sections:
            sections.append(value)
    return sections


def parse_tags(soup: BeautifulSoup) -> list[str]:
    tags = []
    selectors = (
        "[data-tag-name], [data-label-name], "
        "tr-todo-labels-field-detail-item, .todo-label, .todo-tag"
    )
    for item in soup.select(selectors):
        if (
            item.find_parent(class_="desc-content")
            or item.find_parent(class_="comment-content")
        ):
            continue
        value = str(item.get("data-tag-name") or item.get("data-label-name") or "")
        value = value.strip() or text_of(item)
        if value and value not in tags:
            tags.append(value)
    return tags


def task_type_from_tags(tags: list[str]) -> str:
    normalized = {
        re.sub(r"\s+", "", tag).strip("#[]【】").lower()
        for tag in tags
    }
    return "bug" if normalized & BUG_TAGS else "requirement"


def decode_javascript_string(value: str) -> str:
    output = []
    index = 0
    simple = {
        "n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
        "v": "\v", "0": "\0", "'": "'", '"': '"', "\\": "\\", "/": "/",
    }
    while index < len(value):
        char = value[index]
        if char != "\\" or index + 1 >= len(value):
            output.append(char)
            index += 1
            continue
        escape = value[index + 1]
        if escape in simple:
            output.append(simple[escape])
            index += 2
            continue
        if escape in {"u", "x"}:
            size = 4 if escape == "u" else 2
            digits = value[index + 2:index + 2 + size]
            if len(digits) == size and re.fullmatch(r"[0-9a-fA-F]+", digits):
                output.append(chr(int(digits, 16)))
                index += 2 + size
                continue
        output.append(escape)
        index += 2
    return "".join(output)


def parse_stream_response(javascript: str) -> str:
    match = re.search(r"var\s+list\s*=\s*'((?:\\.|[^'\\])*)';", javascript, re.S)
    if not match:
        raise ValueError("无法解析 Tower 历史记录响应")
    return decode_javascript_string(match.group(1))


async def expand_stream_fragments(soup: BeautifulSoup) -> int:
    visited: set[str] = set()
    stream_count = 0

    async def expand(container: BeautifulSoup) -> None:
        nonlocal stream_count
        while True:
            placeholder = next((
                item
                for item in container.select(
                    "[data-comment-streams-range][data-url]"
                )
                if not item.find_parent(class_="desc-content")
                and not item.find_parent(class_="comment-content")
            ), None)
            if placeholder is None:
                return
            source_url = urljoin(
                TOWER_BASE,
                str(placeholder.get("data-url") or ""),
            )
            if not source_url or source_url in visited:
                placeholder.decompose()
                continue
            visited.add(source_url)
            fragment = parse_stream_response(
                (await request(source_url)).text
            )
            stream_count += 1
            fragment_soup = BeautifulSoup(fragment, "lxml")
            await expand(fragment_soup)
            fragment_root = fragment_soup.body or fragment_soup
            for node in list(fragment_root.contents):
                placeholder.insert_before(node)
            placeholder.decompose()

    await expand(soup)
    return stream_count


def parse_todo(soup: BeautifulSoup, url: str) -> dict:
    page = soup.select_one(".page-inner")
    tags = parse_tags(soup)
    data = {
        "title": page.get("data-page-name", "") if page else "",
        "url": url,
        "created_at": page.get("data-since", "") if page else "",
        "status": "进行中" if soup.select_one("[data-tooltip*='正在进行']") else "待处理",
        "comments": parse_comments(soup),
        "image_urls": parse_images(soup),
        "project_sections": parse_project_sections(soup),
        "tags": tags,
        "task_type": task_type_from_tags(tags),
    }
    data["todo_id"] = text_of(soup.select_one(".original-text"))
    data["assignee"] = text_of(soup.select_one(".addition-content.has-assignee"))
    due = soup.select_one("tr-detail-date-time input[type=hidden]")
    data["due_date"] = due.get("value", "") if due else ""
    description = soup.select_one(".desc-content")
    ordered_description = (
        parse_ordered_content(description)
        if description else {
            "text": "",
            "images": [],
            "attachments": [],
            "links": [],
        }
    )
    data["description"] = ordered_description["text"]
    data["description_images"] = ordered_description["images"]
    data["description_attachments"] = ordered_description["attachments"]
    data["description_links"] = ordered_description["links"]
    data["parents"] = [
        {"title": text_of(item), "url": urljoin(TOWER_BASE, item.get("href", ""))}
        for item in soup.select(".breadcrumb-link")
    ]
    data["sub_todos"] = []
    for row in soup.select("tr-grid-subtodo-row"):
        title = text_of(row.select_one(".todo-content-shadow .todo-rest"))
        if title:
            data["sub_todos"].append({
                "title": title,
                "url": urljoin(TOWER_BASE, row.get("detail-url", "")),
            })
    data["image_occurrences"] = build_image_occurrences(data)
    data["attachment_occurrences"] = build_attachment_occurrences(data)
    data["attachments"] = unique_attachments(data["attachment_occurrences"])
    data["external_sources"] = discover_external_sources(data)
    return data


async def load_todo_data(url: str) -> dict:
    response = await request(url)
    if is_login_page(response):
        raise RuntimeError("Tower Cookie 已过期，请运行 specweaver configure tower 更新后重试")
    soup = BeautifulSoup(response.text, "lxml")
    stream_count = await expand_stream_fragments(soup)
    data = parse_todo(soup, url)
    if not data["title"]:
        raise RuntimeError("无法解析 Tower 任务")

    ordered_comments = []
    stable_positions: dict[str, int] = {}
    for comment in data["comments"]:
        comment_id = comment.get("id") or ""
        if comment_id and comment_id in stable_positions:
            ordered_comments[stable_positions[comment_id]] = comment
            continue
        if comment_id:
            stable_positions[comment_id] = len(ordered_comments)
        ordered_comments.append(comment)
    data["comments"] = ordered_comments
    data["image_occurrences"] = build_image_occurrences(data)
    data["attachment_occurrences"] = build_attachment_occurrences(data)
    data["attachments"] = unique_attachments(data["attachment_occurrences"])
    data["external_sources"] = discover_external_sources(data)
    data["stream_count"] = stream_count
    return data


def tower_cache_metadata(data: dict) -> dict:
    return {
        "schema_version": 2,
        "title": data.get("title") or "未提供",
        "url": data.get("url") or "",
        "todo_id": data.get("todo_id") or "未提供",
        "task_type": data.get("task_type", "requirement"),
        "comment_count": len(data.get("comments", [])),
        "comment_metadata_incomplete": any(
            not comment.get("id") or not comment.get("created_at")
            for comment in data.get("comments", [])
        ),
        "sub_todo_count": len(data.get("sub_todos", [])),
        "attachments": data.get("attachments", []),
        "attachment_occurrences": data.get("attachment_occurrences", []),
        "external_sources": data.get("external_sources", {}),
        "stream_count": data.get("stream_count", 0),
    }


def format_todo(data: dict) -> str:
    lines = [
        f"# {data['title'] or '未提供'}",
        "",
        "## 任务信息",
        "",
        f"- Tower 链接：{data['url']}",
        f"- 任务 ID：{data.get('todo_id') or '未提供'}",
        f"- 任务类型：{'Bug' if data.get('task_type') == 'bug' else '普通需求'}",
        f"- 状态：{data.get('status') or '未提供'}",
        f"- 负责人：{data.get('assignee') or '未提供'}",
        f"- 截止时间：{data.get('due_date') or '未提供'}",
        f"- 创建时间：{data.get('created_at') or '未提供'}",
        f"- Tags：{', '.join(data.get('tags') or []) or '未提供'}",
    ]
    lines.extend(["", "## 所属分类与分组"])
    if data["project_sections"]:
        for item in data["project_sections"]:
            lines.append(
                f"- 分类: {item['category'] or '未提供'} | 分组: {item['section'] or '未提供'}"
            )
    else:
        lines.append("- 分类: 未提供 | 分组: 未提供")
    lines.extend(["", "## 父任务"])
    if data["parents"]:
        lines.extend(f"- {item['title']}: {item['url']}" for item in data["parents"])
    else:
        lines.append("- 未提供")
    lines.extend(["", "## 正文", "", data.get("description") or "未提供"])
    lines.extend(["", f"## 子任务 ({len(data['sub_todos'])})"])
    if data["sub_todos"]:
        lines.extend(f"- {item['title']}: {item['url']}" for item in data["sub_todos"])
    else:
        lines.append("- 无")
    lines.extend(["", f"## 评论 ({len(data['comments'])})"])
    if not data["comments"]:
        lines.append("- 无")
    for index, comment in enumerate(data["comments"], 1):
        lines.extend([
            "",
            f"### 评论 {index}",
            "",
            f"- 评论 ID：{comment.get('id') or '未提供'}",
            f"- 作者：{comment.get('author') or '未提供'}",
            f"- 时间：{comment.get('created_at') or '未提供'}",
            f"- 回复对象：{comment.get('reply_to') or '未提供'}",
            "",
            "#### 引用",
            "",
            comment.get("quote") or "未提供",
            "",
            "#### 正文",
            "",
            comment.get("text") or "未提供",
        ])
    lines.extend([
        "",
        "## 读取完整性",
        "",
        f"- 延迟加载区间：{data.get('stream_count', 0)}",
        "- 评论读取状态：完整",
        "- 子任务读取深度：仅标题和链接，未递归",
    ])
    occurrences = data.get("attachment_occurrences", [])
    lines.extend(["", f"## 附件索引 ({len(occurrences)})"])
    if not occurrences:
        lines.append("- 无")
    for item in occurrences:
        scope = "正文" if item["scope"] == "description" else f"评论 {item['scope_index']}"
        lines.extend([
            "",
            f"### 附件 {item['occurrence_index']}",
            "",
            f"- 出现位置：{scope} / 第 {item['position']} 个附件",
            f"- 名称：{item.get('name') or '未提供'}",
            f"- 类型：{item.get('media_type') or item.get('kind') or '未提供'}",
            f"- 大小：{item.get('size') or '未提供'}",
            f"- 来源：{item['source_url']}",
        ])
    sources = data.get("external_sources", {})
    source_count = sum(len(items) for items in sources.values())
    lines.extend(["", f"## 外部来源线索 ({source_count})"])
    for source, label in (
        ("lanhu", "蓝湖"),
        ("eolink", "Eolink"),
        ("other", "其他"),
    ):
        values = sources.get(source, [])
        lines.extend(["", f"### {label} ({len(values)})"])
        lines.extend(f"- {value}" for value in values)
        if not values:
            lines.append("- 无")
    return "\n".join(lines)


def tower_cache_key(data: dict, url: str) -> str:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    try:
        todo_index = path_parts.index("todos")
        raw = path_parts[todo_index + 1]
    except (ValueError, IndexError):
        raw = str(data.get("todo_id") or "unknown")
    value = re.sub(r"[^0-9A-Za-z._-]+", "-", raw).strip("-")
    return value or "unknown"


def tower_cache_file(data: dict, url: str) -> Path:
    home = Path(
        os.getenv("SPECWEAVER_HOME", Path.home() / ".specweaver")
    ).expanduser()
    return home / "cache" / "tower" / tower_cache_key(data, url) / "tower-raw.md"


def tower_metadata_file(data: dict, url: str) -> Path:
    return tower_cache_file(data, url).with_name("tower-metadata.json")


def tower_image_cache_dir(data: dict, url: str) -> Path:
    return tower_cache_file(data, url).with_name("images")


def write_cached_image(path: Path, content: bytes) -> None:
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temp_path.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(0o600)
        os.replace(temp_path, path)
        path.chmod(0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()


async def discover_extensionless_image_attachments(data: dict) -> list[dict]:
    failures = []
    occurrences = data.get("attachment_occurrences", [])
    for candidate_index, attachment in enumerate(data.get("attachments", []), 1):
        if attachment.get("kind") != "file" or attachment.get("media_type"):
            continue
        source_url = str(attachment["source_url"])
        try:
            response = await request(
                source_url,
                extra_headers={"Range": "bytes=0-0"},
            )
            content_type = (
                response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
        except Exception as error:
            detail = tool_error(error)
            failures.append({
                "source_index": candidate_index,
                "source_url": source_url,
                "name": attachment.get("name") or "未提供",
                "status": detail.get("status", "download_error"),
                "error": (
                    "无法识别附件是否为图片: "
                    f"{detail.get('message') or str(error)}"
                ),
            })
            continue
        if content_type not in IMAGE_EXTENSIONS:
            continue
        attachment["kind"] = "image"
        attachment["media_type"] = content_type
        for occurrence in occurrences:
            if occurrence.get("source_url") == source_url:
                occurrence["kind"] = "image"
                occurrence["media_type"] = content_type
    return failures


async def download_tower_image_attachments(
    data: dict,
    output_dir: Path,
    *,
    file_prefix: str,
) -> dict:
    target_dir = prepare_output_dir(str(output_dir))
    failures = await discover_extensionless_image_attachments(data)
    images = [
        attachment
        for attachment in data.get("attachments", [])
        if attachment.get("kind") == "image"
    ]
    downloaded = []
    hashes: dict[str, dict] = {}
    saved_names: set[str] = set()
    source_results: dict[str, dict] = {
        item["source_url"]: item
        for item in failures
    }

    def record_failure(
        source_index: int,
        attachment: dict,
        status: str,
        error: str,
    ) -> None:
        item = {
            "source_index": source_index,
            "source_url": attachment["source_url"],
            "name": attachment.get("name") or "未提供",
            "status": status,
            "error": error,
        }
        failures.append(item)
        source_results[attachment["source_url"]] = item

    for source_index, attachment in enumerate(images, 1):
        source_url = str(attachment["source_url"])
        try:
            response = await request(source_url)
            if is_login_page(response):
                record_failure(
                    source_index,
                    attachment,
                    "auth_expired",
                    "Tower Cookie 已过期",
                )
                continue
            content_type = (
                response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            extension = IMAGE_EXTENSIONS.get(content_type)
            if not extension:
                raise ValueError(
                    f"不支持的图片类型: {content_type or '未知类型'}"
                )
            content_hash = hashlib.sha256(response.content).hexdigest()
            if content_hash in hashes:
                original = hashes[content_hash]
                item = {
                    "source_index": source_index,
                    "source_url": source_url,
                    "name": attachment.get("name") or "未提供",
                    "status": "success",
                    "file_name": original["file_name"],
                    "path": original["path"],
                    "content_type": content_type,
                    "sha256": content_hash,
                    "duplicate": True,
                    "duplicate_of": original["file_name"],
                }
                downloaded.append(item)
                source_results[source_url] = item
                continue
            file_name = f"{file_prefix}-{len(hashes) + 1:03d}{extension}"
            file_path = target_dir / file_name
            write_cached_image(file_path, response.content)
            item = {
                "source_index": source_index,
                "source_url": source_url,
                "name": attachment.get("name") or "未提供",
                "status": "success",
                "file_name": file_name,
                "path": str(file_path),
                "content_type": content_type,
                "bytes": len(response.content),
                "sha256": content_hash,
                "duplicate": False,
            }
            hashes[content_hash] = item
            saved_names.add(file_name)
            downloaded.append(item)
            source_results[source_url] = item
        except TowerSessionError as error:
            record_failure(
                source_index,
                attachment,
                error.status,
                str(error),
            )
        except httpx.HTTPStatusError as error:
            code = error.response.status_code
            status = (
                "auth_expired" if code == 401
                else "forbidden" if code == 403
                else "not_found" if code == 404
                else "api_error"
            )
            record_failure(
                source_index,
                attachment,
                status,
                f"Tower 返回 HTTP {code}",
            )
        except httpx.HTTPError as error:
            record_failure(
                source_index,
                attachment,
                "network_error",
                str(error),
            )
        except Exception as error:
            record_failure(
                source_index,
                attachment,
                "download_error",
                str(error),
            )

    owned_pattern = re.compile(
        rf"{re.escape(file_prefix)}-\d{{3}}\.(gif|jpe?g|png|svg|webp)$",
        re.I,
    )
    for old_file in target_dir.iterdir():
        if (
            old_file.is_file()
            and owned_pattern.fullmatch(old_file.name)
            and old_file.name not in saved_names
        ):
            old_file.unlink()

    occurrences = []
    for occurrence in data.get("attachment_occurrences", []):
        if occurrence.get("kind") != "image":
            continue
        occurrences.append({
            **occurrence,
            **source_results.get(occurrence["source_url"], {
                "status": "not_downloaded",
                "error": "未找到对应的图片缓存结果",
            }),
        })

    status = "success" if not failures else "partial"
    if failures and not downloaded:
        failure_statuses = {item["status"] for item in failures}
        if len(failure_statuses) == 1:
            status = failure_statuses.pop()
    return {
        "status": status,
        "output_dir": str(target_dir),
        "source_count": len(images),
        "saved_count": len(hashes),
        "images": downloaded,
        "occurrences": occurrences,
        "failures": failures,
    }


async def cache_tower_images(data: dict, url: str) -> dict:
    target_dir = prepare_output_dir(str(tower_image_cache_dir(data, url)))
    target_dir.parent.chmod(0o700)
    target_dir.chmod(0o700)
    return await download_tower_image_attachments(
        data,
        target_dir,
        file_prefix="tower-image",
    )


def write_tower_raw(
    data: dict,
    url: str,
    image_cache: dict | None = None,
) -> Path:
    cache_file = atomic_write_text(tower_cache_file(data, url), format_todo(data))
    metadata = tower_cache_metadata(data)
    metadata["image_cache"] = image_cache or {
        "status": "not_cached",
        "output_dir": str(tower_image_cache_dir(data, url)),
        "source_count": sum(
            attachment.get("kind") == "image"
            for attachment in data.get("attachments", [])
        ),
        "saved_count": 0,
        "images": [],
        "occurrences": [],
        "failures": [],
    }
    atomic_write_text(
        tower_metadata_file(data, url),
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
    )
    return cache_file


def read_cached_tower_data(url: str) -> tuple[dict, Path]:
    cache_file = tower_cache_file({}, url)
    if not cache_file.is_file():
        raise FileNotFoundError(
            "Tower 原始缓存不存在；请先调用 tower_read_todo"
        )
    if not cache_file.read_text(encoding="utf-8").strip():
        raise ValueError("tower-raw.md 是空文件")
    metadata_file = tower_metadata_file({}, url)
    if not metadata_file.is_file():
        raise ValueError("Tower 缓存缺少 tower-metadata.json")
    try:
        data = json.loads(metadata_file.read_text(encoding="utf-8"))
    except Exception as error:
        raise ValueError("tower-metadata.json 损坏") from error
    if data.get("schema_version") not in {1, 2}:
        raise ValueError("tower-metadata.json 的版本不受支持")
    if data.get("url") != url:
        raise ValueError("Tower 缓存与请求的 Tower 链接不一致")
    return data, cache_file


def tower_read_summary(
    data: dict,
    cache_file: Path,
    image_cache: dict,
) -> dict:
    unresolved = []
    if data.get("comment_metadata_incomplete") or any(
        not comment.get("id") or not comment.get("created_at")
        for comment in data.get("comments", [])
    ):
        unresolved.append("部分评论缺少 Tower 可解析的稳定 ID 或时间，已标记为“未提供”")
    if image_cache["failures"]:
        unresolved.append(
            f"{len(image_cache['failures'])} 张 Tower 图片缓存失败，"
            "分析时不得忽略缺失的图片证据"
        )
    status = "success" if not image_cache["failures"] else "partial"
    return {
        "status": status,
        "platform": "tower",
        "todo_id": data.get("todo_id") or "未提供",
        "task_title": data.get("title") or "未提供",
        "task_type": data.get("task_type", "requirement"),
        "cache_file": str(cache_file),
        "metadata_file": str(cache_file.with_name("tower-metadata.json")),
        "comment_count": data.get(
            "comment_count",
            len(data.get("comments", [])),
        ),
        "attachment_count": len(data.get("attachment_occurrences", [])),
        "image_count": image_cache["source_count"],
        "cached_image_count": image_cache["saved_count"],
        "image_cache_dir": image_cache["output_dir"],
        "image_paths": [
            item["path"]
            for item in image_cache["images"]
            if not item.get("duplicate")
        ],
        "image_failures": image_cache["failures"],
        "sub_todo_count": data.get(
            "sub_todo_count",
            len(data.get("sub_todos", [])),
        ),
        "external_sources": data.get("external_sources", {}),
        "stream_count": data.get("stream_count", 0),
        "read_complete": True,
        "unresolved": unresolved,
    }


def tool_error(error: Exception) -> dict[str, str]:
    if isinstance(error, UnsafePathError):
        return {
            "status": "invalid_output",
            "platform": "tower",
            "message": str(error),
        }
    if isinstance(error, TowerSessionError):
        return {
            "status": error.status,
            "platform": "tower",
            "message": str(error),
        }
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        status = (
            "auth_expired" if code == 401
            else "forbidden" if code == 403
            else "not_found" if code == 404
            else "api_error"
        )
        return {
            "status": status,
            "platform": "tower",
            "message": f"Tower 返回 HTTP {code}",
        }
    if isinstance(error, httpx.HTTPError):
        return {
            "status": "network_error",
            "platform": "tower",
            "message": f"Tower 网络请求失败: {error}",
        }
    return {
        "status": "api_error",
        "platform": "tower",
        "message": str(error),
    }


@mcp.tool()
async def tower_check_auth(url: str = TOWER_BASE) -> dict[str, str]:
    """检查 Tower Cookie；提供任务链接时同时检查任务访问权限。"""
    if not tower_cookie():
        return {"status": "missing_config", "platform": "tower", "message": "未设置 TOWER_COOKIE"}
    if url != TOWER_BASE:
        url_error = validate_tower_todo_url(url)
        if url_error:
            return {"status": "invalid_input", "platform": "tower", "message": url_error}
    try:
        response = await request(url)
    except TowerSessionError as error:
        return {
            "status": error.status,
            "platform": "tower",
            "message": str(error),
        }
    except httpx.HTTPStatusError as error:
        status = "auth_expired" if error.response.status_code == 401 else "forbidden" if error.response.status_code == 403 else "network_error"
        return {"status": status, "platform": "tower", "message": f"Tower 返回 HTTP {error.response.status_code}"}
    except Exception as error:
        return {"status": "network_error", "platform": "tower", "message": str(error)}
    if is_login_page(response):
        return {"status": "auth_expired", "platform": "tower", "message": "Tower Cookie 已过期"}
    return {"status": "success", "platform": "tower", "message": "Tower 认证有效"}


@mcp.tool()
async def tower_read_todo(url: str) -> dict | str:
    """读取 Tower 原始事实与图片到用户缓存，只返回路径、数量和来源摘要。"""
    if not tower_cookie():
        return {
            "status": "missing_config",
            "platform": "tower",
            "message": "未设置 TOWER_COOKIE",
        }
    url_error = validate_tower_todo_url(url)
    if url_error:
        return {
            "status": "invalid_input",
            "platform": "tower",
            "message": url_error,
        }
    try:
        data = await load_todo_data(url)
        image_cache = await cache_tower_images(data, url)
        cache_file = write_tower_raw(data, url, image_cache)
    except Exception as error:
        return tool_error(error)
    return tower_read_summary(data, cache_file, image_cache)


@mcp.tool()
async def tower_download_images(url: str, output_dir: str) -> dict | str:
    """下载 Tower 正文和全部评论中的附件图片，并返回本地文件与来源映射。"""
    if not tower_cookie():
        return "错误: 未设置 TOWER_COOKIE"
    url_error = validate_tower_todo_url(url)
    if url_error:
        return f"错误: {url_error}"
    try:
        data = await load_todo_data(url)
        result = await download_tower_image_attachments(
            data,
            Path(output_dir).expanduser(),
            file_prefix="tower",
        )
    except Exception as error:
        return tool_error(error)
    return {
        **result,
        "platform": "tower",
        "task_title": data["title"],
        "task_url": url,
        "project_sections": data["project_sections"],
        "stale_files_removed": True,
    }


@mcp.tool()
async def tower_add_comment(url: str, content: str, dry_run: bool = True) -> str:
    """向 Tower 发布 Markdown 评论；默认只预览，dry_run=false 才真正发布。"""
    if not tower_cookie():
        return "错误: 未设置 TOWER_COOKIE"
    url_error = validate_tower_todo_url(url)
    if url_error:
        return f"错误: {url_error}"
    try:
        comment_html = text_to_comment_html(content)
        response = await request(url)
    except Exception as error:
        return tool_error(error)
    if is_login_page(response):
        return "错误: Tower Cookie 已过期，请运行 specweaver configure tower 更新后重试"
    soup = BeautifulSoup(response.text, "lxml")
    meta = parse_comment_meta(soup)
    missing = [
        name for name in ("project_guid", "todo_guid", "csrf_token")
        if not meta[name]
    ]
    if missing:
        return f"错误: Tower 页面缺少评论参数: {', '.join(missing)}"

    title = (soup.select_one(".page-inner") or {}).get("data-page-name", "")
    if dry_run:
        return "\n".join([
            "Tower 评论预览（未发布）",
            f"任务: {title or '未解析标题'}",
            f"链接: {url}",
            f"提交内容: {comment_html}",
            "确认无误后，将 dry_run 设为 false 才会真正发布。",
        ])
    try:
        result = await post_comment(meta, comment_html, url)
    except Exception as error:
        return tool_error(error)
    return f"Tower 评论发布成功（HTTP {result.status_code}）: {title or url}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
