from __future__ import annotations

import os
from pathlib import Path
import tempfile

from dotenv import dotenv_values


CONFIG_KEYS = (
    "TOWER_EMAIL",
    "TOWER_PASSWORD",
    "TOWER_COOKIE",
    "EOLINK_BASE_URL",
    "EOLINK_USER",
    "EOLINK_PASSWORD",
    "LANHU_ENABLED",
    "LANHU_PHONE",
    "LANHU_PASSWORD",
    "LANHU_COOKIE",
)
SPECWEAVER_HOME = Path(
    os.getenv("SPECWEAVER_HOME", Path.home() / ".specweaver")
).expanduser()
CONFIG_FILE = SPECWEAVER_HOME / ".env"

IMAGE_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


class UnsafePathError(ValueError):
    pass


def _allowed_system_symlink(path: Path) -> bool:
    expected = {
        Path("/var"): Path("/private/var"),
        Path("/tmp"): Path("/private/tmp"),
        Path("/etc"): Path("/private/etc"),
    }.get(path)
    return expected is not None and path.resolve() == expected


def unsafe_symlink_components(path: Path) -> list[Path]:
    absolute = path.expanduser().absolute()
    components = [absolute, *absolute.parents]
    return [
        component
        for component in components
        if component.is_symlink() and not _allowed_system_symlink(component)
    ]


def ensure_no_symlink_components(path: Path) -> None:
    unsafe = unsafe_symlink_components(path)
    if unsafe:
        raise UnsafePathError(
            f"路径中不允许符号链接: {', '.join(map(str, unsafe))}"
        )


def read_config() -> dict[str, str]:
    file_values = dotenv_values(CONFIG_FILE) if CONFIG_FILE.is_file() else {}
    return {
        key: str(os.environ.get(key, file_values.get(key) or ""))
        for key in CONFIG_KEYS
    }


def quote_env(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def update_config_atomic(updates: dict[str, str]) -> None:
    values = dotenv_values(CONFIG_FILE) if CONFIG_FILE.is_file() else {}
    merged = {
        key: str(updates.get(key, values.get(key) or ""))
        for key in CONFIG_KEYS
    }
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".env.",
        dir=CONFIG_FILE.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for key in CONFIG_KEYS:
                handle.write(f"{key}={quote_env(merged[key])}\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(0o600)
        os.replace(temp_path, CONFIG_FILE)
        CONFIG_FILE.chmod(0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def manual_cookie_hint(platform: str, key: str) -> str:
    return (
        f"配置文件：{CONFIG_FILE}；请手动填写 {key}，"
        f"或运行 specweaver configure {platform} --cookie"
    )


def parse_strict_bool(value: str, *, default: bool | None = None) -> bool:
    normalized = value.strip().lower()
    if not normalized and default is not None:
        return default
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("只接受 true 或 false")


def prepare_output_dir(output_dir: str) -> Path:
    path = Path(output_dir).expanduser()
    if not path.is_absolute():
        raise ValueError("output_dir 必须是绝对路径")
    ensure_no_symlink_components(path)
    path.mkdir(parents=True, exist_ok=True)
    ensure_no_symlink_components(path)
    return path.resolve()


def atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> Path:
    ensure_no_symlink_components(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_no_symlink_components(path)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            if content and not content.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(mode)
        os.replace(temp_path, path)
        path.chmod(mode)
        return path.resolve()
    finally:
        if temp_path.exists():
            temp_path.unlink()
