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
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()
