from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common import atomic_write_text


INLINE_NODE_LIMIT = 120


def _number(value: Any, default: float | None = None) -> float | int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return default
        return int(parsed) if parsed.is_integer() else parsed
    return default


def _scaled(value: Any, scale: float) -> float | int | None:
    number = _number(value)
    if number is None:
        return None
    result = float(number) / scale
    return int(result) if result.is_integer() else round(result, 4)


def _color(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    red = _number(value.get("r", value.get("red")))
    green = _number(value.get("g", value.get("green")))
    blue = _number(value.get("b", value.get("blue")))
    if red is None or green is None or blue is None:
        return None
    alpha = _number(value.get("a", value.get("alpha")), 1)
    if alpha is None:
        alpha = 1
    if alpha > 1:
        alpha = float(alpha) / 255
    channels = [
        max(0, min(255, round(float(red)))),
        max(0, min(255, round(float(green)))),
        max(0, min(255, round(float(blue)))),
    ]
    if alpha >= 1:
        return "#" + "".join(f"{channel:02X}" for channel in channels)
    return f"rgba({channels[0]}, {channels[1]}, {channels[2]}, {round(float(alpha), 4)})"


def _frame(node: dict[str, Any], scale: float) -> dict[str, Any]:
    frame = node.get("frame") if isinstance(node.get("frame"), dict) else {}
    bounds = node.get("bounds") if isinstance(node.get("bounds"), dict) else {}
    left = frame.get("x", frame.get("left", node.get("left", bounds.get("left"))))
    top = frame.get("y", frame.get("top", node.get("top", bounds.get("top"))))
    width = frame.get("width", node.get("width"))
    height = frame.get("height", node.get("height"))
    if width is None and bounds.get("right") is not None and bounds.get("left") is not None:
        width = float(bounds["right"]) - float(bounds["left"])
    if height is None and bounds.get("bottom") is not None and bounds.get("top") is not None:
        height = float(bounds["bottom"]) - float(bounds["top"])
    return {
        "x": _scaled(left, scale) or 0,
        "y": _scaled(top, scale) or 0,
        "width": _scaled(width, scale) or 0,
        "height": _scaled(height, scale) or 0,
        "source": "fact",
    }


def _node_type(node: dict[str, Any]) -> str:
    raw_type = str(node.get("type") or node.get("layerType") or "").lower()
    if "text" in raw_type or isinstance(node.get("textInfo"), dict):
        return "text"
    if node.get("isAsset") or node.get("isSlice") or node.get("images"):
        frame = node.get("frame") or node
        width = float(_number(frame.get("width"), 0) or 0)
        height = float(_number(frame.get("height"), 0) or 0)
        return "icon" if max(width, height) <= 128 else "image"
    if "artboard" in raw_type or "group" in raw_type or "section" in raw_type:
        return "container"
    if node.get("layers") or node.get("children"):
        return "container"
    if any(word in raw_type for word in ("shape", "rect", "oval", "path")):
        return "shape"
    if node.get("fill") or node.get("fills") or node.get("path"):
        return "shape"
    return "container"


def _style(node: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"source": "fact"}
    fill = node.get("fill")
    if not isinstance(fill, dict):
        fills = node.get("fills")
        fill = fills[0] if isinstance(fills, list) and fills else {}
    background = _color(fill.get("color")) if isinstance(fill, dict) else None
    if background:
        result["background"] = background
    opacity = _number(node.get("opacity"))
    if opacity is not None:
        result["opacity"] = opacity
    radius = node.get("radius", node.get("cornerRadius"))
    if radius is not None:
        result["border_radius"] = radius
    borders = node.get("borders", node.get("strokes"))
    if isinstance(borders, list) and borders:
        border = borders[0] if isinstance(borders[0], dict) else {}
        result["border"] = {
            "width": _number(border.get("thickness", border.get("width")), 1),
            "color": _color(border.get("color")),
            "enabled": border.get("isEnabled", True),
        }
    effects = node.get("layerEffects")
    shadow = effects.get("dropShadow") if isinstance(effects, dict) else None
    if isinstance(shadow, dict) and shadow.get("enabled", True):
        shadow_opacity = shadow.get("opacity")
        if isinstance(shadow_opacity, dict):
            shadow_opacity = _number(shadow_opacity.get("value"))
        result["shadows"] = [{
            "color": _color(shadow.get("color")),
            "opacity": shadow_opacity,
            "offset_x": _number(shadow.get("offsetX"), 0),
            "offset_y": _number(shadow.get("distance"), 0),
            "blur": _number(shadow.get("blur"), 0),
        }]
    return result


def _text(node: dict[str, Any]) -> dict[str, Any] | None:
    info = node.get("textInfo")
    if not isinstance(info, dict):
        info = node.get("textStyle") if isinstance(node.get("textStyle"), dict) else {}
    content = info.get("text", node.get("textContent"))
    if content is None and isinstance(node.get("text"), str):
        content = node["text"]
    if content is None and not info:
        return None
    result: dict[str, Any] = {"content": str(content or ""), "source": "fact"}
    mappings = {
        "font_family": info.get("fontName", info.get("fontFamily")),
        "font_style": info.get("fontStyleName"),
        "font_size": _number(info.get("size", info.get("fontSize"))),
        "font_weight": info.get("fontWeight", 700 if info.get("bold") else None),
        "line_height": _number(info.get("leading", info.get("lineHeight"))),
        "letter_spacing": _number(info.get("tracking", info.get("letterSpacing"))),
        "align": info.get("justification", info.get("align")),
        "color": _color(info.get("color")),
    }
    result.update({key: value for key, value in mappings.items() if value is not None})
    return result


def _asset_urls(node: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    images = node.get("images")
    if isinstance(images, dict):
        urls.extend(str(value) for value in images.values() if isinstance(value, str))
    image = node.get("image")
    if isinstance(image, dict):
        urls.extend(
            str(image[key])
            for key in ("imageUrl", "svgUrl")
            if isinstance(image.get(key), str)
        )
    dds_image = node.get("ddsImage")
    if isinstance(dds_image, dict) and isinstance(dds_image.get("imageUrl"), str):
        urls.append(str(dds_image["imageUrl"]))
    return list(dict.fromkeys(urls))


def _slice_category(node: dict[str, Any], scale: float) -> str:
    node_type = _node_type(node)
    if node_type == "icon":
        return "icon"
    frame = node.get("frame") if isinstance(node.get("frame"), dict) else node
    width = float(_number(frame.get("width"), 0) or 0) / scale
    height = float(_number(frame.get("height"), 0) or 0) / scale
    if max(width, height) <= 128:
        return "icon"
    if width >= 600 or height >= 600:
        return "bg"
    return "img"


def _sketch_roots(sketch: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(sketch.get("layers"), list):
        return [node for node in sketch["layers"] if isinstance(node, dict)]
    artboard = sketch.get("artboard")
    if isinstance(artboard, dict) and isinstance(artboard.get("layers"), list):
        return [node for node in artboard["layers"] if isinstance(node, dict)]
    info = sketch.get("info")
    if not isinstance(info, list):
        return []
    nodes = [node for node in info if isinstance(node, dict)]
    artboards = [
        node for node in nodes
        if "artboard" in str(node.get("type") or "").lower()
    ]
    return artboards or nodes


def extract_slice_assets(sketch: dict[str, Any]) -> list[dict[str, Any]]:
    roots = _sketch_roots(sketch)
    scale = float(_number(
        sketch.get("sliceScale", sketch.get("ArtboardScale", sketch.get("exportScale"))),
        1,
    ) or 1)
    if scale <= 0:
        scale = 1
    assets: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    stack = list(reversed(roots))
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        layer_id = str(node.get("id") or "")
        for source_url in _asset_urls(node):
            key = (layer_id, source_url)
            if key in seen:
                continue
            seen.add(key)
            assets.append({
                "layer_id": layer_id,
                "layer_name": str(node.get("name") or ""),
                "source_url": source_url,
                "category": _slice_category(node, scale),
                "source": "fact",
                "status": "available",
            })
        children = node.get("layers", node.get("children", []))
        if isinstance(children, list):
            stack.extend(
                reversed([child for child in children if isinstance(child, dict)])
            )
    return assets


def _derived_layout(children: list[dict[str, Any]]) -> dict[str, Any] | None:
    positioned = [child for child in children if isinstance(child.get("frame"), dict)]
    if len(positioned) < 2:
        return None
    x_values = [float(child["frame"]["x"]) for child in positioned]
    y_values = [float(child["frame"]["y"]) for child in positioned]
    return {
        "direction": "row" if max(x_values) - min(x_values) > max(y_values) - min(y_values) else "column",
        "source": "derived",
    }


def _normalize_node(
    node: dict[str, Any],
    *,
    scale: float,
    parent_id: str | None,
    order: int,
    seen: set[str],
) -> dict[str, Any] | None:
    node_id = str(node.get("id") or f"{parent_id or 'root'}-{order}")
    if node_id in seen:
        return None
    seen.add(node_id)
    raw_children = node.get("layers", node.get("children", []))
    children: list[dict[str, Any]] = []
    if isinstance(raw_children, list):
        for child_order, child in enumerate(raw_children):
            if not isinstance(child, dict):
                continue
            normalized = _normalize_node(
                child,
                scale=scale,
                parent_id=node_id,
                order=child_order,
                seen=seen,
            )
            if normalized:
                children.append(normalized)
    result: dict[str, Any] = {
        "id": node_id,
        "name": str(node.get("name") or ""),
        "type": _node_type(node),
        "parent_id": parent_id,
        "order": order,
        "source": "fact",
        "frame": _frame(node, scale),
        "stacking": {
            "z_index": order,
            "clip": bool(node.get("clipped") or node.get("mask")),
            "source": "fact",
        },
        "state": {
            "visible": node.get("visible", True) is not False,
            "opacity": _number(node.get("opacity"), 1),
            "source": "fact",
        },
        "style": _style(node),
        "children": children,
    }
    text = _text(node)
    if text:
        result["text"] = text
    transform = {
        key: value
        for key, value in {
            "rotation": _number(node.get("rotation")),
            "scale_x": _number(node.get("scaleX")),
            "scale_y": _number(node.get("scaleY")),
        }.items()
        if value is not None
    }
    if transform:
        transform["source"] = "fact"
        result["transform"] = transform
    asset_urls = _asset_urls(node)
    if asset_urls:
        result["asset_refs"] = asset_urls
    layout = _derived_layout(children)
    if layout:
        result["layout"] = layout
    return result


def _summarize_layers(layers: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    hidden_count = 0
    max_depth = 0
    stack = [(node, 1) for node in reversed(layers)]
    while stack:
        node, depth = stack.pop()
        node_type = str(node.get("type") or "unknown")
        counts[node_type] = counts.get(node_type, 0) + 1
        if not (node.get("state") or {}).get("visible", True):
            hidden_count += 1
        max_depth = max(max_depth, depth)
        stack.extend(
            (child, depth + 1)
            for child in reversed(node.get("children") or [])
            if isinstance(child, dict)
        )
    return {
        "node_count": sum(counts.values()),
        "node_types": counts,
        "hidden_count": hidden_count,
        "max_depth": max_depth,
    }


def normalize_design_document(
    source_url: str,
    params: dict[str, str | None],
    detail: dict[str, Any],
    sketch: dict[str, Any],
) -> dict[str, Any]:
    scale = float(_number(
        sketch.get("sliceScale", sketch.get("ArtboardScale", sketch.get("exportScale"))),
        1,
    ) or 1)
    if scale <= 0:
        scale = 1
    seen: set[str] = set()
    layers: list[dict[str, Any]] = []
    for order, root in enumerate(_sketch_roots(sketch)):
        normalized = _normalize_node(
            root,
            scale=scale,
            parent_id=None,
            order=order,
            seen=seen,
        )
        if normalized:
            layers.append(normalized)
    canvas_frame = layers[0].get("frame", {}) if layers else {}
    width = canvas_frame.get("width") or detail.get("width")
    height = canvas_frame.get("height") or detail.get("height")
    assets = extract_slice_assets(sketch)
    summary = _summarize_layers(layers)
    summary["asset_count"] = len(assets)
    return {
        "source": {
            "url": source_url,
            "project_id": params["project_id"],
            "team_id": params["team_id"],
            "design_id": params["image_id"],
            "name": detail.get("name"),
            "version_id": ((detail.get("versions") or [{}])[0]).get("id"),
            "structure_source": "sketch",
        },
        "canvas": {
            "width": width,
            "height": height,
            "scale": scale,
            "device": sketch.get("device"),
            "source": "fact",
        },
        "summary": summary,
        "layers": layers,
        "assets": assets,
    }


def navigation(layers: list[dict[str, Any]], depth: int = 0) -> list[dict[str, Any]]:
    if depth >= 3:
        return []
    result = []
    for node in layers[:30]:
        children = node.get("children") or []
        item = {
            "id": node.get("id"),
            "name": node.get("name"),
            "type": node.get("type"),
            "frame": node.get("frame"),
            "child_count": len(children),
        }
        nested = navigation(children, depth + 1)
        if nested:
            item["children"] = nested
        result.append(item)
    return result


def write_design_document(document: dict[str, Any], output_file: str) -> Path:
    path = Path(output_file).expanduser()
    if not path.is_absolute():
        raise ValueError("output_file 必须是绝对路径")
    if path.suffix.lower() != ".json":
        raise ValueError("output_file 必须是 .json 文件")
    return atomic_write_text(
        path,
        json.dumps(document, ensure_ascii=False, indent=2),
    )
