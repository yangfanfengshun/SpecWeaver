#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = [
#   "beautifulsoup4>=4.12.0,<5.0.0",
#   "cryptography>=43.0.0,<47.0.0",
#   "fastmcp>=3.3.1,<4.0.0",
#   "httpx>=0.27.0,<1.0.0",
#   "lxml>=5.0.0,<7.0.0",
#   "markdownify>=0.13.0,<2.0.0",
#   "mistune>=3.0.0,<4.0.0",
#   "python-dotenv>=1.0.0,<2.0.0",
# ]
# ///
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse

from fastmcp import FastMCP
import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import (
    UnsafePathError,
    atomic_write_text,
    ensure_no_symlink_components,
    prepare_output_dir,
    unsafe_symlink_components,
)
from eolink import server as eolink
from lanhu import server as lanhu
from tower import server as tower


mcp = FastMCP("SpecWeaver Requirement Collector")
RESTRICTED_ATTACHMENT_KINDS = {"archive", "video"}
LARGE_ATTACHMENT_BYTES = 20 * 1024 * 1024


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def safe_directory_name(title: str, fallback: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", title).strip(" .-")
    if not value or value in {".", ".."}:
        value = f"tower-{fallback}"
    return value[:100].rstrip(" .") or f"tower-{fallback}"


def safe_file_component(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value).strip(" .-")
    raw = (cleaned or fallback).encode("utf-8")[:100]
    while raw:
        try:
            return raw.decode("utf-8").rstrip(" .") or fallback
        except UnicodeDecodeError:
            raw = raw[:-1]
    return fallback


def specweaver_home() -> Path:
    return Path(
        os.getenv("SPECWEAVER_HOME", Path.home() / ".specweaver")
    ).expanduser().absolute()


def requirement_manifest_file(tower_key: str, output_dir: Path) -> Path:
    output_hash = hashlib.sha256(
        str(output_dir.resolve()).encode("utf-8")
    ).hexdigest()[:16]
    return (
        specweaver_home()
        / "cache"
        / "requirements"
        / tower_key
        / output_hash
        / "manifest.json"
    )


def lanhu_design_cache_file(image_id: str, name: str) -> Path:
    safe_id = safe_file_component(image_id, "unknown")
    safe_name = safe_file_component(name, "未命名设计")
    return (
        specweaver_home()
        / "cache"
        / "lanhu"
        / safe_id
        / f"{safe_name}--{safe_id}.json"
    )


def relative_to_output(path: str | Path, output_dir: Path) -> str:
    return str(Path(path).resolve().relative_to(output_dir.resolve()))


def safe_extension(source_url: str, content_type: str) -> str:
    guessed = mimetypes.guess_extension(content_type, strict=False) or ""
    if guessed == ".jpe":
        guessed = ".jpg"
    if guessed:
        return guessed
    suffix = Path(urlparse(source_url).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        return suffix
    return ".bin"


def error_status(error: Exception) -> tuple[str, str]:
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        status = (
            "auth_expired" if code == 401
            else "forbidden" if code == 403
            else "api_error"
        )
        return status, f"HTTP {code}"
    if isinstance(error, httpx.HTTPError):
        return "network_error", str(error)
    return "download_error", str(error)


def lanhu_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        status = (
            "auth_expired" if code in {401, 418}
            else "forbidden" if code == 403
            else "api_error"
        )
        return status, f"蓝湖返回 HTTP {code}"
    if isinstance(error, httpx.HTTPError):
        return "network_error", str(error)
    return "api_error", str(error)


def unsafe_managed_paths(paths: list[Path]) -> list[str]:
    unsafe = []
    for path in paths:
        if path.is_symlink():
            unsafe.append(str(path))
            continue
        if not path.is_dir():
            continue
        for child in path.rglob("*"):
            if child.is_symlink():
                unsafe.append(str(child))
    return unsafe


def remove_empty_directories(root: Path) -> None:
    if not root.is_dir():
        return
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass


def clean_legacy_project_artifacts(output_dir: Path) -> None:
    for file_name in ("collection-manifest.json", "tower-attachments.json"):
        path = output_dir / file_name
        if path.is_file() and not path.is_symlink():
            path.unlink()
    design_dir = output_dir / "design"
    if design_dir.is_dir() and not design_dir.is_symlink():
        for path in design_dir.iterdir():
            if path.is_file() and re.fullmatch(
                r"lanhu-\d{3}\.json",
                path.name,
                re.I,
            ):
                path.unlink()
        remove_empty_directories(design_dir)


def normalize_scope(confirmed_scope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(confirmed_scope, dict):
        raise ValueError("confirmed_scope 必须是对象")
    required = {
        "tower_attachments",
        "allow_restricted_attachments",
        "replace_existing",
        "lanhu",
        "eolink",
        "skipped_sources",
    }
    missing = sorted(required - confirmed_scope.keys())
    if missing:
        raise ValueError(
            f"confirmed_scope 缺少字段: {', '.join(missing)}"
        )
    lanhu_scope = confirmed_scope.get("lanhu") or []
    eolink_scope = confirmed_scope.get("eolink") or []
    if not isinstance(lanhu_scope, list) or not all(
        isinstance(item, dict) for item in lanhu_scope
    ):
        raise ValueError("confirmed_scope.lanhu 必须是对象数组")
    if not isinstance(eolink_scope, list) or not all(
        isinstance(item, dict) for item in eolink_scope
    ):
        raise ValueError("confirmed_scope.eolink 必须是对象数组")
    for key in (
        "tower_attachments",
        "allow_restricted_attachments",
        "replace_existing",
    ):
        value = confirmed_scope[key]
        if not isinstance(value, bool):
            raise ValueError(f"confirmed_scope.{key} 必须是布尔值")

    normalized_lanhu = []
    seen_lanhu = set()
    for item in lanhu_scope:
        normalized = {
            "url": str(item.get("url") or "").strip(),
            "image_id": str(item.get("image_id") or item.get("id") or "").strip(),
            "name": str(item.get("name") or "").strip(),
        }
        key = (normalized["url"], normalized["image_id"])
        if key not in seen_lanhu:
            seen_lanhu.add(key)
            normalized_lanhu.append(normalized)
    normalized_lanhu.sort(key=lambda item: (item["url"], item["image_id"]))

    normalized_eolink = []
    seen_eolink = set()
    for item in eolink_scope:
        source_url = str(item.get("url") or "").strip()
        api_ids = item.get("api_ids")
        if api_ids is not None:
            if not isinstance(api_ids, list) or not api_ids or not all(
                isinstance(api_id, int) and not isinstance(api_id, bool)
                for api_id in api_ids
            ):
                raise ValueError(
                    "Eolink 范围的 api_ids 必须是非空整数数组"
                )
            api_ids = sorted(set(api_ids))
        key = (source_url, tuple(api_ids or []))
        if key not in seen_eolink:
            seen_eolink.add(key)
            normalized_eolink.append({
                "url": source_url,
                **({"api_ids": api_ids} if api_ids is not None else {}),
            })
    normalized_eolink.sort(
        key=lambda item: (item["url"], tuple(item.get("api_ids") or []))
    )
    skipped_sources = confirmed_scope.get("skipped_sources") or []
    if not isinstance(skipped_sources, list) or not all(
        isinstance(item, dict) for item in skipped_sources
    ):
        raise ValueError("confirmed_scope.skipped_sources 必须是对象数组")
    normalized_skipped = []
    seen_skipped = set()
    for item in skipped_sources:
        normalized = {
            "source": str(item.get("source") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
        }
        key = (
            normalized["source"],
            normalized["url"],
            normalized["reason"],
        )
        if key not in seen_skipped:
            seen_skipped.add(key)
            normalized_skipped.append(normalized)
    normalized_skipped.sort(
        key=lambda item: (item["source"], item["url"], item["reason"])
    )
    for item in normalized_skipped:
        if (
            item["source"] not in {"tower", "lanhu", "eolink"}
            or not item["url"]
            or not item["reason"]
        ):
            raise ValueError(
                "skipped_sources 每项必须包含 tower/lanhu/eolink 来源、URL 和原因"
            )
    return {
        "tower_attachments": confirmed_scope["tower_attachments"],
        "allow_restricted_attachments": confirmed_scope[
            "allow_restricted_attachments"
        ],
        "replace_existing": confirmed_scope["replace_existing"],
        "lanhu": normalized_lanhu,
        "eolink": normalized_eolink,
        "skipped_sources": normalized_skipped,
    }


def parse_size_bytes(value: str) -> int | None:
    normalized = value.strip().replace(",", "")
    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|字节)?",
        normalized,
        re.I,
    )
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    multiplier = {
        "B": 1,
        "字节": 1,
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
    }[unit]
    return int(number * multiplier)


def compact_design_candidates(result: dict[str, Any], source_url: str) -> dict:
    if result.get("status") != "success":
        return {
            "source_url": source_url,
            "status": result.get("status", "api_error"),
            "message": result.get("message", "蓝湖候选读取失败"),
            "items": [],
        }
    items = []
    for item in result.get("designs") or []:
        items.append({
            "id": str(item.get("id") or item.get("image_id") or ""),
            "name": str(item.get("name") or ""),
            "url": source_url,
            "preview_url": str(
                item.get("preview_url")
                or item.get("url")
                or ""
            ),
            "sectors": item.get("sectors") or [],
        })
    return {
        "source_url": source_url,
        "status": "success",
        "project_name": result.get("project_name") or "",
        "items": items,
    }


def compact_api_candidates(payload: dict[str, Any], source_url: str) -> dict:
    items = []
    for item in payload.get("apiList") or []:
        items.append({
            "api_id": item.get("apiID"),
            "name": item.get("apiName") or item.get("name") or "",
            "method": item.get("apiRequestType") or item.get("method") or "",
            "path": item.get("apiURI") or item.get("path") or "",
        })
    return {
        "source_url": source_url,
        "status": "success",
        "location": payload.get("location") or {},
        "items": items,
    }


async def discover_candidates(data: dict[str, Any]) -> dict[str, Any]:
    sources = data.get("external_sources") or {}
    result: dict[str, Any] = {"lanhu": [], "eolink": []}
    for source_url in sources.get("lanhu") or []:
        try:
            parsed = lanhu.parse_lanhu_design_url(source_url)
            if parsed.get("image_id"):
                result["lanhu"].append({
                    "source_url": source_url,
                    "status": "success",
                    "items": [{
                        "id": str(parsed["image_id"]),
                        "name": "",
                        "url": source_url,
                        "sectors": [],
                    }],
                })
                continue
            result["lanhu"].append(
                compact_design_candidates(
                    await lanhu.lanhu_get_designs(source_url),
                    source_url,
                )
            )
        except Exception as error:
            result["lanhu"].append({
                "source_url": source_url,
                "status": "api_error",
                "message": str(error),
                "items": [],
            })
    for source_url in sources.get("eolink") or []:
        try:
            raw = await eolink.eolink_read_url(source_url, include_details=False)
            if raw.startswith("错误:"):
                raise ValueError(raw.removeprefix("错误:").strip())
            result["eolink"].append(
                compact_api_candidates(json.loads(raw), source_url)
            )
        except Exception as error:
            classified = eolink.auth_error(error)
            result["eolink"].append({
                "source_url": source_url,
                "status": classified["status"],
                "message": classified["message"],
                "items": [],
            })
    return result


def suggested_scope_from_candidates(
    candidates: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    scope: dict[str, Any] = {
        "tower_attachments": True,
        "allow_restricted_attachments": False,
        "replace_existing": False,
        "lanhu": [],
        "eolink": [],
        "skipped_sources": [],
    }
    unambiguous = True
    for source in candidates.get("lanhu") or []:
        items = source.get("items") or []
        if source.get("status") != "success" or len(items) != 1:
            unambiguous = False
            continue
        item = items[0]
        if not item.get("id"):
            unambiguous = False
            continue
        scope["lanhu"].append({
            "url": item.get("url") or source.get("source_url"),
            "image_id": item.get("id") or "",
            "name": item.get("name") or "",
        })
    for source in candidates.get("eolink") or []:
        items = source.get("items") or []
        if source.get("status") != "success" or len(items) != 1:
            unambiguous = False
            continue
        api_id = items[0].get("api_id")
        if not isinstance(api_id, int) or isinstance(api_id, bool):
            unambiguous = False
            continue
        scope["eolink"].append({
            "url": source.get("source_url"),
            "api_ids": [api_id],
        })
    return scope, unambiguous


async def download_tower_attachments(
    data: dict[str, Any],
    output_dir: Path,
    *,
    allow_restricted: bool,
    skipped_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    target_dir = output_dir / "tower-attachments"
    target_dir.mkdir(parents=True, exist_ok=True)
    unique = data.get("attachments") or []
    downloaded: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    hashes: dict[str, dict[str, Any]] = {}
    saved_names: set[str] = set()
    skipped_urls = skipped_urls or {}

    for source_index, attachment in enumerate(unique, 1):
        source_url = str(attachment["source_url"])
        if source_url in skipped_urls:
            skipped.append({
                "source_index": source_index,
                "source_url": source_url,
                "name": attachment.get("name") or "未提供",
                "kind": attachment.get("kind"),
                "status": "skipped",
                "message": skipped_urls[source_url],
            })
            continue
        known_size = parse_size_bytes(str(attachment.get("size") or ""))
        if (
            (
                attachment.get("kind") in RESTRICTED_ATTACHMENT_KINDS
                or (
                    known_size is not None
                    and known_size > LARGE_ATTACHMENT_BYTES
                )
            )
            and not allow_restricted
        ):
            skipped.append({
                "source_index": source_index,
                "source_url": source_url,
                "name": attachment.get("name") or "未提供",
                "kind": attachment.get("kind"),
                "status": "confirmation_required",
                "message": "视频、压缩包或已知超大附件需要用户确认后下载",
            })
            continue
        try:
            response = await tower.request(source_url)
            content_type = (
                response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            content_hash = hashlib.sha256(response.content).hexdigest()
            if content_hash in hashes:
                original = hashes[content_hash]
                downloaded.append({
                    "source_index": source_index,
                    "source_url": source_url,
                    "name": attachment.get("name") or "未提供",
                    "status": "duplicate",
                    "path": original["path"],
                    "sha256": content_hash,
                })
                continue
            extension = safe_extension(source_url, content_type)
            file_name = f"tower-attachment-{len(hashes) + 1:03d}{extension}"
            file_path = target_dir / file_name
            file_path.write_bytes(response.content)
            saved_names.add(file_name)
            item = {
                "source_index": source_index,
                "source_url": source_url,
                "name": attachment.get("name") or "未提供",
                "status": "success",
                "path": relative_to_output(file_path, output_dir),
                "content_type": content_type or "application/octet-stream",
                "bytes": len(response.content),
                "sha256": content_hash,
            }
            hashes[content_hash] = item
            downloaded.append(item)
        except Exception as error:
            status, message = error_status(error)
            failures.append({
                "source_index": source_index,
                "source_url": source_url,
                "name": attachment.get("name") or "未提供",
                "status": status,
                "message": message,
            })

    owned_pattern = re.compile(
        r"tower-attachment-\d{3}\.[a-z0-9]{1,10}",
        re.I,
    )
    for old_file in target_dir.iterdir():
        if (
            old_file.is_file()
            and owned_pattern.fullmatch(old_file.name)
            and old_file.name not in saved_names
        ):
            old_file.unlink()

    by_url = {
        item["source_url"]: item
        for item in [*downloaded, *failures, *skipped]
    }
    occurrences = []
    for occurrence in data.get("attachment_occurrences") or []:
        source = by_url.get(occurrence["source_url"], {})
        occurrences.append({
            "occurrence_index": occurrence["occurrence_index"],
            "scope": occurrence["scope"],
            "scope_index": occurrence["scope_index"],
            "position": occurrence["position"],
            "source_url": occurrence["source_url"],
            "name": occurrence.get("name") or "未提供",
            "status": source.get("status", "not_downloaded"),
            "path": source.get("path"),
            "message": source.get("message"),
        })
    manifest = {
        "source_count": len(unique),
        "saved_count": len(hashes),
        "downloaded": downloaded,
        "skipped": skipped,
        "failures": failures,
        "occurrences": occurrences,
    }
    status = "success"
    if failures or any(
        item.get("status") != "skipped"
        for item in skipped
    ):
        status = "partial"
    return {
        "status": status,
        "saved_count": len(hashes),
        "failures": failures,
        "skipped": skipped,
        "occurrences": occurrences,
        "downloaded": downloaded,
        "source_count": len(unique),
        "artifacts": [
            item["path"]
            for item in downloaded
            if item["status"] == "success"
        ],
    }


async def collect_lanhu(
    scope: list[dict],
    output_dir: Path,
) -> dict[str, Any]:
    image_dir = output_dir / "images"
    results: list[dict[str, Any]] = []
    previews: list[dict[str, Any]] = []
    for item in scope:
        source_url = str(item.get("url") or "").strip()
        image_id = str(item.get("image_id") or item.get("id") or "").strip()
        if not source_url:
            results.append({
                "status": "invalid_input",
                "message": "蓝湖范围缺少 url",
            })
            continue
        preliminary_file = lanhu_design_cache_file(
            image_id,
            str(item.get("name") or "未命名设计"),
        )
        try:
            ensure_no_symlink_components(preliminary_file)
            detail = await lanhu.lanhu_get_design_detail(
                source_url,
                image_id=image_id,
                output_file=str(preliminary_file),
            )
        except Exception as error:
            status, message = lanhu_error(error)
            results.append({
                "source_url": source_url,
                "image_id": image_id,
                "status": status,
                "message": message,
            })
            continue
        entry = {
            "source_url": source_url,
            "image_id": image_id,
            "status": detail.get("status", "api_error"),
            "message": detail.get("message", ""),
        }
        if detail.get("status") != "success":
            results.append(entry)
            continue
        source = detail.get("source") or {}
        selected_id = str(source.get("design_id") or image_id)
        design_name = str(
            source.get("name") or item.get("name") or "未命名设计"
        )
        cache_file = lanhu_design_cache_file(selected_id, design_name)
        if not preliminary_file.is_file():
            entry.update({
                "status": "verification_failed",
                "message": "蓝湖声明写入成功但规范化结构文件不存在",
            })
            results.append(entry)
            continue
        try:
            document = json.loads(preliminary_file.read_text(encoding="utf-8"))
            atomic_write_text(cache_file, canonical_json(document))
            if preliminary_file.resolve() != cache_file.resolve():
                preliminary_file.unlink()
        except (OSError, ValueError, TypeError) as error:
            entry.update({
                "status": "verification_failed",
                "message": f"蓝湖规范化结构无法验证: {error}",
            })
            results.append(entry)
            continue
        if cache_file.parent.is_dir():
            for old_file in cache_file.parent.glob("*.json"):
                if old_file.resolve() != cache_file.resolve():
                    old_file.unlink()
        entry.update({
            "image_id": selected_id,
            "project_id": str(source.get("project_id") or ""),
            "version_id": str(source.get("version_id") or ""),
            "name": design_name,
            "design_cache_file": str(cache_file.resolve()),
        })
        file_stem = (
            f"{safe_file_component(design_name, '未命名设计')}--"
            f"{safe_file_component(selected_id, 'unknown')}"
        )
        preview_url = str(detail.get("preview_url") or "")
        if preview_url:
            previews.append({
                "id": selected_id,
                "name": design_name,
                "url": preview_url,
                "file_stem": f"{file_stem}-preview",
            })
        slices_dir = image_dir / "lanhu-slices" / file_stem
        try:
            slices = await lanhu.lanhu_download_slices(
                source_url,
                selected_id,
                str(slices_dir.resolve()),
                manifest_file="",
            )
            entry["slices_status"] = slices.get("status", "api_error")
            entry["slice_count"] = slices.get("saved_count", 0)
            slice_files = []
            for asset in slices.get("assets") or []:
                local_path = asset.get("local_path")
                if not local_path:
                    continue
                candidate = Path(str(local_path))
                if not candidate.is_absolute():
                    candidate = slices_dir / candidate
                try:
                    slice_files.append(
                        relative_to_output(candidate, output_dir)
                    )
                except ValueError:
                    entry["slices_status"] = "invalid_output"
                    entry["slices_message"] = "蓝湖切图路径越出目标目录"
            entry["slice_files"] = sorted(set(slice_files))
            if entry["slice_count"] and not entry["slice_files"]:
                entry["slices_status"] = "verification_failed"
                entry["slices_message"] = "蓝湖切图声明成功但没有返回可验证文件"
        except Exception as error:
            status, message = lanhu_error(error)
            entry["slices_status"] = status
            entry["slices_message"] = message
            entry["slice_count"] = 0
        if entry["slices_status"] in {"success", "partial"}:
            entry["slices_dir"] = relative_to_output(slices_dir, output_dir)
        results.append(entry)

    preview_result: dict[str, Any] = {
        "status": "not_applicable",
        "saved_count": 0,
        "images": [],
    }
    if previews:
        try:
            preview_result = await lanhu.lanhu_download_design_images(
                previews,
                str(image_dir.resolve()),
            )
        except Exception as error:
            status, message = lanhu_error(error)
            preview_result = {
                "status": status,
                "saved_count": 0,
                "images": [],
                "failures": [{
                    "status": status,
                    "message": message,
                }],
            }
    preview_files = {}
    for image in preview_result.get("images") or []:
        path = image.get("path")
        if not path and image.get("duplicate_of"):
            path = image_dir / str(image["duplicate_of"])
        if path:
            preview_files[str(image.get("design_id") or "")] = relative_to_output(
                path,
                output_dir,
            )
    for entry in results:
        preview_file = preview_files.get(str(entry.get("image_id") or ""))
        if preview_file:
            entry["preview_file"] = preview_file
    failures = [
        item for item in results
        if item.get("status") != "success"
        or item.get("slices_status") not in {None, "success"}
    ]
    preview_failures = list(preview_result.get("failures") or [])
    if (
        preview_result.get("status") not in {"success", "not_applicable"}
        and not preview_failures
    ):
        preview_failures.append({
            "status": preview_result.get("status", "api_error"),
            "message": preview_result.get("message")
            or "蓝湖预览图收集失败",
        })
    status = "success" if not failures else "partial"
    if preview_failures:
        status = "partial"
    detail_failures = [
        item for item in results
        if item.get("status") != "success"
    ]
    if scope and len(detail_failures) == len(scope):
        statuses = {item.get("status") for item in detail_failures}
        if len(statuses) == 1:
            status = statuses.pop() or "api_error"
    if image_dir.is_dir() and not failures and not preview_failures:
        active_previews = {
            Path(item["preview_file"]).name
            for item in results
            if item.get("preview_file")
        }
        owned_preview = re.compile(
            r"(?:lanhu-\d{3}|.+--[^/]+)-preview\.(gif|jpe?g|png|svg|webp)",
            re.I,
        )
        for old_file in image_dir.iterdir():
            if (
                old_file.is_file()
                and owned_preview.fullmatch(old_file.name)
                and old_file.name not in active_previews
            ):
                old_file.unlink()
        active_slices = {
            (output_dir / path).resolve()
            for item in results
            for path in item.get("slice_files") or []
        }
        slice_root = image_dir / "lanhu-slices"
        owned_slice = re.compile(
            r"lanhu-slice-\d{3}\.(gif|jpe?g|png|svg|webp)",
            re.I,
        )
        if slice_root.is_dir():
            for old_file in slice_root.rglob("*"):
                if (
                    old_file.is_file()
                    and owned_slice.fullmatch(old_file.name)
                    and old_file.resolve() not in active_slices
                ):
                    old_file.unlink()
            remove_empty_directories(slice_root)
    return {
        "status": status if scope else "not_applicable",
        "source_count": len(scope),
        "design_count": sum(
            bool(item.get("design_cache_file")) for item in results
        ),
        "preview_count": preview_result.get("saved_count", 0),
        "items": results,
        "preview_failures": preview_failures,
    }


async def collect_eolink(
    scope: list[dict],
    output_dir: Path,
) -> dict[str, Any]:
    target_dir = output_dir / "api"
    results: list[dict[str, Any]] = []
    saved_names: set[str] = set()
    for item in scope:
        source_url = str(item.get("url") or "").strip()
        requested_api_ids = item.get("api_ids")
        if not source_url:
            results.append({
                "status": "invalid_input",
                "message": "Eolink 范围缺少 url",
            })
            continue
        try:
            location = eolink.parse_eolink_url(source_url)
            api_ids = item.get("api_ids")
            if api_ids is not None:
                if not isinstance(api_ids, list) or not all(
                    isinstance(api_id, int) and not isinstance(api_id, bool)
                    for api_id in api_ids
                ):
                    raise ValueError("Eolink 范围的 api_ids 必须是整数数组")
                details = []
                for api_id in api_ids:
                    raw_detail = await eolink.eolink_get_interface_detail(
                        location["projectID"],
                        api_id,
                    )
                    detail = json.loads(raw_detail)
                    status_code = detail.get("statusCode")
                    if (
                        status_code is not None
                        and str(status_code) != eolink.SUCCESS_CODE
                    ):
                        raise ValueError(
                            f"Eolink API {api_id} 返回失败状态 {status_code}"
                        )
                    actual_id = (
                        ((detail.get("apiInfo") or {}).get("baseInfo") or {})
                        .get("apiID")
                    )
                    if actual_id is not None and str(actual_id) != str(api_id):
                        raise ValueError(
                            f"Eolink 返回 API ID {actual_id}，与确认的 {api_id} 不一致"
                        )
                    details.append(detail)
                api_list = []
            else:
                raw = await eolink.eolink_read_url(source_url, include_details=True)
                if raw.startswith("错误:"):
                    raise ValueError(raw.removeprefix("错误:").strip())
                payload = json.loads(raw)
                location = payload.get("location") or location
                api_list = payload.get("apiList") or []
                details = payload.get("apiDetails") or []

            list_by_id = {
                str(api.get("apiID")): api
                for api in api_list
                if api.get("apiID") is not None
            }
            records = []
            for position, detail in enumerate(details):
                base = ((detail.get("apiInfo") or {}).get("baseInfo") or {})
                api_id = base.get("apiID")
                if api_id is None and position < len(api_list):
                    api_id = api_list[position].get("apiID")
                if api_id is None:
                    raise ValueError("Eolink 接口详情缺少 API ID")
                list_item = list_by_id.get(str(api_id), {})
                api_name = str(
                    base.get("apiName")
                    or list_item.get("apiName")
                    or list_item.get("name")
                    or f"API-{api_id}"
                )
                records.append((int(api_id), api_name, detail))

            for api_id, api_name, detail in sorted(
                records,
                key=lambda record: record[0],
            ):
                file_name = (
                    f"{api_id}-"
                    f"{safe_file_component(api_name, f'API-{api_id}')}.json"
                )
                payload = {
                    "schema_version": 1,
                    "specweaver_schema": "eolink-api",
                    "platform": "eolink",
                    "source_url": source_url,
                    "location": location,
                    "project_id": location.get("projectID"),
                    "group_id": location.get("groupID"),
                    "api_id": api_id,
                    "api_name": api_name,
                    "api_detail": detail,
                }
                output_file = atomic_write_text(
                    target_dir / file_name,
                    canonical_json(payload),
                )
                saved_names.add(output_file.name)
                results.append({
                    "status": "success",
                    "source_url": source_url,
                    "api_id": api_id,
                    "name": api_name,
                    "path": relative_to_output(output_file, output_dir),
                })
        except Exception as error:
            classified = eolink.auth_error(error)
            results.append({
                "status": classified["status"],
                "source_url": source_url,
                "api_ids": requested_api_ids or [],
                "message": classified["message"],
            })
    failures = [item for item in results if item["status"] != "success"]
    successful_ids = {
        item["api_id"]
        for item in results
        if item.get("status") == "success" and item.get("api_id") is not None
    }
    if target_dir.is_dir():
        for old_file in target_dir.iterdir():
            if not old_file.is_file() or old_file.name in saved_names:
                continue
            owned = bool(re.fullmatch(r"eolink-\d{3}\.json", old_file.name, re.I))
            old_api_id = None
            if old_file.suffix.lower() == ".json" and not owned:
                try:
                    old_payload = json.loads(old_file.read_text(encoding="utf-8"))
                    owned = old_payload.get("specweaver_schema") == "eolink-api"
                    old_api_id = old_payload.get("api_id")
                except (OSError, ValueError, TypeError):
                    owned = False
            if owned and (not failures or old_api_id in successful_ids):
                old_file.unlink()
    results.sort(key=lambda item: (
        item.get("status") != "success",
        item.get("api_id", 2 ** 63),
        item.get("source_url", ""),
    ))
    status = "not_applicable"
    if scope:
        status = "success" if not failures else "partial"
        if len(failures) == len(scope):
            failure_statuses = {item["status"] for item in failures}
            status = (
                failure_statuses.pop()
                if len(failure_statuses) == 1
                else "partial"
            )
    return {
        "status": status,
        "source_count": len(scope),
        "api_count": sum(item.get("status") == "success" for item in results),
        "items": results,
    }


def verify_artifacts(output_dir: Path, manifest: dict[str, Any]) -> list[str]:
    missing = []
    paths = [
        "tower-raw.md",
        *manifest["tower"]["attachments"].get("artifacts", []),
    ]
    for item in manifest["lanhu"].get("items", []):
        cache_file = item.get("design_cache_file")
        if cache_file and not Path(str(cache_file)).is_file():
            missing.append(f"蓝湖缓存缺失：{cache_file}")
        paths.append(item.get("preview_file"))
        paths.extend(item.get("slice_files") or [])
    for item in manifest["eolink"].get("items", []):
        paths.append(item.get("path"))
    for relative in filter(None, paths):
        path = (output_dir / str(relative)).resolve()
        try:
            path.relative_to(output_dir.resolve())
        except ValueError:
            missing.append(f"路径越界：{relative}")
            continue
        if not path.is_file():
            missing.append(str(relative))
    return missing


@mcp.tool()
async def requirement_get_manifest(
    tower_url: str,
    output_dir: str,
) -> dict[str, Any] | str:
    """定位已收集需求在用户缓存中的清单，不返回清单正文。"""
    url_error = tower.validate_tower_todo_url(tower_url)
    if url_error:
        return f"错误: {url_error}"
    try:
        target_dir = Path(output_dir).expanduser()
        if not target_dir.is_absolute():
            raise ValueError("output_dir 必须是绝对路径")
        manifest_file = requirement_manifest_file(
            tower.tower_cache_key({}, tower_url),
            target_dir,
        )
        ensure_no_symlink_components(manifest_file)
    except UnsafePathError as error:
        return {
            "status": "invalid_output",
            "message": str(error),
        }
    except ValueError as error:
        return {"status": "invalid_input", "message": str(error)}
    if not manifest_file.is_file():
        return {
            "status": "cache_missing",
            "manifest_file": str(manifest_file),
            "message": "收集清单缓存不存在；请先完成需求资料收集",
        }
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {
            "status": "cache_invalid",
            "manifest_file": str(manifest_file),
            "message": str(error),
        }
    if (
        (manifest.get("tower") or {}).get("source_url") != tower_url
        or Path(str(manifest.get("output_dir") or "")).resolve()
        != target_dir.resolve()
    ):
        return {
            "status": "cache_invalid",
            "manifest_file": str(manifest_file),
            "message": "收集清单与请求的 Tower 链接或项目目录不一致",
        }
    return {
        "status": manifest.get("status", "success"),
        "manifest_file": str(manifest_file.resolve()),
        "output_dir": manifest.get("output_dir") or str(target_dir.resolve()),
        "schema_version": manifest.get("schema_version"),
    }


@mcp.tool()
async def requirement_collect(
    tower_url: str,
    output_dir: str = "",
    confirmed_scope: dict[str, Any] | None = None,
) -> dict[str, Any] | str:
    """确定性编排 Tower、蓝湖和 Eolink；未确认范围时只返回候选，确认后写入项目。"""
    url_error = tower.validate_tower_todo_url(tower_url)
    if url_error:
        return f"错误: {url_error}"
    try:
        data, cache_file = tower.read_cached_tower_data(tower_url)
    except FileNotFoundError as error:
        return {
            "status": "cache_missing",
            "platform": "tower",
            "message": str(error),
        }
    except Exception as error:
        return {
            "status": "cache_invalid",
            "platform": "tower",
            "message": str(error),
        }

    if confirmed_scope is None:
        candidates = await discover_candidates(data)
        suggested_scope, scope_ready = suggested_scope_from_candidates(candidates)
        return {
            **tower.tower_read_summary(data, cache_file),
            "status": (
                "scope_ready" if scope_ready
                else "scope_confirmation_required"
            ),
            "candidates": candidates,
            "suggested_scope": suggested_scope,
            "suggested_directory_name": safe_directory_name(
                data.get("title") or "",
                tower.tower_cache_key(data, tower_url),
            ),
            "message": (
                "来源候选唯一，可使用 suggested_scope"
                if scope_ready
                else "请确认 Tower 附件、蓝湖设计和 Eolink API 范围后再次调用"
            ),
        }
    if not output_dir:
        return {
            "status": "invalid_input",
            "message": "确认完整收集后必须提供绝对 output_dir",
        }
    requested_output = Path(output_dir).expanduser()
    unsafe_output = unsafe_symlink_components(requested_output)
    if unsafe_output:
        return {
            "status": "invalid_output",
            "output_dir": str(requested_output),
            "unsafe_paths": [str(path) for path in unsafe_output],
            "message": "output_dir 路径中不允许符号链接",
        }
    try:
        normalized_scope = normalize_scope(confirmed_scope)
        target_dir = prepare_output_dir(output_dir)
        lanhu_scope = normalized_scope["lanhu"]
        eolink_scope = normalized_scope["eolink"]
    except UnsafePathError as error:
        return {
            "status": "invalid_output",
            "output_dir": str(requested_output),
            "message": str(error),
        }
    except ValueError as error:
        return {"status": "invalid_input", "message": str(error)}

    cache_paths = [
        requirement_manifest_file(
            tower.tower_cache_key(data, tower_url),
            target_dir,
        ),
        *(
            lanhu_design_cache_file(
                str(item.get("image_id") or item.get("id") or ""),
                str(item.get("name") or "未命名设计"),
            )
            for item in lanhu_scope
        ),
    ]
    unsafe_cache_paths = sorted({
        str(component)
        for path in cache_paths
        for component in unsafe_symlink_components(path)
    })
    if unsafe_cache_paths:
        return {
            "status": "invalid_output",
            "output_dir": str(target_dir),
            "unsafe_paths": unsafe_cache_paths,
            "message": "SpecWeaver 用户缓存路径中不允许符号链接",
        }

    managed_paths = [
        target_dir / "tower-raw.md",
        target_dir / "tower-attachments.json",
        target_dir / "collection-manifest.json",
        target_dir / "tower-attachments",
        target_dir / "design",
        target_dir / "images",
        target_dir / "api",
    ]
    existing_managed = [
        str(path)
        for path in managed_paths
        if path.exists()
    ]
    unsafe_paths = unsafe_managed_paths(managed_paths)
    if unsafe_paths:
        return {
            "status": "invalid_output",
            "output_dir": str(target_dir),
            "unsafe_paths": unsafe_paths,
            "message": "脚本管理路径中不允许符号链接",
        }
    if existing_managed and not normalized_scope["replace_existing"]:
        return {
            "status": "existing_output_confirmation_required",
            "output_dir": str(target_dir),
            "existing_managed_paths": existing_managed,
            "message": (
                "目标目录已有脚本管理的来源文件；请确认更新后将 "
                "replace_existing 设为 true"
            ),
        }
    if normalized_scope["replace_existing"]:
        clean_legacy_project_artifacts(target_dir)

    project_tower_raw = atomic_write_text(
        target_dir / "tower-raw.md",
        cache_file.read_text(encoding="utf-8"),
    )
    if normalized_scope["tower_attachments"]:
        skipped_tower_attachments = {
            item["url"]: item["reason"]
            for item in normalized_scope["skipped_sources"]
            if item["source"] == "tower"
        }
        attachments = await download_tower_attachments(
            data,
            target_dir,
            allow_restricted=bool(
                normalized_scope["allow_restricted_attachments"]
            ),
            skipped_urls=skipped_tower_attachments,
        )
    else:
        old_attachment_dir = target_dir / "tower-attachments"
        owned_attachment = re.compile(
            r"tower-attachment-\d{3}\.[a-z0-9]{1,10}",
            re.I,
        )
        if old_attachment_dir.is_dir():
            for old_file in old_attachment_dir.iterdir():
                if (
                    old_file.is_file()
                    and owned_attachment.fullmatch(old_file.name)
                ):
                    old_file.unlink()
        attachments = {
            "status": "skipped",
            "saved_count": 0,
            "failures": [],
            "skipped": [],
            "occurrences": [],
            "downloaded": [],
            "source_count": len(data.get("attachments") or []),
            "artifacts": [],
        }
    lanhu_result = await collect_lanhu(lanhu_scope, target_dir)
    eolink_result = await collect_eolink(eolink_scope, target_dir)
    manifest = {
        "schema_version": 2,
        "output_dir": str(target_dir),
        "tower": {
            "status": "success",
            "todo_id": data.get("todo_id") or "未提供",
            "task_title": data.get("title") or "未提供",
            "task_type": data.get("task_type", "requirement"),
            "source_url": tower_url,
            "raw_file": relative_to_output(project_tower_raw, target_dir),
            "attachments": attachments,
        },
        "lanhu": lanhu_result,
        "eolink": eolink_result,
        "confirmed_scope": normalized_scope,
    }
    missing = verify_artifacts(target_dir, manifest)
    statuses = {
        attachments["status"],
        lanhu_result["status"],
        eolink_result["status"],
    } - {"success", "not_applicable", "skipped"}
    status = "success" if not statuses and not missing else "partial"
    manifest["verification"] = {
        "status": "success" if not missing else "failed",
        "missing": missing,
    }
    manifest["status"] = status
    manifest_file = atomic_write_text(
        requirement_manifest_file(
            tower.tower_cache_key(data, tower_url),
            target_dir,
        ),
        canonical_json(manifest),
    )
    unresolved = [
        item["message"]
        for item in attachments.get("skipped", [])
        if item.get("status") != "skipped"
    ]
    unresolved.extend(
        item.get("message") or (
            f"Tower 附件失败：{item.get('source_url', '未提供')}"
        )
        for item in attachments.get("failures", [])
    )
    unresolved.extend(
        item.get("slices_message")
        or item.get("message")
        or f"蓝湖收集失败：{item.get('source_url', '未提供')}"
        for item in lanhu_result.get("items", [])
        if item.get("status") != "success"
        or item.get("slices_status") not in {None, "success"}
    )
    unresolved.extend(
        item.get("message")
        or item.get("error")
        or "蓝湖预览图收集失败"
        for item in lanhu_result.get("preview_failures", [])
    )
    unresolved.extend(
        item.get("message") or f"Eolink 收集失败：{item.get('source_url', '未提供')}"
        for item in eolink_result.get("items", [])
        if item.get("status") != "success"
    )
    unresolved.extend(f"缺少文件：{item}" for item in missing)
    return {
        "status": status,
        "output_dir": str(target_dir),
        "manifest_file": str(manifest_file),
        "tower_raw_file": str(project_tower_raw),
        "attachment_count": attachments.get("saved_count", 0),
        "lanhu_design_count": lanhu_result.get("design_count", 0),
        "eolink_api_count": eolink_result.get("api_count", 0),
        "unresolved": unresolved,
        "next_action": (
            "让用户选择重试失败来源、明确跳过，或明确接受现有缺失后分析；"
            "重试同一目录时保持 confirmed_scope 并设置 replace_existing=true"
            if status == "partial"
            else "询问用户是否需要分析；未确认前不要生成 requirement.md"
        ),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
