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
import hashlib
import os
from pathlib import Path
import readline
import tempfile
from urllib.parse import parse_qs, urlparse

from dotenv import dotenv_values
import httpx


CONFIG_KEYS = (
    "TOWER_COOKIE",
    "EOLINK_BASE_URL",
    "EOLINK_USER",
    "EOLINK_PASSWORD",
    "LANHU_ENABLED",
    "LANHU_COOKIE",
)
SECRET_KEYS = {"TOWER_COOKIE", "EOLINK_PASSWORD", "LANHU_COOKIE"}
PLATFORMS = ("tower", "eolink", "lanhu")
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


def missing_platforms(values: dict[str, str]) -> list[str]:
    return [
        platform
        for platform in PLATFORMS
        if not platform_is_complete(platform, values)
    ]


def required_keys(platforms: list[str], values: dict[str, str]) -> list[str]:
    required: list[str] = []
    if "tower" in platforms:
        required.append("TOWER_COOKIE")
    if "eolink" in platforms:
        required.extend(("EOLINK_BASE_URL", "EOLINK_USER", "EOLINK_PASSWORD"))
    if "lanhu" in platforms:
        required.append("LANHU_ENABLED")
        if values["LANHU_ENABLED"] and parse_enabled(values["LANHU_ENABLED"]):
            required.append("LANHU_COOKIE")
    return required


def merged_non_interactive(
    existing: dict[str, str], platforms: list[str] | None = None
) -> dict[str, str]:
    values = dict(existing)
    for key in CONFIG_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    if not values["LANHU_ENABLED"]:
        values["LANHU_ENABLED"] = "true"
    targets = platforms or list(PLATFORMS)
    missing = [
        key for key in required_keys(targets, values) if not values[key].strip()
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


def prompt_configure(label: str) -> bool:
    answer = input(f"是否现在配置{label}？[Y/s]: ").strip().lower()
    if not answer or answer in {"y", "yes"}:
        return True
    if answer in {"s", "skip", "n", "no"}:
        return False
    print("请输入 y 或 s。")
    return prompt_configure(label)


def prompt_enabled(current: str) -> str:
    default = parse_enabled(current or "true")
    suffix = "Y/n" if default else "y/N"
    answer = input(
        "是否启用蓝湖设计稿能力？前端、客户端和产品通常需要，后端可关闭 "
        f"[{suffix}]: "
    ).strip().lower()
    if not answer:
        return "true" if default else "false"
    if answer in {"y", "yes"}:
        return "true"
    if answer in {"n", "no"}:
        return "false"
    print("请输入 y 或 n。")
    return prompt_enabled(current)


def collect_interactive(
    existing: dict[str, str],
    platforms: list[str],
    *,
    only_missing: bool,
) -> tuple[dict[str, str], list[str]]:
    values = dict(existing)
    skipped: list[str] = []
    if "tower" in platforms:
        print("\n配置 Tower")
        print("用于读取任务、下载附件和按明确授权发布评论。")
        if not prompt_configure(" Tower"):
            skipped.append("tower")
        else:
            previous = values["TOWER_COOKIE"]
            try:
                if not only_missing or not values["TOWER_COOKIE"]:
                    values["TOWER_COOKIE"] = prompt_value(
                        "TOWER_COOKIE",
                        "Tower Cookie",
                        values["TOWER_COOKIE"],
                        secret=True,
                    )
            except SkipPlatform:
                values["TOWER_COOKIE"] = previous
                skipped.append("tower")

    if "eolink" in platforms:
        print("\n配置 Eolink")
        print("用于读取项目、接口列表和接口详情。")
        if not prompt_configure(" Eolink"):
            skipped.append("eolink")
        else:
            previous = {
                key: values[key]
                for key in ("EOLINK_BASE_URL", "EOLINK_USER", "EOLINK_PASSWORD")
            }
            try:
                if not only_missing or not values["EOLINK_BASE_URL"]:
                    values["EOLINK_BASE_URL"] = prompt_value(
                        "EOLINK_BASE_URL",
                        "Eolink 根地址",
                        values["EOLINK_BASE_URL"],
                    ).rstrip("/")
                if not only_missing or not values["EOLINK_USER"]:
                    values["EOLINK_USER"] = prompt_value(
                        "EOLINK_USER", "Eolink 账号", values["EOLINK_USER"]
                    )
                if not only_missing or not values["EOLINK_PASSWORD"]:
                    values["EOLINK_PASSWORD"] = prompt_value(
                        "EOLINK_PASSWORD",
                        "Eolink 密码",
                        values["EOLINK_PASSWORD"],
                        secret=True,
                    )
            except SkipPlatform:
                values.update(previous)
                skipped.append("eolink")

    if "lanhu" in platforms:
        print("\n配置蓝湖")
        if not prompt_configure("蓝湖"):
            skipped.append("lanhu")
        else:
            previous = {
                key: values[key] for key in ("LANHU_ENABLED", "LANHU_COOKIE")
            }
            try:
                should_prompt_enabled = (
                    not only_missing
                    or not values["LANHU_ENABLED"]
                    or values["LANHU_ENABLED"].strip().lower() not in {"true", "false"}
                )
                if should_prompt_enabled:
                    current_enabled = values["LANHU_ENABLED"].strip().lower()
                    if current_enabled not in {"true", "false"}:
                        current_enabled = "true"
                    values["LANHU_ENABLED"] = prompt_enabled(current_enabled)
                if parse_enabled(values["LANHU_ENABLED"]):
                    if not only_missing or not values["LANHU_COOKIE"]:
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


def validate_tower(cookie: str) -> tuple[str, str]:
    try:
        response = httpx.get(
            "https://tower.im/launchpad/",
            headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"},
            timeout=20,
            follow_redirects=True,
        )
        response.raise_for_status()
        sample = response.text[:5000].lower()
        if (
            "/login" in response.url.path.lower()
            or "登录" in response.text[:5000]
            or "login" in sample
        ):
            return "failed", "Tower Cookie 已失效"
        return "success", "Tower 认证有效"
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
) -> dict[str, tuple[str, str]]:
    results: dict[str, tuple[str, str]] = {}
    if "tower" in platforms:
        if values["TOWER_COOKIE"].strip():
            results["Tower"] = validate_tower(values["TOWER_COOKIE"])
        else:
            results["Tower"] = ("failed", "未配置 Tower Cookie")
    if "eolink" in platforms:
        if platform_is_complete("eolink", values):
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


def validate_with_skips(
    values: dict[str, str],
    platforms: list[str],
    skipped: list[str],
    lanhu_check_url: str = "",
) -> dict[str, tuple[str, str]]:
    results: dict[str, tuple[str, str]] = {}
    for platform in platforms:
        label = PLATFORM_LABELS[platform]
        if platform in skipped:
            results[label] = ("skipped", "已跳过，可稍后配置")
        else:
            results.update(validate_platforms(values, [platform], lanhu_check_url))
    return results


def print_deferred(platforms: list[str]) -> None:
    if len(platforms) == len(PLATFORMS):
        print("已跳过认证配置；稍后运行：specweaver configure")
        return
    commands = "、".join(f"specweaver configure {platform}" for platform in platforms)
    print(f"已跳过配置；稍后运行：{commands}")


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
        help="可选：检查蓝湖 Cookie 和指定项目权限，不会保存链接",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = config_file()
    existing = load_existing(path)
    command = args.command
    if args.legacy_configure or args.non_interactive:
        command = command or "configure"

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
            values = merged_non_interactive(existing, platforms)
        except ValueError as error:
            print(f"错误: {error}")
            return 2
        lanhu_check_url = args.lanhu_url or os.getenv("LANHU_CHECK_URL", "")
        results = validate_platforms(values, platforms, lanhu_check_url)
        write_config_atomic(path, values)
        print_summary(path, results)
        failed = [name for name, (status, _) in results.items() if status == "failed"]
        if failed:
            print(f"认证验证未全部通过: {', '.join(failed)}")
            return 1
        return 0

    values = existing
    platforms = [args.platform] if args.platform else missing_platforms(values)
    if not platforms:
        print_existing_status(path, values)
        print(
            "没有缺失配置；如需更新单个平台，请运行 "
            "specweaver configure tower、eolink 或 lanhu。"
        )
        return 0

    only_missing = args.platform is None
    if args.platform is None and not prompt_configure("认证信息"):
        print_deferred(platforms)
        return 0

    while True:
        values, skipped = collect_interactive(
            values,
            platforms,
            only_missing=only_missing,
        )
        active_platforms = [
            platform for platform in platforms if platform not in skipped
        ]
        results = validate_with_skips(
            values,
            platforms,
            skipped,
            args.lanhu_url,
        )
        if active_platforms:
            write_config_atomic(path, values)
        print_summary(path, results)
        failed = [name for name, (status, _) in results.items() if status == "failed"]
        if not failed:
            if skipped:
                print_deferred(skipped)
            return 0
        print(f"认证验证未全部通过: {', '.join(failed)}")
        answer = input("是否立即重新填写并验证？[Y/n]: ").strip().lower()
        if answer not in {"n", "no"}:
            platforms = [
                platform
                for platform in platforms
                if PLATFORM_LABELS[platform] in failed
            ]
            only_missing = False
            continue
        suffix = f" {args.platform}" if args.platform else ""
        print(f"已保留当前配置，可稍后运行 specweaver configure{suffix}。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
