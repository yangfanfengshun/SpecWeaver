#!/usr/bin/env python3
"""Query a normalized SpecWeaver Lanhu design without loading the whole file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def load_design(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"设计文件不存在: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"设计文件不是有效 JSON: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("layers"), list):
        raise ValueError("设计文件缺少 layers 数组")
    return data


def flatten_layers(
    layers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    def visit(node: dict[str, Any], names: list[str], depth: int) -> None:
        node_id = str(node.get("id", ""))
        name = str(node.get("name", ""))
        row = {
            "node": node,
            "id": node_id,
            "name": name,
            "path": " / ".join([*names, name]),
            "depth": depth,
        }
        rows.append(row)
        if node_id:
            by_id[node_id] = row
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child, [*names, name], depth + 1)

    for layer in layers:
        if isinstance(layer, dict):
            visit(layer, [], 0)
    return rows, by_id


def compact(row: dict[str, Any]) -> dict[str, Any]:
    node = row["node"]
    result = {
        "id": row["id"],
        "name": row["name"],
        "type": node.get("type"),
        "path": row["path"],
        "depth": row["depth"],
        "frame": node.get("frame"),
    }
    for key in ("state", "style", "stacking", "text", "asset", "layout"):
        value = node.get(key)
        if value:
            result[key] = value
    return result


def brief(row: dict[str, Any]) -> dict[str, Any]:
    node = row["node"]
    return {
        "id": row["id"],
        "name": row["name"],
        "type": node.get("type"),
        "path": row["path"],
        "frame": node.get("frame"),
    }


def frame_values(row: dict[str, Any]) -> tuple[float, float, float, float] | None:
    frame = row["node"].get("frame")
    if not isinstance(frame, dict):
        return None
    try:
        return tuple(float(frame[key]) for key in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError):
        return None


def is_visible(row: dict[str, Any]) -> bool:
    state = row["node"].get("state")
    return not isinstance(state, dict) or state.get("visible") is not False


def point_hits(
    rows: list[dict[str, Any]], x: float, y: float
) -> list[dict[str, Any]]:
    hits = []
    for row in rows:
        if not is_visible(row):
            continue
        values = frame_values(row)
        if values is None:
            continue
        left, top, width, height = values
        if left <= x <= left + width and top <= y <= top + height:
            hits.append(row)
    return sorted(
        hits,
        key=lambda item: (
            -item["depth"],
            (frame_values(item) or (0, 0, 0, 0))[2]
            * (frame_values(item) or (0, 0, 0, 0))[3],
        ),
    )


def region_hits(
    rows: list[dict[str, Any]], x: float, y: float, width: float, height: float
) -> list[dict[str, Any]]:
    right = x + width
    bottom = y + height
    hits = []
    for row in rows:
        if not is_visible(row):
            continue
        values = frame_values(row)
        if values is None:
            continue
        left, top, node_width, node_height = values
        node_right = left + node_width
        node_bottom = top + node_height
        if left < right and node_right > x and top < bottom and node_bottom > y:
            hits.append(row)
    return sorted(hits, key=lambda item: (item["depth"], item["path"]))


def node_result(
    row: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    node = row["node"]
    ancestors = []
    parent_id = node.get("parent_id")
    while parent_id and str(parent_id) in by_id:
        parent = by_id[str(parent_id)]
        ancestors.append(compact(parent))
        parent_id = parent["node"].get("parent_id")
    children = []
    for child in node.get("children") or []:
        child_id = str(child.get("id", ""))
        child_row = by_id.get(child_id)
        if child_row:
            children.append(compact(child_row))
    current = dict(node)
    current.pop("children", None)
    return {
        "node": current,
        "path": row["path"],
        "ancestors": list(reversed(ancestors)),
        "children": children,
    }


def measure(
    first: dict[str, Any], second: dict[str, Any]
) -> dict[str, Any]:
    first_frame = frame_values(first)
    second_frame = frame_values(second)
    if first_frame is None or second_frame is None:
        raise ValueError("待测节点缺少有效 frame")
    ax, ay, aw, ah = first_frame
    bx, by, bw, bh = second_frame
    horizontal_gap = max(bx - (ax + aw), ax - (bx + bw), 0)
    vertical_gap = max(by - (ay + ah), ay - (by + bh), 0)
    return {
        "from": compact(first),
        "to": compact(second),
        "horizontal_gap": horizontal_gap,
        "vertical_gap": vertical_gap,
        "center_delta": {
            "x": (bx + bw / 2) - (ax + aw / 2),
            "y": (by + bh / 2) - (ay + ah / 2),
        },
        "overlaps": horizontal_gap == 0 and vertical_gap == 0,
        "source": "derived",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design_file", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("summary")

    search = commands.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=20)

    node = commands.add_parser("node")
    node.add_argument("--id", required=True)

    point = commands.add_parser("point")
    point.add_argument("--x", type=float, required=True)
    point.add_argument("--y", type=float, required=True)
    point.add_argument("--limit", type=int, default=20)

    region = commands.add_parser("region")
    region.add_argument("--x", type=float, required=True)
    region.add_argument("--y", type=float, required=True)
    region.add_argument("--width", type=float, required=True)
    region.add_argument("--height", type=float, required=True)
    region.add_argument("--limit", type=int, default=50)

    distance = commands.add_parser("measure")
    distance.add_argument("--from-id", required=True)
    distance.add_argument("--to-id", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        data = load_design(args.design_file)
        rows, by_id = flatten_layers(data["layers"])
        if args.command == "summary":
            result = {
                "source": data.get("source"),
                "canvas": data.get("canvas"),
                "summary": data.get("summary"),
                "top_layers": [brief(row) for row in rows if row["depth"] == 0],
            }
        elif args.command == "search":
            query = args.query.casefold()
            matches = [
                row
                for row in rows
                if query in row["name"].casefold()
                or query in json.dumps(
                    row["node"].get("text", ""), ensure_ascii=False
                ).casefold()
            ]
            result = {
                "query": args.query,
                "total": len(matches),
                "matches": [compact(row) for row in matches[: args.limit]],
            }
        elif args.command == "node":
            row = by_id.get(args.id)
            if row is None:
                raise ValueError(f"未找到节点: {args.id}")
            result = node_result(row, by_id)
        elif args.command == "point":
            matches = point_hits(rows, args.x, args.y)
            result = {
                "point": {"x": args.x, "y": args.y},
                "total": len(matches),
                "matches": [compact(row) for row in matches[: args.limit]],
            }
        elif args.command == "region":
            matches = region_hits(
                rows, args.x, args.y, args.width, args.height
            )
            result = {
                "region": {
                    "x": args.x,
                    "y": args.y,
                    "width": args.width,
                    "height": args.height,
                },
                "total": len(matches),
                "matches": [compact(row) for row in matches[: args.limit]],
            }
        else:
            first = by_id.get(args.from_id)
            second = by_id.get(args.to_id)
            if first is None:
                raise ValueError(f"未找到节点: {args.from_id}")
            if second is None:
                raise ValueError(f"未找到节点: {args.to_id}")
            result = measure(first, second)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
