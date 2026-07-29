from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
from common import manual_cookie_hint, read_config, update_config_atomic
from lanhu_auth import LanhuLoginError, login_lanhu

Result = TypeVar("Result")
_runtime_cookie = ""
_login_lock: asyncio.Lock | None = None


class LanhuSessionError(RuntimeError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def lanhu_settings() -> tuple[bool, str, str, str]:
    config = read_config()
    normalized = config["LANHU_ENABLED"].strip().lower()
    if normalized and normalized not in {"true", "false"}:
        raise ValueError("LANHU_ENABLED 只接受 true 或 false")
    enabled = normalized != "false"
    return (
        enabled,
        _runtime_cookie or config["LANHU_COOKIE"],
        config["LANHU_PHONE"],
        config["LANHU_PASSWORD"],
    )


def login_lock() -> asyncio.Lock:
    global _login_lock
    if _login_lock is None:
        _login_lock = asyncio.Lock()
    return _login_lock


def is_auth_expired_error(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {401, 418}
    return isinstance(error, RuntimeError) and str(error).startswith("auth_expired:")


def is_auth_expired_result(result: Any) -> bool:
    if isinstance(result, dict):
        if result.get("status") == "auth_expired":
            return True
        code = str(result.get("code", ""))
        if code and code not in {"0", "00000"}:
            message = str(result.get("msg") or result.get("message") or "").lower()
            if any(
                marker in message
                for marker in ("登录", "login", "cookie", "token", "认证")
            ):
                return True
        return any(is_auth_expired_result(item) for item in result.get("failures", []))
    if isinstance(result, (list, tuple)):
        return any(is_auth_expired_result(item) for item in result)
    return False


async def refresh_lanhu_session(stale_fingerprint: str) -> None:
    global _runtime_cookie
    async with login_lock():
        _, current_cookie, _, _ = lanhu_settings()
        current_fingerprint = hashlib.sha256(current_cookie.encode()).hexdigest()
        if current_fingerprint != stale_fingerprint:
            return
        config = read_config()
        account = config["LANHU_PHONE"]
        password = config["LANHU_PASSWORD"]
        if not account or not password:
            raise LanhuSessionError(
                "auth_expired",
                "蓝湖 Cookie 已过期，且未配置手机号/邮箱和密码；"
                + manual_cookie_hint("lanhu", "LANHU_COOKIE"),
            )
        try:
            renewed_cookie = await asyncio.to_thread(
                login_lanhu,
                account,
                password,
            )
        except LanhuLoginError as error:
            if error.kind == "credentials":
                status = "auth_expired"
                message = "蓝湖手机号/邮箱或密码已失效"
            elif error.kind == "locked":
                status = "auth_expired"
                message = "蓝湖账号已被锁定"
            elif error.kind == "verification":
                status = "verification_required"
                message = "蓝湖要求人机验证或手机号认证"
            elif error.kind == "network":
                status = "network_error"
                message = "蓝湖登录网络异常"
            else:
                status = "compatibility_error"
                message = "蓝湖网页登录流程暂时不可用"
            raise LanhuSessionError(
                status,
                f"{message}；{manual_cookie_hint('lanhu', 'LANHU_COOKIE')}",
            ) from error
        update_config_atomic({"LANHU_COOKIE": renewed_cookie})
        _runtime_cookie = renewed_cookie


async def run_with_lanhu_session(
    operation: Callable[[str], Awaitable[Result]],
) -> Result:
    _, stale_cookie, _, _ = lanhu_settings()
    try:
        result = await operation(stale_cookie)
    except Exception as error:
        if not is_auth_expired_error(error):
            raise
    else:
        if not is_auth_expired_result(result):
            return result

    stale_fingerprint = hashlib.sha256(stale_cookie.encode()).hexdigest()
    await refresh_lanhu_session(stale_fingerprint)
    _, renewed_cookie, _, _ = lanhu_settings()
    try:
        result = await operation(renewed_cookie)
    except Exception as error:
        if not is_auth_expired_error(error):
            raise
        raise LanhuSessionError(
            "auth_expired",
            "蓝湖自动续期后认证仍然失效；"
            + manual_cookie_hint("lanhu", "LANHU_COOKIE"),
        ) from error
    if is_auth_expired_result(result):
        raise LanhuSessionError(
            "auth_expired",
            "蓝湖自动续期后认证仍然失效；"
            + manual_cookie_hint("lanhu", "LANHU_COOKIE"),
        )
    return result
