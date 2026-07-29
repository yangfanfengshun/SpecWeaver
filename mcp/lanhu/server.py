#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = [
#   "cryptography>=43.0.0,<47.0.0",
#   "fastmcp>=3.3.1,<4.0.0",
#   "httpx>=0.27.0,<1.0.0",
#   "python-dotenv>=1.0.0,<2.0.0",
# ]
# ///
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from fastmcp import FastMCP
import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lanhu.api import (
    auth_result_from_payload,
    create_client,
    disabled_or_config_error,
    fetch_design_payloads,
    fetch_design_structure,
    get_lanhu_image,
    is_lanhu_image_url,
    normalize_design_response,
    parse_lanhu_design_url,
    parse_lanhu_project_url,
    select_design_id,
    structure_error,
)
from lanhu.session import (
    LanhuSessionError,
    lanhu_settings,
    run_with_lanhu_session,
)
from lanhu.design import (
    INLINE_NODE_LIMIT,
    extract_slice_assets,
    navigation,
    normalize_design_document,
    write_design_document,
)
from lanhu.download import download_design_images, download_slice_assets


mcp = FastMCP("SpecWeaver Lanhu Reader")


def session_error_result(error: LanhuSessionError) -> dict[str, str]:
    return {
        "status": error.status,
        "platform": "lanhu",
        "message": str(error),
    }


@mcp.tool()
async def lanhu_check_auth(project_url: str = "") -> dict[str, str]:
    """检查蓝湖能力和认证状态；提供标准项目链接时同时检查项目权限。"""
    early = disabled_or_config_error()
    if early:
        return early
    _, cookie, account, password = lanhu_settings()
    if not project_url:
        if account and password:
            method = "账号密码和 Cookie" if cookie else "账号密码"
        else:
            method = "Cookie"
        return {
            "status": "configured",
            "platform": "lanhu",
            "message": f"已配置蓝湖{method}；提供标准项目链接后可验证项目权限",
        }
    try:
        params = parse_lanhu_project_url(project_url)
    except ValueError as error:
        return {"status": "invalid_input", "platform": "lanhu", "message": str(error)}
    try:
        async def operation(active_cookie: str):
            async with create_client(active_cookie) as client:
                return await fetch_design_payloads(
                    client,
                    str(params["project_id"]),
                    params["team_id"],
                )

        image_payload, _, _ = await run_with_lanhu_session(operation)
    except LanhuSessionError as error:
        return session_error_result(error)
    except httpx.HTTPStatusError as error:
        code = error.response.status_code
        status = "auth_expired" if code in {401, 418} else "forbidden" if code == 403 else "api_error"
        return {"status": status, "platform": "lanhu", "message": f"蓝湖返回 HTTP {code}"}
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
    try:
        params = parse_lanhu_project_url(url)
    except ValueError as error:
        return {"status": "invalid_input", "platform": "lanhu", "message": str(error)}
    try:
        async def operation(active_cookie: str):
            async with create_client(active_cookie) as client:
                return await fetch_design_payloads(
                    client,
                    str(params["project_id"]),
                    params["team_id"],
                )

        image_payload, sector_payload, sector_warning = await run_with_lanhu_session(
            operation
        )
    except LanhuSessionError as error:
        return session_error_result(error)
    except httpx.HTTPStatusError as error:
        code = error.response.status_code
        status = "auth_expired" if code in {401, 418} else "forbidden" if code == 403 else "api_error"
        return {"status": status, "platform": "lanhu", "message": f"蓝湖返回 HTTP {code}"}
    except httpx.HTTPError as error:
        return {"status": "network_error", "platform": "lanhu", "message": str(error)}
    except ValueError as error:
        return {"status": "api_error", "platform": "lanhu", "message": f"蓝湖响应无法解析: {error}"}

    auth = auth_result_from_payload(image_payload)
    if auth["status"] != "success":
        return auth
    return normalize_design_response(image_payload, sector_payload, sector_warning)


@mcp.tool()
async def lanhu_get_design_detail(
    url: str,
    image_id: str = "",
    output_file: str = "",
) -> dict[str, Any]:
    """读取已确认设计稿的 Sketch 结构，返回规范化图层树或写入完整 JSON。"""
    early = disabled_or_config_error()
    if early:
        return early
    try:
        params = parse_lanhu_design_url(url)
        selected_id = select_design_id(params, image_id)
        params["image_id"] = selected_id

        async def operation(active_cookie: str):
            async with create_client(active_cookie) as client:
                return await fetch_design_structure(client, params, selected_id)

        detail, sketch = await run_with_lanhu_session(operation)
        document = normalize_design_document(url, params, detail, sketch)
        result: dict[str, Any] = {
            "status": "success",
            "platform": "lanhu",
            "structure_status": "sketch_only",
            "message": "已读取蓝湖真实 Sketch 结构；DDS 因额外认证边界未接入",
            "source": document["source"],
            "canvas": document["canvas"],
            "summary": document["summary"],
            "preview_url": detail.get("url"),
            "navigation": navigation(document["layers"]),
        }
        if output_file:
            result["output_file"] = str(write_design_document(document, output_file))
            result["delivery"] = "file"
            return result
        if document["summary"]["node_count"] > INLINE_NODE_LIMIT:
            result.update({
                "delivery": "summary",
                "truncated": True,
                "message": (
                    "设计稿较大，已返回精简导航；传入绝对 output_file "
                    "可保存完整规范化 JSON"
                ),
            })
            return result
        result["delivery"] = "inline"
        result["truncated"] = False
        result["document"] = document
        return result
    except ValueError as error:
        return {"status": "invalid_input", "platform": "lanhu", "message": str(error)}
    except LanhuSessionError as error:
        return session_error_result(error)
    except Exception as error:
        return structure_error(error)


@mcp.tool()
async def lanhu_download_design_images(
    images: list[dict[str, Any]],
    output_dir: str,
) -> dict[str, Any]:
    """下载已确认采用的蓝湖设计预览图，并返回本地文件与来源映射。"""
    early = disabled_or_config_error()
    if early:
        return early
    try:
        return await run_with_lanhu_session(
            lambda active_cookie: download_design_images(
                active_cookie,
                images,
                output_dir,
            )
        )
    except LanhuSessionError as error:
        return session_error_result(error)
    except ValueError as error:
        return {"status": "invalid_input", "platform": "lanhu", "message": str(error)}


@mcp.tool()
async def lanhu_download_slices(
    url: str,
    image_id: str,
    output_dir: str,
    manifest_file: str = "",
) -> dict[str, Any]:
    """下载已确认设计稿的真实切图，按类型分类、哈希去重并保留来源映射。"""
    early = disabled_or_config_error()
    if early:
        return early
    try:
        params = parse_lanhu_design_url(url)
        selected_id = select_design_id(params, image_id)
        params["image_id"] = selected_id

        async def operation(active_cookie: str):
            async with create_client(active_cookie) as client:
                _, sketch = await fetch_design_structure(
                    client,
                    params,
                    selected_id,
                )
            assets = extract_slice_assets(sketch)
            return await download_slice_assets(
                active_cookie,
                assets,
                output_dir,
                selected_id,
                manifest_file,
            )

        return await run_with_lanhu_session(operation)
    except ValueError as error:
        return {"status": "invalid_input", "platform": "lanhu", "message": str(error)}
    except LanhuSessionError as error:
        return session_error_result(error)
    except Exception as error:
        return structure_error(error)


if __name__ == "__main__":
    mcp.run(transport="stdio")
