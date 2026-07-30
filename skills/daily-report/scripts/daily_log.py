#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
import fcntl
import os
from pathlib import Path
import re
import sys
import tempfile


PROJECT_HEADING = re.compile(r"^## 项目：(.+)$")


def default_log_directory() -> Path:
    root = Path(os.environ.get("SPECWEAVER_HOME", Path.home() / ".specweaver"))
    return root.expanduser() / "daily-logs"


def normalize(value: str, label: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{label}不能为空")
    return normalized


def checked_date(value: str | None) -> str:
    if value is None:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValueError("日期必须使用 YYYY-MM-DD 格式") from error


def daily_path(directory: Path, target_date: str) -> Path:
    return directory.expanduser() / f"{target_date}.md"


def find_project(lines: list[str], project: str) -> tuple[int, int] | None:
    for index, line in enumerate(lines):
        match = PROJECT_HEADING.match(line)
        if match and match.group(1) == project:
            end = len(lines)
            for candidate in range(index + 1, len(lines)):
                if PROJECT_HEADING.match(lines[candidate]):
                    end = candidate
                    break
            return index, end
    return None


def project_lines(project: str, completed: list[str]) -> list[str]:
    return [f"## 项目：{project}", "", *[f"- 完成：{item}" for item in completed]]


def merge_daily_log(
    content: str, target_date: str, project: str, completed: list[str]
) -> tuple[str, int]:
    lines = content.splitlines() or [f"# {target_date} 日报记录"]
    project_section = find_project(lines, project)
    if project_section is None:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(project_lines(project, completed))
        return "\n".join(lines).rstrip() + "\n", len(completed)

    start, end = project_section
    existing = {
        line.removeprefix("- 完成：")
        for line in lines[start + 1 : end]
        if line.startswith("- 完成：")
    }
    additions = [item for item in completed if item not in existing]
    if additions:
        while end > start + 1 and lines[end - 1] == "":
            end -= 1
        lines[end:end] = [f"- 完成：{item}" for item in additions]
    return "\n".join(lines).rstrip() + "\n", len(additions)


def write_atomic(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def add_entry(path: Path, target_date: str, project: str, completed: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        merged, added = merge_daily_log(current, target_date, project, completed)
        if added or not path.exists():
            write_atomic(path, merged)
    print(f"日报已更新：{path.resolve()}（新增 {added} 项）")
    return 0


def show_daily_log(path: Path, target_date: str) -> int:
    if not path.is_file():
        print(f"当天没有日报记录：{target_date}（文件：{path.resolve()}）", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8").rstrip())
    print(f"\n文件：{path.resolve()}")
    return 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="记录或读取 SpecWeaver 跨项目日报")
    parser.add_argument("--directory", type=Path, default=default_log_directory())
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="追加本次任务的完成事项")
    add.add_argument("--date")
    add.add_argument("--project", required=True)
    add.add_argument("--completed", action="append", required=True)

    show = subparsers.add_parser("show", help="读取指定日期的全部项目记录")
    show.add_argument("--date")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        target_date = checked_date(arguments.date)
        path = daily_path(arguments.directory, target_date)
        if arguments.command == "add":
            project = normalize(arguments.project, "项目名称")
            completed = list(
                dict.fromkeys(normalize(item, "完成事项") for item in arguments.completed)
            )
            return add_entry(path, target_date, project, completed)
        return show_daily_log(path, target_date)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
