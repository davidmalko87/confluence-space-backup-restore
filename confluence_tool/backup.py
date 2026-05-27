# backup.py — Per-space Confluence backup via REST (streaming to disk)
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""BackupManager reads a single Confluence space through the REST API and
streams it to disk: pages (storage body) + hierarchy, blog posts, attachments
(binaries), comments (footer + inline), labels, properties, restrictions and
permissions. A manifest with sha256 checksums is written LAST as the
completion gate.

Streaming: every collection is written item-by-item as it arrives from the API,
so memory stays flat on large spaces. Only lightweight references (id, title,
parentId) are kept in RAM for the dependent phases.
"""

import logging
import os
from pathlib import Path
from typing import Any, Iterable

from confluence_tool import __version__
from confluence_tool.api_client import ConfluenceApiError, ConfluenceClient
from confluence_tool.config import ConfluenceConfig
from confluence_tool import manifest, native_export
from confluence_tool.utils import (
    StreamingJsonArray,
    dir_size_bytes,
    format_size,
    sanitize_filename,
    save_json,
    utc_stamp,
)

logger = logging.getLogger("confluence_tool")


class BackupManager:
    """Backs up one Confluence space to a timestamped directory."""

    def __init__(self, client: ConfluenceClient, config: ConfluenceConfig) -> None:
        self.client = client
        self.config = config
        self._counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def backup_space(self, space_key: str) -> str | None:
        """Back up a single space by key. Returns the backup dir, or None."""
        space = self._resolve_space(space_key)
        if not space:
            logger.error("Space '%s' not found or not accessible.", space_key)
            return None

        space_id = str(space["id"])
        backup_dir = os.path.join(
            self.config.backup_root, f"{sanitize_filename(space_key)}_{utc_stamp()}"
        )
        os.makedirs(backup_dir, exist_ok=True)
        logger.info("Backing up space '%s' (id=%s) -> %s", space_key, space_id, backup_dir)
        self._counts = {}

        # Lightweight references reused by dependent phases (kept in RAM).
        page_refs = self._backup_pages(space_id, backup_dir)
        blog_refs = (
            self._backup_blogposts(space_id, backup_dir)
            if self.config.include_blogposts else []
        )

        self._backup_space_meta(space, backup_dir)

        if self.config.include_attachments:
            self._backup_attachments(page_refs, blog_refs, backup_dir)
        if self.config.include_comments:
            self._backup_comments(page_refs, blog_refs, backup_dir)
        self._backup_labels(space_id, page_refs, blog_refs, backup_dir)
        self._backup_properties(space_id, page_refs, blog_refs, backup_dir)
        if self.config.include_restrictions:
            self._backup_restrictions(page_refs, backup_dir)
        if self.config.include_versions:
            self._backup_versions(page_refs, backup_dir)

        native_info = self._maybe_native_export(space_key, backup_dir)

        self._write_manifest(space_key, backup_dir, native_info)
        self._print_summary(space_key, backup_dir)
        return backup_dir

    # ------------------------------------------------------------------
    # Space resolution + metadata
    # ------------------------------------------------------------------

    def _resolve_space(self, space_key: str) -> dict[str, Any] | None:
        """Resolve a space key to its full v2 object (key->id is via ?keys=)."""
        try:
            data = self.client.get(
                "/api/v2/spaces",
                params={"keys": space_key, "description-format": "storage", "limit": 1},
            )
        except ConfluenceApiError as exc:
            logger.error("Failed to resolve space '%s': %s", space_key, exc)
            return None
        results = data.get("results") or []
        return results[0] if results else None

    def _backup_space_meta(self, space: dict[str, Any], backup_dir: str) -> None:
        """Save the space object + permissions (own files)."""
        save_json(space, os.path.join(backup_dir, "space.json"))
        space_id = str(space["id"])
        try:
            perms = self.client.paginate(f"/api/v2/spaces/{space_id}/permissions")
            save_json(perms, os.path.join(backup_dir, "permissions.json"))
            self._counts["permissions"] = len(perms)
        except ConfluenceApiError as exc:
            logger.warning("Could not read space permissions: %s", exc)

    # ------------------------------------------------------------------
    # Pages + blog posts (streamed)
    # ------------------------------------------------------------------

    def _backup_pages(self, space_id: str, backup_dir: str) -> list[dict[str, Any]]:
        """Stream all current pages to pages.json; return lite references."""
        refs: list[dict[str, Any]] = []
        path = os.path.join(backup_dir, "pages.json")
        params = {"body-format": self.config.body_format, "status": "current"}
        with StreamingJsonArray(path) as out:
            for page in self.client.paginate_iter(
                f"/api/v2/spaces/{space_id}/pages", params=params
            ):
                out.append(page)
                refs.append({
                    "id": str(page["id"]),
                    "title": page.get("title", ""),
                    "parentId": page.get("parentId"),
                    "status": page.get("status"),
                })
                self._tick("pages", out.count)
        self._counts["pages"] = len(refs)
        logger.info("Backed up %d pages", len(refs))
        return refs

    def _backup_blogposts(self, space_id: str, backup_dir: str) -> list[dict[str, Any]]:
        """Stream all blog posts to blogposts.json; return lite references."""
        refs: list[dict[str, Any]] = []
        path = os.path.join(backup_dir, "blogposts.json")
        params = {"body-format": self.config.body_format, "status": "current"}
        with StreamingJsonArray(path) as out:
            for blog in self.client.paginate_iter(
                f"/api/v2/spaces/{space_id}/blogposts", params=params
            ):
                out.append(blog)
                refs.append({"id": str(blog["id"]), "title": blog.get("title", "")})
                self._tick("blogposts", out.count)
        self._counts["blogposts"] = len(refs)
        logger.info("Backed up %d blog posts", len(refs))
        return refs

    # ------------------------------------------------------------------
    # Attachments (metadata streamed; binaries downloaded)
    # ------------------------------------------------------------------

    def _backup_attachments(
        self,
        page_refs: list[dict[str, Any]],
        blog_refs: list[dict[str, Any]],
        backup_dir: str,
    ) -> None:
        """Stream attachment metadata and download each binary to disk."""
        index_path = os.path.join(backup_dir, "attachments.json")
        att_dir = os.path.join(backup_dir, "attachments")
        downloaded = 0
        with StreamingJsonArray(index_path) as out:
            for content_type, refs in (("pages", page_refs), ("blogposts", blog_refs)):
                for ref in refs:
                    cid = ref["id"]
                    for att in self._safe_iter(
                        f"/api/v2/{content_type}/{cid}/attachments"
                    ):
                        record = {"contentId": cid, "contentType": content_type, "attachment": att}
                        out.append(record)
                        if self._download_attachment(att, cid, att_dir):
                            downloaded += 1
                        self._tick("attachments", out.count)
            self._counts["attachments"] = out.count
        logger.info("Backed up %d attachments (%d binaries downloaded)",
                    self._counts.get("attachments", 0), downloaded)

    def _download_attachment(self, att: dict[str, Any], content_id: str, att_dir: str) -> bool:
        """Download one attachment binary; returns True on success."""
        links = att.get("_links") or {}
        download = links.get("download")
        if not download:
            logger.warning("Attachment %s has no download link", att.get("id"))
            return False
        filename = sanitize_filename(att.get("title") or f"{att.get('id')}.bin")
        dest = os.path.join(att_dir, content_id, f"{att.get('id')}_{filename}")
        if os.path.exists(dest):  # resumable: skip already-downloaded files
            return True
        return self.client.download_file(download, dest)

    # ------------------------------------------------------------------
    # Comments (footer + inline, streamed)
    # ------------------------------------------------------------------

    def _backup_comments(
        self,
        page_refs: list[dict[str, Any]],
        blog_refs: list[dict[str, Any]],
        backup_dir: str,
    ) -> None:
        """Stream footer comments (pages + blogs) and inline comments (pages)."""
        footer_path = os.path.join(backup_dir, "comments")
        bf = os.path.join(footer_path, "footer.json")
        inl = os.path.join(footer_path, "inline.json")
        body = {"body-format": self.config.body_format}

        with StreamingJsonArray(bf) as out:
            for content_type, refs in (("pages", page_refs), ("blogposts", blog_refs)):
                for ref in refs:
                    cid = ref["id"]
                    for c in self._safe_iter(
                        f"/api/v2/{content_type}/{cid}/footer-comments", params=body
                    ):
                        out.append({"contentId": cid, "contentType": content_type, "comment": c})
                        self._tick("footer_comments", out.count)
            self._counts["footer_comments"] = out.count

        with StreamingJsonArray(inl) as out:
            for ref in page_refs:
                cid = ref["id"]
                for c in self._safe_iter(
                    f"/api/v2/pages/{cid}/inline-comments", params=body
                ):
                    out.append({"contentId": cid, "contentType": "pages", "comment": c})
                    self._tick("inline_comments", out.count)
            self._counts["inline_comments"] = out.count
        logger.info("Backed up %d footer + %d inline comments",
                    self._counts.get("footer_comments", 0),
                    self._counts.get("inline_comments", 0))

    # ------------------------------------------------------------------
    # Labels / properties / restrictions / versions
    # ------------------------------------------------------------------

    def _backup_labels(
        self,
        space_id: str,
        page_refs: list[dict[str, Any]],
        blog_refs: list[dict[str, Any]],
        backup_dir: str,
    ) -> None:
        """Stream per-content labels and the space's own labels."""
        path = os.path.join(backup_dir, "labels.json")
        with StreamingJsonArray(path) as out:
            try:
                space_labels = self.client.paginate(f"/api/v2/spaces/{space_id}/labels")
                if space_labels:
                    out.append({"contentType": "space", "contentId": space_id,
                                "labels": space_labels})
            except ConfluenceApiError as exc:
                logger.warning("Could not read space labels: %s", exc)
            for content_type, refs in (("pages", page_refs), ("blogposts", blog_refs)):
                for ref in refs:
                    cid = ref["id"]
                    labels = list(self._safe_iter(f"/api/v2/{content_type}/{cid}/labels"))
                    if labels:
                        out.append({"contentType": content_type, "contentId": cid,
                                    "labels": labels})
            self._counts["label_sets"] = out.count

    def _backup_properties(
        self,
        space_id: str,
        page_refs: list[dict[str, Any]],
        blog_refs: list[dict[str, Any]],
        backup_dir: str,
    ) -> None:
        """Stream content properties and the space's properties."""
        prop_dir = os.path.join(backup_dir, "properties")
        try:
            space_props = self.client.paginate(f"/api/v2/spaces/{space_id}/properties")
            save_json(space_props, os.path.join(prop_dir, "space_properties.json"))
        except ConfluenceApiError as exc:
            logger.warning("Could not read space properties: %s", exc)

        path = os.path.join(prop_dir, "content_properties.json")
        with StreamingJsonArray(path) as out:
            for content_type, refs in (("pages", page_refs), ("blogposts", blog_refs)):
                for ref in refs:
                    cid = ref["id"]
                    props = list(self._safe_iter(f"/api/v2/{content_type}/{cid}/properties"))
                    if props:
                        out.append({"contentType": content_type, "contentId": cid,
                                    "properties": props})
            self._counts["property_sets"] = out.count

    def _backup_restrictions(
        self, page_refs: list[dict[str, Any]], backup_dir: str
    ) -> None:
        """Stream per-page restrictions (v1 — no v2 endpoint exists)."""
        path = os.path.join(backup_dir, "restrictions.json")
        with StreamingJsonArray(path) as out:
            for ref in page_refs:
                cid = ref["id"]
                try:
                    data = self.client.get(
                        f"/rest/api/content/{cid}/restriction/byOperation"
                    )
                except ConfluenceApiError as exc:
                    logger.warning("Restrictions read failed for page %s: %s", cid, exc)
                    continue
                if data:
                    out.append({"contentId": cid, "restrictions": data})
            self._counts["restriction_sets"] = out.count

    def _backup_versions(
        self, page_refs: list[dict[str, Any]], backup_dir: str
    ) -> None:
        """Save page version METADATA as a read-only sidecar (never replayed)."""
        ver_dir = os.path.join(backup_dir, "versions")
        saved = 0
        for ref in page_refs:
            cid = ref["id"]
            versions = list(self._safe_iter(f"/api/v2/pages/{cid}/versions"))
            if versions:
                save_json(versions, os.path.join(ver_dir, f"{cid}.json"))
                saved += 1
        self._counts["version_sidecars"] = saved
        logger.info("Saved version metadata for %d pages (reference only)", saved)

    # ------------------------------------------------------------------
    # Native export (optional, best-effort)
    # ------------------------------------------------------------------

    def _maybe_native_export(self, space_key: str, backup_dir: str) -> dict[str, Any]:
        """Optionally trigger a native XML export; never fails the REST backup."""
        if not self.config.native_export:
            return {"present": False}
        logger.info("Attempting optional native XML export (best-effort)...")
        try:
            return native_export.export_space(self.client, self.config, space_key, backup_dir)
        except Exception as exc:  # noqa: BLE001 - fragile undocumented path; never fatal
            logger.warning("Native export failed (non-fatal): %s", exc)
            return {"present": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Manifest + summary
    # ------------------------------------------------------------------

    def _write_manifest(
        self, space_key: str, backup_dir: str, native_info: dict[str, Any]
    ) -> None:
        man = manifest.build(
            Path(backup_dir),
            space_key,
            tool_version=__version__,
            source_site_slug=self.config.site_slug,
            counts=self._counts,
            native_export=native_info,
        )
        manifest.write(man, Path(backup_dir))
        logger.info("Wrote manifest.json (backup marked complete)")

    def _print_summary(self, space_key: str, backup_dir: str) -> None:
        size = format_size(dir_size_bytes(backup_dir))
        logger.info("--- Backup summary: %s ---", space_key)
        for key in sorted(self._counts):
            logger.info("  %-18s %d", key, self._counts[key])
        logger.info("  %-18s %s", "disk size", size)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _safe_iter(self, path: str, params: dict | None = None) -> Iterable[dict]:
        """Paginate an endpoint, downgrading per-content errors to warnings.

        A single page's missing/forbidden sub-resource must not abort the whole
        space backup, so 4xx errors here are logged and skipped.
        """
        try:
            yield from self.client.paginate_iter(path, params=params)
        except ConfluenceApiError as exc:
            logger.warning("Read failed for %s: %s", path, exc)

    def _tick(self, phase: str, count: int) -> None:
        """Log progress every 100 items so long phases show signs of life."""
        if count % 100 == 0:
            logger.info("  %s: %d so far...", phase, count)


# ----------------------------------------------------------------------
# Module-level backup directory utilities (used by menu/export/cli)
# ----------------------------------------------------------------------

def list_backups(backup_root: str) -> list[dict[str, Any]]:
    """List backup directories with completion status and size."""
    root = Path(backup_root)
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        man = manifest.read(d)
        out.append({
            "dir": str(d),
            "name": d.name,
            "space_key": (man or {}).get("space_key", "?"),
            "created": (man or {}).get("created_utc", ""),
            "complete": bool(man and man.get("complete")),
            "size": dir_size_bytes(str(d)),
        })
    return out


def cleanup_incomplete(backup_root: str) -> list[str]:
    """Delete backup directories that lack a complete manifest. Returns removed."""
    from confluence_tool.utils import force_rmtree

    removed: list[str] = []
    for entry in list_backups(backup_root):
        if not entry["complete"]:
            force_rmtree(entry["dir"])
            removed.append(entry["dir"])
    return removed
