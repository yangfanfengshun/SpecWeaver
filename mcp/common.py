from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


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
        for key in {
            "TOWER_COOKIE",
            "EOLINK_BASE_URL",
            "EOLINK_USER",
            "EOLINK_PASSWORD",
            "LANHU_ENABLED",
            "LANHU_COOKIE",
        }
    }


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
