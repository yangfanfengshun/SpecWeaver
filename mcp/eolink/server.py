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

import asyncio
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastmcp import FastMCP
import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import read_config


HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
}
LOGIN_PATH = "/server/index.php?g=Web&c=Guest&o=login"
SUCCESS_CODE = "000000"
SESSION_EXPIRED_CODE = "120005"

mcp = FastMCP("SpecWeaver Eolink Reader")
_client: httpx.AsyncClient | None = None
_client_base_url = ""
_login_fingerprint = ""


def to_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def current_settings() -> tuple[str, str, str]:
    config = read_config()
    return (
        config["EOLINK_BASE_URL"].rstrip("/"),
        config["EOLINK_USER"],
        config["EOLINK_PASSWORD"],
    )


def parse_eolink_url(url: str, base_url: str | None = None) -> dict[str, Any]:
    parsed = urlparse(url)
    expected_host = urlparse(base_url or current_settings()[0]).netloc.lower()
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("请提供有效的 Eolink 链接")
    if expected_host and parsed.netloc.lower() != expected_host:
        raise ValueError(f"链接域名与 EOLINK_BASE_URL 不一致: {parsed.netloc}")

    fragment_query = parsed.fragment.partition("?")[2]
    query = parse_qs(fragment_query or parsed.query)

    def first(name: str) -> str:
        return (query.get(name) or [""])[0].strip()

    project_id = first("projectID")
    if not project_id.isdigit():
        raise ValueError("Eolink 链接中缺少有效的 projectID")

    child_group_id = first("childGroupID")
    group_id = child_group_id if child_group_id not in {"", "0", "-1"} else first("groupID")
    if group_id and group_id != "-1" and not group_id.isdigit():
        raise ValueError("Eolink 链接中的 groupID 无效")

    return {
        "projectID": int(project_id),
        "groupID": int(group_id) if group_id and group_id != "-1" else -1,
        "projectName": first("projectName"),
    }


async def get_client(base_url: str) -> httpx.AsyncClient:
    global _client, _client_base_url, _login_fingerprint
    if not base_url:
        raise RuntimeError("未设置 EOLINK_BASE_URL")
    if _client is None or _client_base_url != base_url:
        if _client is not None:
            await _client.aclose()
        _client = httpx.AsyncClient(base_url=base_url, timeout=30, follow_redirects=True)
        _client_base_url = base_url
        _login_fingerprint = ""
    return _client


async def ensure_login(force: bool = False) -> None:
    global _login_fingerprint
    base_url, user, password = current_settings()
    if not user or not password:
        raise RuntimeError("未设置 EOLINK_USER 或 EOLINK_PASSWORD")
    fingerprint = hashlib.sha256(f"{base_url}\0{user}\0{password}".encode()).hexdigest()
    if _login_fingerprint == fingerprint and not force:
        return

    client = await get_client(base_url)
    await client.get("/")
    response = await client.post(
        LOGIN_PATH,
        data={
            "loginName": user,
            "loginPassword": hashlib.md5(password.encode()).hexdigest(),
        },
        headers={**HEADERS, "Origin": base_url, "Referer": f"{base_url}/"},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("statusCode") != SUCCESS_CODE:
        raise RuntimeError(f"Eolink 认证信息无效（状态码 {payload.get('statusCode') or '未知'}）")
    _login_fingerprint = fingerprint


async def api_post(path: str, form: dict[str, Any], retry: bool = True) -> dict:
    global _login_fingerprint
    await ensure_login()
    base_url = current_settings()[0]
    response = await (await get_client(base_url)).post(
        path,
        data=form,
        headers={**HEADERS, "Origin": base_url, "Referer": f"{base_url}/"},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("statusCode") == SESSION_EXPIRED_CODE and retry:
        _login_fingerprint = ""
        await ensure_login(force=True)
        return await api_post(path, form, retry=False)
    if payload.get("statusCode") == SESSION_EXPIRED_CODE:
        raise RuntimeError("Eolink 登录会话已失效，请运行 setup.sh --configure 更新认证后重试")
    return payload


def auth_error(error: Exception) -> dict[str, str]:
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        status = "auth_expired" if code == 401 else "forbidden" if code == 403 else "network_error"
        return {
            "status": status,
            "platform": "eolink",
            "message": f"Eolink 返回 HTTP {code}",
        }
    if isinstance(error, httpx.HTTPError):
        return {"status": "network_error", "platform": "eolink", "message": str(error)}
    message = str(error)
    status = "auth_expired" if any(
        word in message for word in ("认证信息无效", "登录会话已失效")
    ) else "api_error"
    return {"status": status, "platform": "eolink", "message": message}


@mcp.tool()
async def eolink_check_auth() -> dict[str, str]:
    """检查 Eolink 配置和认证状态，不返回账号或密码。"""
    base_url, user, password = current_settings()
    missing = [
        name
        for name, value in (
            ("EOLINK_BASE_URL", base_url),
            ("EOLINK_USER", user),
            ("EOLINK_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        return {
            "status": "missing_config",
            "platform": "eolink",
            "message": f"未设置 {', '.join(missing)}",
        }
    try:
        await ensure_login(force=True)
    except Exception as error:
        return auth_error(error)
    return {"status": "success", "platform": "eolink", "message": "Eolink 认证有效"}


@mcp.tool()
async def eolink_get_projects() -> str:
    """读取 Eolink 全部项目列表。"""
    return to_text(await api_post(
        "/server/index.php?g=Web&c=Project&o=getProjectList",
        {"projectType": "-1"},
    ))


@mcp.tool()
async def eolink_get_interface_by_id(apiID: int) -> str:
    """仅凭 API ID 读取接口详情及接口真实所属项目。"""
    detail = await api_post(
        "/server/index.php?g=Web&c=Api&o=getApi",
        {"apiID": apiID},
    )
    base = ((detail.get("apiInfo") or {}).get("baseInfo") or {})
    project_id = base.get("projectID")
    if not project_id:
        return to_text(detail)
    projects = await api_post(
        "/server/index.php?g=Web&c=Project&o=getProjectList",
        {"projectType": "-1"},
    )
    project = next(
        (
            item for item in projects.get("projectList") or []
            if str(item.get("projectID")) == str(project_id)
        ),
        {"projectID": project_id},
    )
    return to_text({**detail, "projectInfo": project})


@mcp.tool()
async def eolink_get_interface_detail(projectID: int, apiID: int) -> str:
    """使用项目 ID 和 API ID 读取接口详情。"""
    return to_text(await api_post(
        "/server/index.php?g=Web&c=Api&o=getApi",
        {"projectID": projectID, "apiID": apiID},
    ))


@mcp.tool()
async def eolink_read_url(url: str, include_details: bool = True) -> str:
    """直接读取 Eolink 接口列表链接；默认同时读取列表内全部接口详情。"""
    try:
        location = parse_eolink_url(url)
    except ValueError as error:
        return f"错误: {error}"

    project_id = location["projectID"]
    group_id = location["groupID"]
    if group_id == -1:
        path = "/server/index.php?g=Web&c=Api&o=getAllApiList"
        form = {"projectID": project_id, "groupID": "-1"}
    else:
        path = "/server/index.php?g=Web&c=Api&o=getApiList"
        form = {"projectID": project_id, "groupID": group_id}

    api_list_response = await api_post(path, form)
    api_list = api_list_response.get("apiList") or []
    result: dict[str, Any] = {
        "sourceURL": url,
        "location": location,
        "statusCode": api_list_response.get("statusCode"),
        "apiCount": len(api_list),
        "apiList": api_list,
    }
    if include_details and api_list:
        result["apiDetails"] = await asyncio.gather(*(
            api_post(
                "/server/index.php?g=Web&c=Api&o=getApi",
                {"projectID": project_id, "apiID": item["apiID"]},
            )
            for item in api_list
            if item.get("apiID")
        ))
    return to_text(result)


if __name__ == "__main__":
    mcp.run(transport="stdio")
