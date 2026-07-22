#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = [
#   "beautifulsoup4>=4.12.0,<5.0.0",
#   "fastmcp>=3.3.1,<4.0.0",
#   "httpx>=0.27.0,<1.0.0",
#   "lxml>=5.0.0,<7.0.0",
#   "mistune>=3.0.0,<4.0.0",
#   "python-dotenv>=1.0.0,<2.0.0",
# ]
# ///
from __future__ import annotations

from collections import deque
import hashlib
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from bs4 import BeautifulSoup
from fastmcp import FastMCP
from fastmcp.utilities.types import Image
import httpx
import mistune


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import IMAGE_EXTENSIONS, prepare_output_dir, read_config


TOWER_BASE = "https://tower.im"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

mcp = FastMCP("SpecWeaver Tower Reader")
_client: httpx.AsyncClient | None = None
_client_cookie_fingerprint = ""
markdown_to_html = mistune.create_markdown(
    escape=True,
    hard_wrap=True,
    plugins=["strikethrough", "table", "task_lists", "url"],
)


def tower_cookie() -> str:
    return read_config()["TOWER_COOKIE"]


def cookies_from_header(value: str) -> httpx.Cookies:
    cookies = httpx.Cookies()
    if not value:
        return cookies
    parsed = SimpleCookie()
    try:
        parsed.load(value)
    except CookieError as error:
        raise ValueError("TOWER_COOKIE 格式无效") from error
    if not parsed:
        raise ValueError("TOWER_COOKIE 格式无效")
    for name, morsel in parsed.items():
        cookies.set(name, morsel.value, domain=".tower.im", path="/")
    return cookies


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


async def request(url: str) -> httpx.Response:
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
            headers=HEADERS,
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


def text_of(element) -> str:
    return element.get_text(" ", strip=True) if element else ""


def parse_ordered_content(element) -> dict:
    soup = BeautifulSoup(str(element), "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    images = []
    for image in soup.find_all("img"):
        src = image.get("src", "")
        alt = image.get("alt", "")
        if not src:
            image.replace_with(alt)
            continue
        images.append({
            "position": len(images) + 1,
            "source_url": src,
            "alt": alt,
        })
        escaped_alt = (alt or f"Tower 图片 {len(images)}").replace("\\", "\\\\")
        escaped_alt = escaped_alt.replace("[", "\\[").replace("]", "\\]")
        image.replace_with(f"![{escaped_alt}]({src})")
    return {
        "text": soup.get_text("\n", strip=True),
        "images": images,
    }


def clean_html(element) -> str:
    return parse_ordered_content(element)["text"]


def validate_tower_todo_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "请提供 Tower HTTPS 任务链接"
    if parsed.netloc not in {"tower.im", "www.tower.im"} or "/todos/" not in parsed.path:
        return "请提供有效的 Tower 任务链接"
    return None


def is_login_page(response: httpx.Response) -> bool:
    path = response.url.path.lower()
    sample = response.text[:5000].lower()
    return (
        "/login" in path
        or "/sign_in" in path
        or "登录" in response.text[:5000]
        or "login" in sample
    )


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
        ordered_content = parse_ordered_content(content)
        if not ordered_content["text"]:
            continue
        wrapper = content.find_parent(class_="comment")
        author = text_of(wrapper.select_one("a.author")) if wrapper else ""
        comments.append({
            "author": author,
            "text": ordered_content["text"],
            "images": ordered_content["images"],
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


def parse_images(soup: BeautifulSoup) -> list[str]:
    urls = []
    for element in soup.select("img[src], a[href]"):
        value = element.get("src") or element.get("href") or ""
        parsed = urlparse(value)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        is_attachment = (
            host in {"attachments.tower.im", "tower.im", "www.tower.im"}
            and (host == "attachments.tower.im" or "/attfiles/" in path)
        )
        if is_attachment and value not in urls:
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


async def read_stream_fragments(soup: BeautifulSoup) -> list[str]:
    queue = deque(
        element.get("data-url")
        for element in soup.select("[data-comment-streams-range][data-url]")
        if element.get("data-url")
    )
    visited: set[str] = set()
    fragments = []
    while queue:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        fragment = parse_stream_response((await request(url)).text)
        fragments.append(fragment)
        fragment_soup = BeautifulSoup(fragment, "lxml")
        for element in fragment_soup.select("[data-comment-streams-range][data-url]"):
            next_url = element.get("data-url")
            if next_url and next_url not in visited:
                queue.append(next_url)
    return fragments


def parse_todo(soup: BeautifulSoup, url: str) -> dict:
    page = soup.select_one(".page-inner")
    data = {
        "title": page.get("data-page-name", "") if page else "",
        "url": url,
        "created_at": page.get("data-since", "") if page else "",
        "status": "进行中" if soup.select_one("[data-tooltip*='正在进行']") else "待处理",
        "comments": parse_comments(soup),
        "image_urls": parse_images(soup),
        "project_sections": parse_project_sections(soup),
    }
    data["todo_id"] = text_of(soup.select_one(".original-text"))
    data["assignee"] = text_of(soup.select_one(".addition-content.has-assignee"))
    due = soup.select_one("tr-detail-date-time input[type=hidden]")
    data["due_date"] = due.get("value", "") if due else ""
    description = soup.select_one(".desc-content")
    ordered_description = (
        parse_ordered_content(description)
        if description else {"text": "", "images": []}
    )
    data["description"] = ordered_description["text"]
    data["description_images"] = ordered_description["images"]
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
    return data


async def load_todo_data(url: str) -> dict:
    response = await request(url)
    if is_login_page(response):
        raise RuntimeError("Tower Cookie 已过期，请运行 setup.sh --configure 更新后重试")
    soup = BeautifulSoup(response.text, "lxml")
    data = parse_todo(soup, url)
    if not data["title"]:
        raise RuntimeError("无法解析 Tower 任务")

    fragments = await read_stream_fragments(soup)
    for fragment in fragments:
        fragment_soup = BeautifulSoup(fragment, "lxml")
        for comment in parse_comments(fragment_soup):
            if comment not in data["comments"]:
                data["comments"].append(comment)
        for image_url in parse_images(fragment_soup):
            if image_url not in data["image_urls"]:
                data["image_urls"].append(image_url)
    data["image_occurrences"] = build_image_occurrences(data)
    data["stream_count"] = len(fragments)
    return data


def format_todo(data: dict) -> str:
    lines = [f"# {data['title']}", f"Tower 链接: {data['url']}"]
    if data.get("todo_id"):
        lines.append(f"ID: {data['todo_id']}")
    lines.append(" | ".join([
        f"状态: {data['status']}",
        f"负责人: {data['assignee'] or '未提供'}",
        f"截止时间: {data['due_date'] or '未提供'}",
        f"创建时间: {data['created_at'] or '未提供'}",
    ]))
    if data["project_sections"]:
        lines.extend(["", "## 所属分类与分组"])
        for item in data["project_sections"]:
            lines.append(
                f"- 分类: {item['category'] or '未提供'} | 分组: {item['section'] or '未提供'}"
            )
    if data["parents"]:
        lines.extend(["", "## 父任务"])
        lines.extend(f"- {item['title']}: {item['url']}" for item in data["parents"])
    if data["description"]:
        lines.extend(["", "## 正文", data["description"]])
    lines.extend(["", f"## 子任务 ({len(data['sub_todos'])})"])
    lines.extend(f"- {item['title']}: {item['url']}" for item in data["sub_todos"])
    lines.extend(["", f"## 评论 ({len(data['comments'])})"])
    for comment in data["comments"]:
        prefix = f"{comment['author']}: " if comment["author"] else ""
        lines.append(prefix + comment["text"])
    lines.extend(["", f"> 已读取全部延迟加载记录（{data['stream_count']} 个区间）。"])
    lines.extend(["", f"## 图片出现位置 ({len(data['image_occurrences'])})"])
    for item in data["image_occurrences"]:
        scope = "正文" if item["scope"] == "description" else f"评论 {item['scope_index']}"
        lines.append(
            f"- occurrence {item['occurrence_index']}: {scope} / "
            f"图片位置 {item['position']} / 说明 {item['alt'] or '未提供'} / "
            f"来源 {item['source_url']}"
        )
    lines.extend(["", f"## 附件图片 ({len(data['image_urls'])})"])
    lines.extend(f"- 图片 {index}: {value}" for index, value in enumerate(data["image_urls"], 1))
    return "\n".join(lines)


def tool_error(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code in {401, 403}:
            return "错误: Tower 认证信息已失效或无访问权限"
        return f"错误: Tower 返回 HTTP {error.response.status_code}"
    if isinstance(error, httpx.HTTPError):
        return f"错误: Tower 网络请求失败: {error}"
    return f"错误: {error}"


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
    except httpx.HTTPStatusError as error:
        status = "auth_expired" if error.response.status_code == 401 else "forbidden" if error.response.status_code == 403 else "network_error"
        return {"status": status, "platform": "tower", "message": f"Tower 返回 HTTP {error.response.status_code}"}
    except Exception as error:
        return {"status": "network_error", "platform": "tower", "message": str(error)}
    if is_login_page(response):
        return {"status": "auth_expired", "platform": "tower", "message": "Tower Cookie 已过期"}
    return {"status": "success", "platform": "tower", "message": "Tower 认证有效"}


@mcp.tool()
async def tower_read_todo(url: str, include_images: bool = False) -> list[str | Image] | str:
    """读取 Tower 分类、正文、全部评论和子任务；确认处理模式后可选择加载附件图片。"""
    if not tower_cookie():
        return "错误: 未设置 TOWER_COOKIE"
    url_error = validate_tower_todo_url(url)
    if url_error:
        return f"错误: {url_error}"
    try:
        data = await load_todo_data(url)
    except Exception as error:
        return tool_error(error)

    content: list[str | Image] = [format_todo(data)]
    if not include_images:
        return content
    for index, image_url in enumerate(data["image_urls"], 1):
        try:
            image_response = await request(image_url)
            content_type = image_response.headers.get("content-type", "").split(";", 1)[0]
            if not content_type.startswith("image/"):
                content.append(f"附件图片 {index} 读取失败: {content_type or '未知类型'}")
                continue
            content.extend([
                f"附件图片 {index}",
                Image(data=image_response.content, format=content_type.removeprefix("image/")),
            ])
        except Exception as error:
            content.append(f"附件图片 {index} 读取失败: {tool_error(error)}")
    return content


@mcp.tool()
async def tower_download_images(url: str, output_dir: str) -> dict | str:
    """下载 Tower 正文和全部评论中的附件图片，并返回本地文件与来源映射。"""
    if not tower_cookie():
        return "错误: 未设置 TOWER_COOKIE"
    url_error = validate_tower_todo_url(url)
    if url_error:
        return f"错误: {url_error}"
    try:
        target_dir = prepare_output_dir(output_dir)
        data = await load_todo_data(url)
    except Exception as error:
        return tool_error(error)

    downloaded = []
    failures = []
    hashes: dict[str, dict] = {}
    saved_names: set[str] = set()
    source_results: dict[str, dict] = {}

    def record_failure(
        source_index: int,
        source_url: str,
        status: str,
        error: str,
    ) -> None:
        failures.append({
            "source_index": source_index,
            "source_url": source_url,
            "status": status,
            "error": error,
        })
        source_results[source_url] = {"status": status, "error": error}

    for source_index, image_url in enumerate(data["image_urls"], 1):
        try:
            response = await request(image_url)
            if is_login_page(response):
                record_failure(
                    source_index,
                    image_url,
                    "auth_expired",
                    "Tower Cookie 已过期",
                )
                continue
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            extension = IMAGE_EXTENSIONS.get(content_type)
            if not extension:
                raise ValueError(f"不支持的图片类型: {content_type or '未知类型'}")
            content_hash = hashlib.sha256(response.content).hexdigest()
            if content_hash in hashes:
                original = hashes[content_hash]
                item = {
                    "source_index": source_index,
                    "source_url": image_url,
                    "file_name": original["file_name"],
                    "path": original["path"],
                    "content_type": content_type,
                    "duplicate": True,
                    "duplicate_of": original["file_name"],
                    "sha256": content_hash,
                }
                downloaded.append(item)
                source_results[image_url] = {
                    "status": "success",
                    "file_name": item["file_name"],
                    "path": item["path"],
                }
                continue
            file_name = f"tower-{len(hashes) + 1:03d}{extension}"
            file_path = target_dir / file_name
            file_path.write_bytes(response.content)
            item = {
                "source_index": source_index,
                "source_url": image_url,
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
            source_results[image_url] = {
                "status": "success",
                "file_name": file_name,
                "path": str(file_path),
            }
        except httpx.HTTPStatusError as error:
            status = "auth_expired" if error.response.status_code == 401 else "forbidden" if error.response.status_code == 403 else "api_error"
            record_failure(
                source_index,
                image_url,
                status,
                f"Tower 返回 HTTP {error.response.status_code}",
            )
        except httpx.HTTPError as error:
            record_failure(source_index, image_url, "network_error", str(error))
        except Exception as error:
            record_failure(source_index, image_url, "download_error", str(error))

    if not failures:
        owned_pattern = re.compile(r"tower-\d{3}\.(gif|jpe?g|png|svg|webp)$", re.I)
        for old_file in target_dir.iterdir():
            if old_file.is_file() and owned_pattern.fullmatch(old_file.name) and old_file.name not in saved_names:
                old_file.unlink()
    status = "success" if not failures else "partial"
    if failures and not downloaded:
        failure_statuses = {item["status"] for item in failures}
        if len(failure_statuses) == 1:
            status = failure_statuses.pop()
    occurrences = []
    for occurrence in data.get("image_occurrences", []):
        occurrence_result = {
            **occurrence,
            **source_results.get(occurrence["source_url"], {
                "status": "not_downloaded",
                "error": "未找到对应的附件下载结果",
            }),
        }
        occurrences.append(occurrence_result)
    return {
        "status": status,
        "platform": "tower",
        "task_title": data["title"],
        "task_url": url,
        "project_sections": data["project_sections"],
        "source_count": len(data["image_urls"]),
        "saved_count": len(hashes),
        "output_dir": str(target_dir),
        "images": downloaded,
        "occurrences": occurrences,
        "failures": failures,
        "stale_files_removed": not failures,
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
        return "错误: Tower Cookie 已过期，请运行 setup.sh --configure 更新后重试"
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
