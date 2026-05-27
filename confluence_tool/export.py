# export.py — CSV export and backup statistics/analysis
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""Turn a backup directory into shareable CSVs and compute summary statistics
for inspection. Read-only: never mutates a backup.
"""

import csv
import logging
import os
from collections import Counter
from typing import Any

from confluence_tool import manifest
from confluence_tool.utils import (
    dir_size_bytes,
    format_size,
    load_json,
    storage_to_text,
)

logger = logging.getLogger("confluence_tool")


def _body_preview(content: dict[str, Any], limit: int = 200) -> str:
    """Best-effort plain-text preview of a page/blog/comment body."""
    body = content.get("body") or {}
    for fmt in ("storage", "view", "atlas_doc_format"):
        value = (body.get(fmt) or {}).get("value")
        if value:
            return storage_to_text(value, limit)
    return ""


def _load(backup_dir: str, name: str, default: Any) -> Any:
    path = os.path.join(backup_dir, name)
    if not os.path.exists(path):
        return default
    try:
        return load_json(path)
    except (ValueError, OSError):
        return default


def export_backup_to_csv(backup_dir: str, out_dir: str | None = None) -> dict[str, int]:
    """Write pages.csv, blogposts.csv, comments.csv and attachments.csv.

    Args:
        backup_dir: A completed backup directory.
        out_dir: Where to write CSVs (default: ``<backup_dir>/csv_export``).

    Returns:
        Mapping of CSV filename -> number of data rows written.
    """
    out_dir = out_dir or os.path.join(backup_dir, "csv_export")
    os.makedirs(out_dir, exist_ok=True)
    written: dict[str, int] = {}

    pages = _load(backup_dir, "pages.json", [])
    written["pages.csv"] = _write_content_csv(
        os.path.join(out_dir, "pages.csv"), pages, include_parent=True
    )

    blogposts = _load(backup_dir, "blogposts.json", [])
    written["blogposts.csv"] = _write_content_csv(
        os.path.join(out_dir, "blogposts.csv"), blogposts, include_parent=False
    )

    written["comments.csv"] = _write_comments_csv(out_dir, backup_dir)
    written["attachments.csv"] = _write_attachments_csv(out_dir, backup_dir)
    return written


def _write_content_csv(
    path: str, items: list[dict[str, Any]], *, include_parent: bool
) -> int:
    headers = ["ID", "Title", "Status", "Version", "AuthorId", "CreatedAt"]
    if include_parent:
        headers.insert(2, "ParentID")
    headers.append("BodyPreview")

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for item in items:
            row = [
                item.get("id", ""),
                item.get("title", ""),
                item.get("status", ""),
                (item.get("version") or {}).get("number", ""),
                item.get("authorId", "") or (item.get("version") or {}).get("authorId", ""),
                item.get("createdAt", ""),
            ]
            if include_parent:
                row.insert(2, item.get("parentId", "") or "")
            row.append(_body_preview(item))
            writer.writerow(row)
    return len(items)


def _write_comments_csv(out_dir: str, backup_dir: str) -> int:
    footer = _load(backup_dir, os.path.join("comments", "footer.json"), [])
    inline = _load(backup_dir, os.path.join("comments", "inline.json"), [])
    rows = 0
    with open(os.path.join(out_dir, "comments.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ContentID", "ContentType", "Kind", "CommentID", "BodyPreview"])
        for kind, records in (("footer", footer), ("inline", inline)):
            for rec in records:
                comment = rec.get("comment", {})
                writer.writerow([
                    rec.get("contentId", ""),
                    rec.get("contentType", ""),
                    kind,
                    comment.get("id", ""),
                    _body_preview(comment),
                ])
                rows += 1
    return rows


def _write_attachments_csv(out_dir: str, backup_dir: str) -> int:
    records = _load(backup_dir, "attachments.json", [])
    with open(os.path.join(out_dir, "attachments.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ContentID", "ContentType", "AttachmentID", "Filename",
                         "MediaType", "FileSize"])
        for rec in records:
            att = rec.get("attachment", {})
            writer.writerow([
                rec.get("contentId", ""),
                rec.get("contentType", ""),
                att.get("id", ""),
                att.get("title", ""),
                att.get("mediaType", ""),
                att.get("fileSize", ""),
            ])
    return len(records)


def get_backup_statistics(backup_dir: str) -> dict[str, Any]:
    """Compute counts, page-status breakdown, and disk size for a backup."""
    man = manifest.read(backup_dir) or {}
    pages = _load(backup_dir, "pages.json", [])
    status_breakdown = Counter(p.get("status", "unknown") for p in pages)

    return {
        "space_key": man.get("space_key", "?"),
        "created": man.get("created_utc", ""),
        "complete": bool(man.get("complete")),
        "counts": man.get("counts", {}),
        "page_status_breakdown": dict(status_breakdown),
        "native_export": man.get("native_export", {"present": False}),
        "size_bytes": dir_size_bytes(backup_dir),
        "size_human": format_size(dir_size_bytes(backup_dir)),
    }
