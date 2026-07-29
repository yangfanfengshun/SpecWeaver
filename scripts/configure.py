#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = [
#   "httpx>=0.27.0,<1.0.0",
#   "python-dotenv>=1.0.0,<2.0.0",
# ]
# ///
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
from pathlib import Path
import readline
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

from dotenv import dotenv_values
import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))
from tower_auth import (
    TowerLoginError,
    cookies_from_header,
    is_login_response,
    login_tower,
)


CONFIG_KEYS = (
    "TOWER_EMAIL",
    "TOWER_PASSWORD",
    "TOWER_COOKIE",
    "EOLINK_BASE_URL",
    "EOLINK_USER",
    "EOLINK_PASSWORD",
    "LANHU_ENABLED",
    "LANHU_COOKIE",
)
PLATFORMS = ("tower", "eolink", "lanhu")
CONFIGURE_DEFERRED_PLATFORMS = frozenset(("eolink", "lanhu"))
PLATFORM_LABELS = {
    "tower": "Tower",
    "eolink": "Eolink",
    "lanhu": "蓝湖",
}


class SkipPlatform(Exception):
    pass


def config_file() -> Path:
    root = Path(os.getenv("SPECWEAVER_HOME", Path.home() / ".specweaver")).expanduser()
    return root / ".env"


def load_existing(path: Path) -> dict[str, str]:
    values = dotenv_values(path) if path.is_file() else {}
    return {key: str(values.get(key) or "") for key in CONFIG_KEYS}


def parse_enabled(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("LANHU_ENABLED 只接受 true 或 false")


def quote_env(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def render_env(values: dict[str, str]) -> str:
    lines = [f"{key}={quote_env(values.get(key, ''))}" for key in CONFIG_KEYS]
    return "\n".join(lines) + "\n"


def write_config_atomic(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".env.", dir=path.parent, text=True)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(render_env(values))
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(0o600)
        os.replace(temp_path, path)
        path.chmod(0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def platform_is_complete(platform: str, values: dict[str, str]) -> bool:
    if platform == "tower":
        return bool(values["TOWER_COOKIE"].strip())
    if platform == "eolink":
        return all(
            values[key].strip()
            for key in ("EOLINK_BASE_URL", "EOLINK_USER", "EOLINK_PASSWORD")
        )
    if platform == "lanhu":
        try:
            enabled = parse_enabled(values["LANHU_ENABLED"])
        except ValueError:
            return False
        return not enabled or bool(values["LANHU_COOKIE"].strip())
    raise ValueError(f"未知平台: {platform}")


def required_keys(
    platforms: list[str],
    values: dict[str, str],
    *,
    tower_cookie_only: bool = False,
) -> list[str]:
    required: list[str] = []
    if "tower" in platforms:
        if tower_cookie_only:
            required.append("TOWER_COOKIE")
        else:
            required.extend(("TOWER_EMAIL", "TOWER_PASSWORD"))
    if "eolink" in platforms:
        required.extend(("EOLINK_BASE_URL", "EOLINK_USER", "EOLINK_PASSWORD"))
    if "lanhu" in platforms:
        required.append("LANHU_ENABLED")
        if values["LANHU_ENABLED"] and parse_enabled(values["LANHU_ENABLED"]):
            required.append("LANHU_COOKIE")
    return required


def merged_non_interactive(
    existing: dict[str, str],
    platforms: list[str] | None = None,
    *,
    tower_cookie_only: bool = False,
) -> dict[str, str]:
    values = dict(existing)
    for key in CONFIG_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    if not values["LANHU_ENABLED"]:
        values["LANHU_ENABLED"] = "true"
    targets = platforms or list(PLATFORMS)
    missing = [
        key
        for key in required_keys(
            targets,
            values,
            tower_cookie_only=tower_cookie_only,
        )
        if not values[key].strip()
    ]
    if missing:
        raise ValueError(f"非交互模式缺少必要配置: {', '.join(missing)}")
    return values


def prompt_value(
    key: str,
    label: str,
    current: str,
    *,
    secret: bool = False,
    required: bool = True,
) -> str:
    status = "已配置" if current else "未配置"
    if secret:
        hint = "回车保留当前值" if current else "回车跳过该平台"
        value = input(f"{label}（{status}，明文输入，{hint}）: ").strip()
    else:
        visible = f"当前值: {current}" if current else status
        hint = "回车保留" if current else "回车跳过该平台"
        value = input(f"{label}（{visible}，{hint}）: ").strip()
    result = value or current
    if required and not result:
        raise SkipPlatform
    return result


def prompt_password(label: str, current: str) -> str:
    status = "已配置" if current else "未配置"
    hint = "回车保留当前值" if current else "回车跳过该平台"
    value = getpass.getpass(
        f"{label}（{status}，输入不回显，{hint}）: "
    )
    result = value or current
    if not result:
        raise SkipPlatform
    return result


def select_platforms() -> list[str]:
    while True:
        print(
            "\n请选择需要配置的平台，可多选：\n\n"
            "1. Tower\n"
            "2. Eolink\n"
            "3. 蓝湖\n"
            "4. 全部\n"
            "5. 退出\n"
        )
        answer = input("请输入编号，多个用逗号分隔，例如：1,3\n> ").strip()
        parts = [part.strip() for part in answer.replace("，", ",").split(",")]
        if not answer or any(not part for part in parts):
            print("请输入 1-5 的编号。")
            continue
        if any(part not in {"1", "2", "3", "4", "5"} for part in parts):
            print("存在无效编号，请重新选择。")
            continue
        if len(parts) != len(set(parts)):
            print("编号不能重复，请重新选择。")
            continue
        if "4" in parts and len(parts) > 1:
            print("“全部”不能和其他编号同时选择。")
            continue
        if "5" in parts and len(parts) > 1:
            print("“退出”不能和其他编号同时选择。")
            continue
        if parts == ["4"]:
            return list(PLATFORMS)
        if parts == ["5"]:
            return []
        mapping = {"1": "tower", "2": "eolink", "3": "lanhu"}
        return [mapping[part] for part in parts]


def prompt_lanhu_action() -> str:
    while True:
        answer = input(
            "1. 启用或更新蓝湖\n"
            "2. 停用蓝湖\n"
            "3. 返回\n"
            "> "
        ).strip()
        if answer in {"1", "2", "3"}:
            return answer
        print("请输入 1、2 或 3。")


def collect_interactive(
    existing: dict[str, str],
    platforms: list[str],
    *,
    tower_cookie_only: bool = False,
) -> tuple[dict[str, str], list[str]]:
    values = dict(existing)
    skipped: list[str] = []
    if "tower" in platforms:
        print("\n配置 Tower")
        print("用于读取任务、下载附件和按明确授权发布评论。")
        previous = {
            key: values[key]
            for key in ("TOWER_EMAIL", "TOWER_PASSWORD", "TOWER_COOKIE")
        }
        try:
            if tower_cookie_only:
                values["TOWER_COOKIE"] = prompt_value(
                    "TOWER_COOKIE",
                    "Tower Cookie",
                    values["TOWER_COOKIE"],
                    secret=True,
                )
            else:
                values["TOWER_EMAIL"] = prompt_value(
                    "TOWER_EMAIL",
                    "Tower 登录邮箱",
                    values["TOWER_EMAIL"],
                )
                values["TOWER_PASSWORD"] = prompt_password(
                    "Tower 登录密码",
                    values["TOWER_PASSWORD"],
                )
        except SkipPlatform:
            values.update(previous)
            skipped.append("tower")

    if "eolink" in platforms:
        print("\n配置 Eolink")
        print("用于读取项目、接口列表和接口详情。")
        previous = {
            key: values[key]
            for key in ("EOLINK_BASE_URL", "EOLINK_USER", "EOLINK_PASSWORD")
        }
        try:
            values["EOLINK_BASE_URL"] = prompt_value(
                "EOLINK_BASE_URL",
                "Eolink 根地址",
                values["EOLINK_BASE_URL"],
            ).rstrip("/")
            values["EOLINK_USER"] = prompt_value(
                "EOLINK_USER", "Eolink 账号", values["EOLINK_USER"]
            )
            values["EOLINK_PASSWORD"] = prompt_password(
                "Eolink 密码",
                values["EOLINK_PASSWORD"],
            )
        except SkipPlatform:
            values.update(previous)
            skipped.append("eolink")

    if "lanhu" in platforms:
        print("\n配置蓝湖")
        action = prompt_lanhu_action()
        if action == "3":
            skipped.append("lanhu")
        elif action == "2":
            values["LANHU_ENABLED"] = "false"
        else:
            previous = {
                key: values[key] for key in ("LANHU_ENABLED", "LANHU_COOKIE")
            }
            try:
                values["LANHU_ENABLED"] = "true"
                values["LANHU_COOKIE"] = prompt_value(
                    "LANHU_COOKIE",
                    "蓝湖 Cookie",
                    values["LANHU_COOKIE"],
                    secret=True,
                )
                print(
                    "蓝湖项目权限将在首次读取真实设计稿时验证，"
                    "无需在安装时提供链接。"
                )
            except SkipPlatform:
                values.update(previous)
                skipped.append("lanhu")
    return values, skipped


def authenticate_tower(values: dict[str, str]) -> tuple[str, str]:
    try:
        values["TOWER_COOKIE"] = login_tower(
            values["TOWER_EMAIL"],
            values["TOWER_PASSWORD"],
        )
        return (
            "success",
            "Tower 登录验证成功；已保存邮箱、密码和登录 Cookie",
        )
    except TowerLoginError as error:
        if error.kind == "credentials":
            return (
                "failed",
                "Tower 登录失败：邮箱或密码错误；本次配置未保存",
            )
        if error.kind == "verification":
            return (
                "failed",
                "Tower 要求验证码或二次验证；请使用 "
                "specweaver configure tower --cookie",
            )
        if error.kind == "network":
            return (
                "failed",
                "Tower 登录暂时无法验证；本次配置未保存",
            )
        return (
            "failed",
            "Tower 网页登录流程暂时不可用；请使用 "
            "specweaver configure tower --cookie",
        )


def validate_tower(
    cookie: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> tuple[str, str]:
    try:
        with httpx.Client(
            cookies=cookies_from_header(cookie),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
            follow_redirects=True,
            transport=transport,
        ) as client:
            response = client.get("https://tower.im/launchpad/")
        response.raise_for_status()
        if is_login_response(response):
            return "failed", "Tower Cookie 已失效"
        return "success", "Tower 认证有效"
    except ValueError as error:
        return "failed", str(error)
    except httpx.HTTPError as error:
        return "failed", f"Tower 连接失败: {error.__class__.__name__}"


def validate_eolink(base_url: str, user: str, password: str) -> tuple[str, str]:
    try:
        with httpx.Client(base_url=base_url, timeout=20, follow_redirects=True) as client:
            client.get("/")
            response = client.post(
                "/server/index.php?g=Web&c=Guest&o=login",
                data={
                    "loginName": user,
                    "loginPassword": hashlib.md5(password.encode()).hexdigest(),
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "Origin": base_url,
                    "Referer": f"{base_url}/",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            response.raise_for_status()
            if response.json().get("statusCode") != "000000":
                return "failed", "Eolink 账号、密码或服务地址无效"
        return "success", "Eolink 认证有效"
    except (httpx.HTTPError, ValueError) as error:
        return "failed", f"Eolink 连接或响应失败: {error.__class__.__name__}"


def parse_lanhu_check_url(url: str) -> tuple[str, str | None]:
    parsed = urlparse(url)
    fragment_path, separator, query_text = parsed.fragment.partition("?")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "lanhuapp.com"
        or not separator
        or "/item/project/stage" not in fragment_path
    ):
        raise ValueError("不是蓝湖 stage 标准项目链接")
    query = parse_qs(query_text)
    project_id = (query.get("pid") or [""])[0]
    team_id = (query.get("tid") or [""])[0] or None
    if not project_id:
        raise ValueError("蓝湖链接缺少 pid")
    return project_id, team_id


def validate_lanhu(cookie: str, project_url: str = "") -> tuple[str, str]:
    if not cookie.strip():
        return "failed", "未配置蓝湖 Cookie"
    if not project_url:
        return "configured", "蓝湖 Cookie 已配置；项目权限将在首次使用时验证"
    try:
        project_id, team_id = parse_lanhu_check_url(project_url)
        params = {
            "project_id": project_id,
            "dds_status": "1",
            "position": "1",
            "show_cb_src": "1",
            "comment": "1",
        }
        if team_id:
            params["team_id"] = team_id
        response = httpx.get(
            "https://lanhuapp.com/api/project/images",
            params=params,
            headers={
                "Cookie": cookie,
                "Referer": "https://lanhuapp.com/web/",
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json, text/plain, */*",
                "request-from": "web",
            },
            timeout=20,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("code")) != "00000":
            return "failed", f"蓝湖认证或项目权限验证失败: {payload.get('msg') or '未知错误'}"
        return "success", "蓝湖认证和项目权限有效"
    except (httpx.HTTPError, ValueError) as error:
        return "failed", f"蓝湖连接、链接或响应失败: {error}"


def validate_platforms(
    values: dict[str, str],
    platforms: list[str],
    lanhu_check_url: str = "",
    deferred_platforms: frozenset[str] = frozenset(),
) -> dict[str, tuple[str, str]]:
    results: dict[str, tuple[str, str]] = {}
    if "tower" in platforms:
        if values["TOWER_COOKIE"].strip():
            if "tower" in deferred_platforms:
                results["Tower"] = (
                    "configured",
                    "Tower Cookie 已保存；将在首次使用时验证",
                )
            else:
                results["Tower"] = validate_tower(values["TOWER_COOKIE"])
        else:
            results["Tower"] = ("failed", "未配置 Tower Cookie")
    if "eolink" in platforms:
        if platform_is_complete("eolink", values):
            if "eolink" in deferred_platforms:
                results["Eolink"] = (
                    "configured",
                    "Eolink 认证信息已保存；将在首次使用时验证",
                )
            else:
                results["Eolink"] = validate_eolink(
                    values["EOLINK_BASE_URL"],
                    values["EOLINK_USER"],
                    values["EOLINK_PASSWORD"],
                )
        else:
            results["Eolink"] = ("failed", "Eolink 配置不完整")
    if "lanhu" in platforms:
        try:
            enabled = parse_enabled(values["LANHU_ENABLED"])
        except ValueError as error:
            results["蓝湖"] = ("failed", str(error))
        else:
            if enabled:
                if "lanhu" in deferred_platforms:
                    results["蓝湖"] = (
                        "configured",
                        "蓝湖 Cookie 已保存；将在首次使用时验证",
                    )
                else:
                    results["蓝湖"] = validate_lanhu(
                        values["LANHU_COOKIE"], lanhu_check_url
                    )
            else:
                results["蓝湖"] = ("disabled", "蓝湖能力未启用")
    return results


def print_summary(path: Path, results: dict[str, tuple[str, str]]) -> None:
    print("\nSpecWeaver 配置结果")
    path_status = "权限 600" if path.is_file() else "尚未创建"
    print(f"- 配置文件: {path}（{path_status}）")
    print("- 源码准备: 由插件平台安装和缓存，无需本地仓库")
    for platform, (status, message) in results.items():
        print(f"- {platform}: {status} · {message}")


def print_existing_status(path: Path, values: dict[str, str]) -> None:
    print(f"已保留现有认证配置：{path}")
    tower_status = "已配置" if values["TOWER_COOKIE"] else "未配置"
    eolink_status = (
        "已配置"
        if all(values[key] for key in ("EOLINK_BASE_URL", "EOLINK_USER", "EOLINK_PASSWORD"))
        else "未完整配置"
    )
    try:
        lanhu_enabled = parse_enabled(values["LANHU_ENABLED"] or "true")
        lanhu_status = (
            "已配置" if values["LANHU_COOKIE"] else "未配置"
        ) if lanhu_enabled else "能力已关闭"
    except ValueError:
        lanhu_status = "配置错误（LANHU_ENABLED 只接受 true 或 false）"
    print(f"- Tower: {tower_status}")
    print(f"- Eolink: {eolink_status}")
    print(f"- 蓝湖: {lanhu_status}")
    print("未执行联网验证；可运行 specweaver check 检查连接。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="specweaver",
        description="配置并验证 SpecWeaver 认证信息",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("configure", "check"),
        help="配置认证或检查连接",
    )
    parser.add_argument(
        "platform",
        nargs="?",
        choices=PLATFORMS,
        help="只处理 tower、eolink 或 lanhu",
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        dest="legacy_configure",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="只读取现有配置和环境变量",
    )
    parser.add_argument(
        "--lanhu-url",
        default="",
        help="check lanhu 时可选：检查指定项目权限，不会保存链接",
    )
    parser.add_argument(
        "--cookie",
        action="store_true",
        help="Tower 人工 Cookie 恢复入口，仅用于 configure tower",
    )
    return parser.parse_args()


def build_configure_results(
    values: dict[str, str],
    existing: dict[str, str],
    platforms: list[str],
    skipped: list[str],
    *,
    tower_cookie_only: bool,
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    results: dict[str, tuple[str, str]] = {}
    saved: list[str] = []
    for platform in platforms:
        label = PLATFORM_LABELS[platform]
        if platform in skipped:
            results[label] = ("skipped", "已返回，原配置保持不变")
            continue
        if platform == "tower" and not tower_cookie_only:
            result = authenticate_tower(values)
            results["Tower"] = result
            if result[0] == "failed":
                for key in ("TOWER_EMAIL", "TOWER_PASSWORD", "TOWER_COOKIE"):
                    values[key] = existing[key]
                continue
            saved.append(platform)
            continue
        if platform == "tower":
            if values["TOWER_COOKIE"].strip():
                results["Tower"] = (
                    "configured",
                    "Tower Cookie 已保存；将在首次使用时验证",
                )
                saved.append(platform)
            else:
                results["Tower"] = ("failed", "未配置 Tower Cookie")
            continue
        results.update(
            validate_platforms(
                values,
                [platform],
                deferred_platforms=CONFIGURE_DEFERRED_PLATFORMS,
            )
        )
        if results[label][0] != "failed":
            saved.append(platform)
    return results, saved


def main() -> int:
    args = parse_args()
    path = config_file()
    existing = load_existing(path)
    command = args.command
    if args.legacy_configure or args.non_interactive:
        command = command or "configure"

    if args.cookie and not (command == "configure" and args.platform == "tower"):
        print("错误: --cookie 仅支持 specweaver configure tower --cookie")
        return 2

    if path.is_file() and command is None:
        print_existing_status(path, existing)
        return 0

    if command == "check":
        platforms = [args.platform] if args.platform else list(PLATFORMS)
        results = validate_platforms(existing, platforms, args.lanhu_url)
        print_summary(path, results)
        failed = [name for name, (status, _) in results.items() if status == "failed"]
        if failed:
            print(f"连接检查未全部通过: {', '.join(failed)}")
            return 1
        return 0

    if args.non_interactive:
        platforms = [args.platform] if args.platform else list(PLATFORMS)
        try:
            values = merged_non_interactive(
                existing,
                platforms,
                tower_cookie_only=args.cookie,
            )
        except ValueError as error:
            print(f"错误: {error}")
            return 2
        results, saved = build_configure_results(
            values,
            existing,
            platforms,
            [],
            tower_cookie_only=args.cookie,
        )
        if saved:
            write_config_atomic(path, values)
        print_summary(path, results)
        failed = [name for name, (status, _) in results.items() if status == "failed"]
        if failed:
            print(f"认证验证未全部通过: {', '.join(failed)}")
            return 1
        return 0

    platforms = [args.platform] if args.platform else select_platforms()
    if not platforms:
        print("已退出，未修改任何配置。")
        return 0

    values, skipped = collect_interactive(
        existing,
        platforms,
        tower_cookie_only=args.cookie,
    )
    results, saved = build_configure_results(
        values,
        existing,
        platforms,
        skipped,
        tower_cookie_only=args.cookie,
    )
    if saved:
        write_config_atomic(path, values)
    print_summary(path, results)
    failed = [name for name, (status, _) in results.items() if status == "failed"]
    if failed:
        print(f"认证验证未全部通过: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
