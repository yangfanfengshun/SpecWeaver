#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = [
#   "fastmcp>=3.3.1,<4.0.0",
#   "httpx>=0.27.0,<1.0.0",
#   "python-dotenv>=1.0.0,<2.0.0",
# ]
# ///
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from fastmcp import FastMCP
import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import IMAGE_EXTENSIONS, parse_strict_bool, prepare_output_dir, read_config


LANHU_BASE = "https://lanhuapp.com"
SUCCESS_CODE = "00000"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://lanhuapp.com/web/",
    "Accept": "application/json, text/plain, */*",
    "request-from": "web",
}

mcp = FastMCP("SpecWeaver Lanhu Reader")


def lanhu_settings() -> tuple[bool, str]:
    config = read_config()
    try:
        enabled = parse_strict_bool(config["LANHU_ENABLED"], default=True)
    except ValueError as error:
        raise ValueError(f"LANHU_ENABLED {error}") from error
    return enabled, config["LANHU_COOKIE"]


def parse_lanhu_project_url(url: str) -> dict[str, str | None]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "lanhuapp.com":
        raise ValueError("请提供蓝湖 HTTPS 标准项目链接")
    fragment_path, separator, fragment_query = parsed.fragment.partition("?")
    if not separator or "/item/project/stage" not in fragment_path:
        raise ValueError("仅支持蓝湖 stage 标准项目链接")
    query = parse_qs(fragment_query)
    project_id = (query.get("pid") or [""])[0].strip()
    team_id = (query.get("tid") or [""])[0].strip() or None
    if not project_id:
        raise ValueError("蓝湖链接缺少 pid（project_id）")
    return {"project_id": project_id, "team_id": team_id}


def is_lanhu_image_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host == "lanhuapp.com" or host.endswith(".lanhuapp.com")
    )


def normalize_design_sectors(
    sectors: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    sector_by_id = {
        str(sector["id"]): sector
        for sector in sectors or []
        if sector.get("id")
    }
    path_cache: dict[str, str] = {}

    def build_path(sector_id: str, trail: frozenset[str] = frozenset()) -> str:
        if sector_id in path_cache:
            return path_cache[sector_id]
        sector = sector_by_id.get(sector_id, {})
        name = str(sector.get("name") or sector_id)
        parent_id = str(sector.get("parent_id") or "")
        if sector_id in trail:
            return name
        if parent_id in sector_by_id:
            parent_path = build_path(parent_id, trail | {sector_id})
            path = f"{parent_path}/{name}" if parent_path else name
        else:
            path = name
        path_cache[sector_id] = path
        return path

    normalized: list[dict[str, Any]] = []
    image_sector_map: dict[str, list[dict[str, Any]]] = {}
    for sector_id, sector in sector_by_id.items():
        item = {
            "id": sector_id,
            "parent_id": sector.get("parent_id") or None,
            "name": sector.get("name"),
            "path": build_path(sector_id),
            "order": sector.get("order", 0),
            "image_count": len(sector.get("images") or []),
        }
        normalized.append(item)
        for image_id in sector.get("images") or []:
            if image_id:
                image_sector_map.setdefault(str(image_id), []).append(dict(item))
    return normalized, image_sector_map


def normalize_design_response(
    image_payload: dict[str, Any],
    sector_payload: dict[str, Any] | None = None,
    sector_warning: str | None = None,
) -> dict[str, Any]:
    if str(image_payload.get("code")) != SUCCESS_CODE:
        return {
            "status": "error",
            "message": image_payload.get("msg") or "蓝湖接口返回未知错误",
        }

    sectors: list[dict[str, Any]] = []
    image_sector_map: dict[str, list[dict[str, Any]]] = {}
    if sector_payload and str(sector_payload.get("code")) == SUCCESS_CODE:
        sectors, image_sector_map = normalize_design_sectors(
            (sector_payload.get("data") or {}).get("sectors") or []
        )
    elif sector_payload:
        sector_warning = str(sector_payload.get("msg") or "分组接口返回未知错误")

    project_data = image_payload.get("data") or {}
    designs = []
    for index, image in enumerate(project_data.get("images") or [], 1):
        design_sectors = image_sector_map.get(str(image.get("id")), [])
        designs.append({
            "index": index,
            "id": image.get("id"),
            "name": image.get("name"),
            "width": image.get("width"),
            "height": image.get("height"),
            "url": image.get("url"),
            "has_comment": image.get("has_comment", False),
            "update_time": image.get("update_time"),
            "sectors": [item["name"] for item in design_sectors if item.get("name")],
        })

    result: dict[str, Any] = {
        "status": "success",
        "project_name": project_data.get("name"),
        "total_sectors": len(sectors),
        "ungrouped_design_count": sum(1 for design in designs if not design["sectors"]),
        "sectors": sectors,
        "total_designs": len(designs),
        "designs": designs,
    }
    if sector_warning:
        result["sector_warning"] = sector_warning
    return result


def auth_result_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    if str(payload.get("code")) == SUCCESS_CODE:
        return {"status": "success", "platform": "lanhu", "message": "蓝湖认证有效"}
    message = str(payload.get("msg") or "蓝湖接口返回未知错误")
    lowered = message.lower()
    if any(word in lowered for word in ("登录", "login", "cookie", "token", "认证")):
        status = "auth_expired"
    elif any(word in lowered for word in ("权限", "permission", "forbidden", "无权")):
        status = "forbidden"
    else:
        status = "api_error"
    return {"status": status, "platform": "lanhu", "message": message}


def create_client(cookie: str, *, image_accept: bool = False) -> httpx.AsyncClient:
    headers = dict(HEADERS)
    headers["Cookie"] = cookie
    if image_accept:
        headers["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
    return httpx.AsyncClient(timeout=60, headers=headers, follow_redirects=False)


async def get_lanhu_image(client: httpx.AsyncClient, url: str) -> httpx.Response:
    current = url
    for _ in range(6):
        if not is_lanhu_image_url(current):
            raise ValueError("图片请求或重定向目标不是蓝湖 HTTPS 域名")
        response = await client.get(current, follow_redirects=False)
        if not response.is_redirect:
            response.raise_for_status()
            return response
        location = response.headers.get("location")
        if not location:
            raise ValueError("蓝湖图片重定向缺少 Location")
        current = urljoin(str(response.url), location)
    raise ValueError("蓝湖图片重定向次数过多")


async def fetch_design_payloads(
    client: httpx.AsyncClient,
    project_id: str,
    team_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    image_params = {
        "project_id": project_id,
        "dds_status": "1",
        "position": "1",
        "show_cb_src": "1",
        "comment": "1",
    }
    if team_id:
        image_params["team_id"] = team_id

    sector_payload = None
    sector_warning = None
    try:
        sector_response = await client.get(
            f"{LANHU_BASE}/api/project/project_sectors",
            params={"project_id": project_id},
        )
        sector_response.raise_for_status()
        sector_payload = sector_response.json()
    except Exception as error:
        sector_warning = f"设计分组读取失败: {error}"

    image_response = await client.get(
        f"{LANHU_BASE}/api/project/images",
        params=image_params,
    )
    image_response.raise_for_status()
    return image_response.json(), sector_payload, sector_warning


def disabled_or_config_error() -> dict[str, str] | None:
    try:
        enabled, cookie = lanhu_settings()
    except ValueError as error:
        return {"status": "config_error", "platform": "lanhu", "message": str(error)}
    if not enabled:
        return {
            "status": "disabled",
            "platform": "lanhu",
            "message": "蓝湖能力未启用（LANHU_ENABLED=false）",
        }
    if not cookie:
        return {"status": "missing_config", "platform": "lanhu", "message": "未设置 LANHU_COOKIE"}
    return None


@mcp.tool()
async def lanhu_check_auth(project_url: str = "") -> dict[str, str]:
    """检查蓝湖能力和认证状态；提供标准项目链接时同时检查项目权限。"""
    early = disabled_or_config_error()
    if early:
        return early
    _, cookie = lanhu_settings()
    if not project_url:
        return {
            "status": "configured",
            "platform": "lanhu",
            "message": "已配置蓝湖 Cookie；提供标准项目链接后可验证登录状态和项目权限",
        }
    try:
        params = parse_lanhu_project_url(project_url)
    except ValueError as error:
        return {"status": "invalid_input", "platform": "lanhu", "message": str(error)}
    try:
        async with create_client(cookie) as client:
            image_payload, _, _ = await fetch_design_payloads(
                client,
                str(params["project_id"]),
                params["team_id"],
            )
    except httpx.HTTPStatusError as error:
        status = "auth_expired" if error.response.status_code == 401 else "forbidden" if error.response.status_code == 403 else "api_error"
        return {"status": status, "platform": "lanhu", "message": f"蓝湖返回 HTTP {error.response.status_code}"}
    except httpx.HTTPError as error:
        return {"status": "network_error", "platform": "lanhu", "message": str(error)}
    except ValueError as error:
        return {"status": "api_error", "platform": "lanhu", "message": f"蓝湖响应无法解析: {error}"}
    return auth_result_from_payload(image_payload)


@mcp.tool()
async def lanhu_get_designs(url: str) -> dict[str, Any]:
    """读取蓝湖标准 stage 项目的项目名称、设计分组和设计图列表。"""
    early = disabled_or_config_error()
    if early:
        return early
    _, cookie = lanhu_settings()
    try:
        params = parse_lanhu_project_url(url)
    except ValueError as error:
        return {"status": "invalid_input", "platform": "lanhu", "message": str(error)}
    try:
        async with create_client(cookie) as client:
            image_payload, sector_payload, sector_warning = await fetch_design_payloads(
                client,
                str(params["project_id"]),
                params["team_id"],
            )
    except httpx.HTTPStatusError as error:
        status = "auth_expired" if error.response.status_code == 401 else "forbidden" if error.response.status_code == 403 else "api_error"
        return {
            "status": status,
            "platform": "lanhu",
            "message": f"蓝湖返回 HTTP {error.response.status_code}",
        }
    except httpx.HTTPError as error:
        return {"status": "network_error", "platform": "lanhu", "message": str(error)}
    except ValueError as error:
        return {"status": "api_error", "platform": "lanhu", "message": f"蓝湖响应无法解析: {error}"}

    auth = auth_result_from_payload(image_payload)
    if auth["status"] != "success":
        return auth
    return normalize_design_response(image_payload, sector_payload, sector_warning)


@mcp.tool()
async def lanhu_download_design_images(
    images: list[dict[str, Any]],
    output_dir: str,
) -> dict[str, Any]:
    """下载已确认采用的蓝湖设计原图，并返回本地文件与来源映射。"""
    early = disabled_or_config_error()
    if early:
        return early
    _, cookie = lanhu_settings()
    try:
        target_dir = prepare_output_dir(output_dir)
    except ValueError as error:
        return {"status": "invalid_input", "message": str(error)}

    downloaded: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    hashes: dict[str, dict[str, Any]] = {}
    saved_names: set[str] = set()

    async with create_client(cookie, image_accept=True) as client:
        for source_index, image in enumerate(images, 1):
            design_name = str(image.get("name") or "")
            design_id = str(image.get("id") or "")
            image_url = str(image.get("url") or "")
            try:
                if not is_lanhu_image_url(image_url):
                    raise ValueError("只允许下载蓝湖 HTTPS 图片链接")
                response = await get_lanhu_image(client, image_url)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                extension = IMAGE_EXTENSIONS.get(content_type)
                if not extension:
                    raise ValueError(f"不支持的图片类型: {content_type or '未知类型'}")

                content_hash = hashlib.sha256(response.content).hexdigest()
                if content_hash in hashes:
                    downloaded.append({
                        "source_index": source_index,
                        "design_id": design_id,
                        "design_name": design_name,
                        "source_url": image_url,
                        "duplicate": True,
                        "duplicate_of": hashes[content_hash]["file_name"],
                        "sha256": content_hash,
                    })
                    continue

                file_name = f"lanhu-{len(hashes) + 1:03d}{extension}"
                file_path = target_dir / file_name
                file_path.write_bytes(response.content)
                item = {
                    "source_index": source_index,
                    "design_id": design_id,
                    "design_name": design_name,
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
            except httpx.HTTPStatusError as error:
                status = "auth_expired" if error.response.status_code == 401 else "forbidden" if error.response.status_code == 403 else "api_error"
                failures.append({
                    "source_index": source_index,
                    "design_id": design_id,
                    "design_name": design_name,
                    "source_url": image_url,
                    "status": status,
                    "error": f"蓝湖返回 HTTP {error.response.status_code}",
                })
            except httpx.HTTPError as error:
                failures.append({
                    "source_index": source_index,
                    "design_id": design_id,
                    "design_name": design_name,
                    "source_url": image_url,
                    "status": "network_error",
                    "error": str(error),
                })
            except Exception as error:
                failures.append({
                    "source_index": source_index,
                    "design_id": design_id,
                    "design_name": design_name,
                    "source_url": image_url,
                    "status": "invalid_input",
                    "error": str(error),
                })

    if not failures:
        owned_pattern = re.compile(r"lanhu-\d{3}\.(gif|jpe?g|png|svg|webp)$", re.I)
        for old_file in target_dir.iterdir():
            if old_file.is_file() and owned_pattern.fullmatch(old_file.name) and old_file.name not in saved_names:
                old_file.unlink()

    status = "success" if not failures else "partial"
    if failures and not downloaded:
        failure_statuses = {item["status"] for item in failures}
        if len(failure_statuses) == 1:
            status = failure_statuses.pop()
    return {
        "status": status,
        "platform": "lanhu",
        "source_count": len(images),
        "saved_count": len(hashes),
        "output_dir": str(target_dir),
        "images": downloaded,
        "failures": failures,
        "stale_files_removed": not failures,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
