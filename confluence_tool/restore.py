# restore.py — Phased restore of a backed-up space into a NEW Confluence space
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""RestoreManager rebuilds a backed-up space via the REST API, in dependency
order, with resumable progress and a dry-run preview.

Safety: restore defaults to creating a NEW space and refuses to touch an
existing space key unless ``overwrite=True`` is passed (the interactive typed
confirmation lives in the menu/CLI layer). It never deletes content.

Ordered phases (and why):
  1. space        - everything needs the new spaceId
  2. pages        - top-down so each child's new parentId exists; mints id map
  3. blogposts    - flat; may be macro-referenced
  4. remap        - 2nd pass: rewrite ri:content-id refs now all new ids exist
  5. attachments  - need the new content id
  6. comments     - footer (inline is best-effort, off by default)
  7. labels       - need the new content id
  8. properties   - need the new content id
  9. restrictions - LAST, so applying them can't lock the API user out mid-run

Fidelity is content-faithful, not forensic: original author/created-date and
version history CANNOT be set via the API (see README). Original author + date
are preserved as a footer note and a content property instead.
"""

import logging
import os
from collections import deque
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from confluence_tool import __version__
from confluence_tool.api_client import ConfluenceApiError, ConfluenceClient
from confluence_tool.config import ConfluenceConfig
from confluence_tool.macros import body_has_content_ids, remap_body, scan_id_macros
from confluence_tool.progress import ProgressTracker
from confluence_tool.utils import load_json, sanitize_filename

logger = logging.getLogger("confluence_tool")

PHASES = (
    "space", "pages", "blogposts", "remap",
    "attachments", "comments", "labels", "properties", "restrictions",
)


class RestoreManager:
    """Restores a backup directory into a target Confluence space."""

    def __init__(
        self,
        client: ConfluenceClient,
        config: ConfluenceConfig,
        *,
        dry_run: bool = False,
    ) -> None:
        self.client = client
        self.config = config
        self.dry_run = dry_run
        self.rep = config.body_format
        self._progress: ProgressTracker | None = None
        self._new_space_id: str = ""
        # Creating a space auto-generates a homepage; we adopt it for the source
        # homepage instead of creating a duplicate.
        self._source_homepage_id: str = ""
        self._new_homepage_id: str = ""

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def restore(
        self,
        backup_dir: str,
        target_key: str,
        *,
        target_name: str | None = None,
        overwrite: bool = False,
    ) -> bool:
        """Restore a backup into ``target_key``.

        Returns True on success. Refuses (returns False) if the target space
        already exists and ``overwrite`` is False.
        """
        bdir = Path(backup_dir)
        if not (bdir / "manifest.json").exists():
            logger.error("No manifest.json in %s — not a complete backup.", backup_dir)
            return False

        space_meta = self._load(bdir, "space.json", default={})
        pages = self._load(bdir, "pages.json", default=[])
        blogposts = self._load(bdir, "blogposts.json", default=[])

        self._progress = ProgressTracker(backup_dir, dry_run=self.dry_run)

        mode = "DRY-RUN (no changes will be written)" if self.dry_run else "LIVE"
        logger.info("Restore [%s]: %s -> space '%s'", mode, backup_dir, target_key)
        logger.info("Plan: %d pages, %d blog posts", len(pages), len(blogposts))

        # Phase 1: space (also the overwrite safety gate)
        if not self.is_done("space"):
            new_space_id = self._restore_space(space_meta, target_key, target_name, overwrite)
            if new_space_id is None:
                return False
            self._new_space_id = new_space_id
            self.done("space")
        else:
            self._new_space_id = self._resolve_target_id(target_key) or ""

        if not self._new_space_id:
            logger.error("Could not determine target space id; aborting.")
            return False

        # Adopt the space's auto-created homepage for the source homepage so the
        # restore doesn't leave a duplicate "<name> Home" page behind.
        self._source_homepage_id = str(space_meta.get("homepageId") or "")
        self._new_homepage_id = self._resolve_homepage_id(self._new_space_id)

        self._run_phase("pages", lambda: self._restore_pages(pages))
        self._run_phase("blogposts", lambda: self._restore_blogposts(blogposts))
        self._run_phase("remap", lambda: self._remap_bodies(pages, blogposts))
        self._run_phase("attachments", lambda: self._restore_attachments(bdir))
        self._run_phase("comments", lambda: self._restore_comments(bdir))
        self._run_phase("labels", lambda: self._restore_labels(bdir))
        self._run_phase("properties", lambda: self._restore_properties(bdir))
        self._run_phase("restrictions", lambda: self._restore_restrictions(bdir))

        self._note_unrestorable(bdir)
        logger.info("Restore %s.", "preview complete" if self.dry_run else "complete")
        return True

    # ------------------------------------------------------------------
    # Phase 1 — space
    # ------------------------------------------------------------------

    def _restore_space(
        self,
        space_meta: dict[str, Any],
        target_key: str,
        target_name: str | None,
        overwrite: bool,
    ) -> str | None:
        """Create the target space, or reuse it under overwrite. Returns its id."""
        existing_id = self._resolve_target_id(target_key)
        if existing_id:
            if not overwrite:
                logger.error(
                    "Target space '%s' already exists. Refusing to modify it. "
                    "Re-run with overwrite to add into it, or choose a new key.",
                    target_key,
                )
                return None
            logger.warning("Overwrite: restoring INTO existing space '%s'.", target_key)
            return existing_id

        name = target_name or space_meta.get("name") or target_key
        if self.dry_run:
            logger.info("[DRY] would create space key='%s' name='%s'", target_key, name)
            return f"DRY-{target_key}"

        body = {
            "key": target_key,
            "name": name,
            "description": {
                "plain": {"value": self._space_description(space_meta), "representation": "plain"}
            },
        }
        try:
            self.client.post("/rest/api/space", body)
        except ConfluenceApiError as exc:
            if exc.status_code == 400 and "exist" in exc.body.lower():
                logger.error(
                    "Space key '%s' is taken (possibly a trashed space not yet "
                    "purged). Purge it under Settings > Data Management > Trashed "
                    "Spaces, or choose a different --target-key.", target_key,
                )
            else:
                logger.error("Failed to create space '%s': %s", target_key, exc)
            return None

        new_id = self._resolve_target_id(target_key)
        if new_id:
            logger.info("Created space '%s' (id=%s)", target_key, new_id)
        return new_id

    # ------------------------------------------------------------------
    # Phase 2/3 — pages (top-down) and blog posts
    # ------------------------------------------------------------------

    def _restore_pages(self, pages: list[dict[str, Any]]) -> int:
        """Create pages parent-before-child and record the old->new id map.

        Returns the number of pages that failed to create.
        """
        failures = 0
        for page in self._creation_order(pages):
            old_id = str(page["id"])
            if self._progress.is_mapped("pages", old_id):
                continue
            # The source homepage adopts the space's auto-created homepage (update
            # in place) rather than being added as a duplicate child page.
            if old_id == self._source_homepage_id and self._new_homepage_id:
                if self._adopt_homepage(page):
                    self._progress.map_id("pages", old_id, self._new_homepage_id)
                else:
                    failures += 1
                continue
            parent_old = page.get("parentId")
            new_parent = self._progress.get_new_id("pages", str(parent_old)) if parent_old else None
            new_id = self._create_content("pages", page, new_parent)
            if new_id:
                self._progress.map_id("pages", old_id, new_id)
            else:
                failures += 1
        return failures

    def _resolve_homepage_id(self, space_id: str) -> str:
        """Return the space's homepage id (the page auto-created with the space)."""
        try:
            sp = self.client.get(f"/api/v2/spaces/{space_id}")
        except ConfluenceApiError:
            return ""
        return str(sp.get("homepageId") or "")

    def _adopt_homepage(self, page: dict[str, Any]) -> bool:
        """Update the space's auto-created homepage to match the source homepage."""
        new_id = self._new_homepage_id
        title = page.get("title", "")
        if self.dry_run:
            logger.info("[DRY] would adopt space homepage as '%s' (id %s)", title, new_id)
            return True
        value = self._with_footer(self._body_value(page), page)
        try:
            current = self.client.get(f"/api/v2/pages/{new_id}")
            next_ver = int((current.get("version") or {}).get("number", 1)) + 1
            self.client.put(f"/api/v2/pages/{new_id}", {
                "id": new_id,
                "status": "current",
                "title": title,
                "body": {"representation": self.rep, "value": value},
                "version": {"number": next_ver, "message": "restore: adopt homepage"},
            })
        except ConfluenceApiError as exc:
            logger.error("Failed to adopt homepage as '%s': %s", title, exc)
            return False
        self._set_provenance("pages", new_id, page)
        logger.info("Adopted space homepage as '%s'", title)
        return True

    def _restore_blogposts(self, blogposts: list[dict[str, Any]]) -> int:
        """Create blog posts (flat). Returns the number that failed to create."""
        failures = 0
        for blog in blogposts:
            old_id = str(blog["id"])
            if self._progress.is_mapped("blogposts", old_id):
                continue
            new_id = self._create_content("blogposts", blog, None)
            if new_id:
                self._progress.map_id("blogposts", old_id, new_id)
            else:
                failures += 1
        return failures

    def _create_content(
        self, kind: str, content: dict[str, Any], new_parent_id: str | None
    ) -> str | None:
        """POST a page or blog post with an attribution footer. Returns new id."""
        title = content.get("title", "")
        value = self._with_footer(self._body_value(content), content)
        if self.dry_run:
            logger.info("[DRY] would create %s '%s'", kind[:-1], title)
            return f"DRY-{content['id']}"

        payload: dict[str, Any] = {
            "spaceId": self._new_space_id,
            "status": "current",
            "title": title,
            "body": {"representation": self.rep, "value": value},
        }
        if kind == "pages" and new_parent_id:
            payload["parentId"] = new_parent_id
        try:
            resp = self.client.post(f"/api/v2/{kind}", payload)
        except ConfluenceApiError as exc:
            logger.error("Failed to create %s '%s': %s", kind[:-1], title, exc)
            return None
        new_id = str(resp.get("id", ""))
        if new_id:
            self._set_provenance(kind, new_id, content)
        return new_id or None

    # ------------------------------------------------------------------
    # Phase 4 — macro / link ID remap (second pass)
    # ------------------------------------------------------------------

    def _remap_bodies(
        self, pages: list[dict[str, Any]], blogposts: list[dict[str, Any]]
    ) -> None:
        """Rewrite ri:content-id references using the full old->new content map."""
        id_map = self._progress.combined_content_map()
        for kind, items in (("pages", pages), ("blogposts", blogposts)):
            for content in items:
                old_id = str(content["id"])
                new_id = self._progress.get_new_id(kind, old_id)
                if not new_id or self._progress.is_item_done("remap", f"{kind}:{old_id}"):
                    continue
                value = self._with_footer(self._body_value(content), content)
                if not body_has_content_ids(value, self.rep):
                    self._progress.mark_item_done("remap", f"{kind}:{old_id}")
                    continue
                new_value, unmapped = remap_body(value, self.rep, id_map)
                macros = scan_id_macros(value)
                if unmapped:
                    logger.warning(
                        "%s %s: %d unmapped content-id ref(s) %s%s",
                        kind[:-1], old_id, len(unmapped), sorted(unmapped),
                        f"; ID-macros present: {sorted(macros)}" if macros else "",
                    )
                self._put_body(kind, new_id, content.get("title", ""), new_value)
                self._progress.mark_item_done("remap", f"{kind}:{old_id}")

    def _put_body(self, kind: str, new_id: str, title: str, value: str) -> None:
        """PUT an updated body (bumping the version) after a remap."""
        if self.dry_run:
            logger.info("[DRY] would remap+update %s '%s'", kind[:-1], title)
            return
        try:
            current = self.client.get(f"/api/v2/{kind}/{new_id}")
            next_ver = int((current.get("version") or {}).get("number", 1)) + 1
            self.client.put(f"/api/v2/{kind}/{new_id}", {
                "id": new_id,
                "status": "current",
                "title": title,
                "body": {"representation": self.rep, "value": value},
                "version": {"number": next_ver, "message": "ID remap (restore)"},
            })
        except ConfluenceApiError as exc:
            logger.warning("Remap PUT failed for %s %s: %s", kind[:-1], new_id, exc)

    # ------------------------------------------------------------------
    # Phase 5 — attachments
    # ------------------------------------------------------------------

    def _restore_attachments(self, bdir: Path) -> int:
        """Upload backed-up attachment binaries to their restored content.

        Returns the number of attachments that failed to upload.
        """
        records = self._load(bdir, "attachments.json", default=[])
        att_root = bdir / "attachments"
        failures = 0
        for rec in records:
            old_cid = str(rec.get("contentId"))
            kind = rec.get("contentType", "pages")
            att = rec.get("attachment", {})
            att_id = str(att.get("id", ""))
            marker = f"{old_cid}:{att_id}"
            if self._progress.is_item_done("attachments", marker):
                continue
            new_cid = self._progress.get_new_id(kind, old_cid)
            if not new_cid:
                logger.warning("No mapping for %s %s; skipping attachment %s",
                               kind, old_cid, att_id)
                failures += 1
                continue
            filename = att.get("title") or f"{att_id}.bin"
            local = att_root / old_cid / f"{att_id}_{sanitize_filename(filename)}"
            if not local.exists():
                logger.warning("Attachment binary missing on disk: %s", local)
                failures += 1
                continue
            if self.dry_run:
                logger.info("[DRY] would upload attachment '%s' to %s %s",
                            filename, kind[:-1], new_cid)
                self._progress.mark_item_done("attachments", marker)
                continue
            try:
                self.client.upload_file(
                    f"/rest/api/content/{new_cid}/child/attachment",
                    str(local), filename=filename,
                )
                self._progress.mark_item_done("attachments", marker)
            except ConfluenceApiError as exc:
                logger.warning("Attachment upload failed (%s): %s", filename, exc)
                failures += 1
        return failures

    # ------------------------------------------------------------------
    # Phase 6 — comments
    # ------------------------------------------------------------------

    def _restore_comments(self, bdir: Path) -> int:
        """Restore footer comments (top-level). Inline comments are skipped.

        Returns the number of footer comments that failed to create.
        """
        footer = self._load(bdir, os.path.join("comments", "footer.json"), default=[])
        failures = 0
        for rec in footer:
            old_cid = str(rec.get("contentId"))
            kind = rec.get("contentType", "pages")
            comment = rec.get("comment", {})
            marker = f"{kind}:{old_cid}:{comment.get('id')}"
            if self._progress.is_item_done("comments", marker):
                continue
            new_cid = self._progress.get_new_id(kind, old_cid)
            if not new_cid:
                continue
            value = self._with_footer(self._body_value(comment), comment, kind_label="comment")
            ref_key = "pageId" if kind == "pages" else "blogPostId"
            if self.dry_run:
                logger.info("[DRY] would create footer comment on %s %s", kind[:-1], new_cid)
                self._progress.mark_item_done("comments", marker)
                continue
            try:
                self.client.post("/api/v2/footer-comments", {
                    ref_key: new_cid,
                    "body": {"representation": self.rep, "value": value},
                })
                self._progress.mark_item_done("comments", marker)
            except ConfluenceApiError as exc:
                logger.warning("Footer comment create failed on %s: %s", new_cid, exc)
                failures += 1

        inline = self._load(bdir, os.path.join("comments", "inline.json"), default=[])
        if inline:
            logger.warning(
                "%d inline comment(s) were backed up but NOT restored: re-anchoring "
                "to text is unreliable via the API (see README). They remain in the "
                "backup for reference.", len(inline),
            )
        return failures

    # ------------------------------------------------------------------
    # Phase 7 — labels
    # ------------------------------------------------------------------

    def _restore_labels(self, bdir: Path) -> None:
        """Re-apply page/blog labels (v1). Space labels are not API-restorable."""
        for entry in self._load(bdir, "labels.json", default=[]):
            kind = entry.get("contentType")
            old_cid = str(entry.get("contentId"))
            labels = entry.get("labels", [])
            if kind == "space":
                logger.info("Space-level labels are not restorable via API; skipping.")
                continue
            new_cid = self._progress.get_new_id(kind, old_cid)
            if not new_cid or not labels:
                continue
            body = [{"prefix": lab.get("prefix", "global"), "name": lab.get("name", "")}
                    for lab in labels if lab.get("name")]
            if self.dry_run:
                logger.info("[DRY] would add %d label(s) to %s %s", len(body), kind[:-1], new_cid)
                continue
            try:
                # v1 label endpoint expects a bare JSON array of {prefix, name}.
                self.client.post(f"/rest/api/content/{new_cid}/label", body)
            except ConfluenceApiError as exc:
                logger.warning("Label add failed on %s: %s", new_cid, exc)

    # ------------------------------------------------------------------
    # Phase 8 — properties
    # ------------------------------------------------------------------

    def _restore_properties(self, bdir: Path) -> None:
        """Recreate content properties and space properties."""
        space_props = self._load(bdir, os.path.join("properties", "space_properties.json"),
                                  default=[])
        for prop in space_props:
            self._post_property(f"/api/v2/spaces/{self._new_space_id}/properties", prop, "space")

        for entry in self._load(bdir, os.path.join("properties", "content_properties.json"),
                                default=[]):
            kind = entry.get("contentType", "pages")
            new_cid = self._progress.get_new_id(kind, str(entry.get("contentId")))
            if not new_cid:
                continue
            for prop in entry.get("properties", []):
                self._post_property(f"/api/v2/{kind}/{new_cid}/properties", prop, kind)

    def _post_property(self, path: str, prop: dict[str, Any], label: str) -> None:
        key = prop.get("key")
        if not key:
            return
        if self.dry_run:
            logger.info("[DRY] would set %s property '%s'", label, key)
            return
        try:
            self.client.post(path, {"key": key, "value": prop.get("value")})
        except ConfluenceApiError as exc:
            # System-managed properties commonly reject writes; not fatal.
            logger.debug("Property '%s' not set on %s: %s", key, label, exc)

    # ------------------------------------------------------------------
    # Phase 9 — restrictions (best-effort, last)
    # ------------------------------------------------------------------

    def _restore_restrictions(self, bdir: Path) -> None:
        """Re-apply page restrictions (v1, best-effort; identities must resolve)."""
        for entry in self._load(bdir, "restrictions.json", default=[]):
            new_cid = self._progress.get_new_id("pages", str(entry.get("contentId")))
            if not new_cid:
                continue
            payload = _restriction_payload(entry.get("restrictions", {}))
            if not payload:
                continue
            if self.dry_run:
                logger.info("[DRY] would apply restrictions to page %s", new_cid)
                continue
            try:
                # v1 restriction endpoint expects a bare JSON array.
                self.client.put(f"/rest/api/content/{new_cid}/restriction", payload)
            except ConfluenceApiError as exc:
                logger.warning("Restriction apply failed on %s (identities may not "
                               "exist in target): %s", new_cid, exc)

    # ------------------------------------------------------------------
    # Body / attribution helpers
    # ------------------------------------------------------------------

    def _body_value(self, content: dict[str, Any]) -> str:
        body = content.get("body") or {}
        fmt = body.get(self.rep) or {}
        return fmt.get("value", "") or ""

    def _with_footer(
        self, value: str, content: dict[str, Any], kind_label: str = "page"
    ) -> str:
        """Prepend an attribution footer (storage format only).

        ADF bodies are left untouched (provenance still goes to a property).
        """
        if self.rep != "storage":
            return value
        author = escape(self._author_label(content))
        created = escape(str(content.get("createdAt", "") or "unknown date"))
        note = (
            f"<p><em>[Originally created by {author} on {created}; "
            f"restored via confluence-space-backup-restore v{__version__}]</em></p>"
        )
        return note + value

    def _author_label(self, content: dict[str, Any]) -> str:
        account_id = content.get("authorId") or (content.get("version") or {}).get("authorId")
        if not account_id:
            return "unknown author"
        found, cached = self._progress.get_cached_user(account_id)
        if found:
            return cached or account_id
        name = account_id
        try:
            user = self.client.get("/rest/api/user", params={"accountId": account_id})
            name = user.get("displayName") or account_id
        except ConfluenceApiError:
            pass
        self._progress.cache_user(account_id, name)
        return name

    def _set_provenance(self, kind: str, new_id: str, content: dict[str, Any]) -> None:
        """Store original author/date/source-id as a machine-readable property."""
        if self.dry_run:
            return
        value = {
            "sourceId": str(content.get("id", "")),
            "authorId": content.get("authorId") or (content.get("version") or {}).get("authorId"),
            "createdAt": content.get("createdAt"),
            "sourceVersion": (content.get("version") or {}).get("number"),
            "restoredBy": f"confluence-space-backup-restore v{__version__}",
        }
        try:
            self.client.post(f"/api/v2/{kind}/{new_id}/properties",
                             {"key": "original_provenance", "value": value})
        except ConfluenceApiError as exc:
            logger.debug("Could not set provenance property on %s %s: %s", kind, new_id, exc)

    def _space_description(self, space_meta: dict[str, Any]) -> str:
        desc = (space_meta.get("description") or {})
        for fmt in ("plain", "view", "storage"):
            value = (desc.get(fmt) or {}).get("value")
            if value:
                return value
        return f"Restored by confluence-space-backup-restore v{__version__}"

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    def _resolve_target_id(self, target_key: str) -> str | None:
        try:
            data = self.client.get("/api/v2/spaces", params={"keys": target_key, "limit": 1})
        except ConfluenceApiError:
            return None
        results = data.get("results") or []
        return str(results[0]["id"]) if results else None

    @staticmethod
    def _creation_order(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return pages ordered parent-before-child (BFS from roots)."""
        by_id = {str(p["id"]): p for p in pages}
        children: dict[str, list[dict[str, Any]]] = {}
        roots: list[dict[str, Any]] = []
        for p in pages:
            parent = p.get("parentId")
            if parent and str(parent) in by_id:
                children.setdefault(str(parent), []).append(p)
            else:
                roots.append(p)
        order: list[dict[str, Any]] = []
        queue = deque(roots)
        while queue:
            node = queue.popleft()
            order.append(node)
            queue.extend(children.get(str(node["id"]), []))
        return order

    def _note_unrestorable(self, bdir: Path) -> None:
        """Log a clear reminder of what was intentionally not restored."""
        perms = self._load(bdir, "permissions.json", default=[])
        if perms:
            logger.info(
                "Note: %d space permission assignment(s) were backed up but NOT "
                "applied (cross-tenant identity remap required). See permissions.json.",
                len(perms),
            )

    def _load(self, bdir: Path, rel: str, default: Any) -> Any:
        path = bdir / rel
        if not path.exists():
            return default
        try:
            return load_json(str(path))
        except (ValueError, OSError) as exc:
            logger.warning("Could not read %s: %s", rel, exc)
            return default

    # -- phase plumbing -------------------------------------------------

    def _run_phase(self, name: str, fn: Any) -> None:
        if self.is_done(name):
            logger.info("Phase '%s' already complete; skipping.", name)
            return
        logger.info("== Phase: %s ==", name)
        failures = fn() or 0
        if failures:
            # Leave the phase incomplete so the next run retries the failed items
            # (the Jira tool's rule: a phase is complete only when fail == 0).
            logger.warning(
                "Phase '%s' had %d failure(s); not marking complete — re-run to "
                "retry.", name, failures,
            )
        else:
            self.done(name)

    def is_done(self, phase: str) -> bool:
        return bool(self._progress and self._progress.is_phase_complete(phase))

    def done(self, phase: str) -> None:
        if self._progress:
            self._progress.mark_phase_complete(phase)


def _restriction_payload(by_operation: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a v1 byOperation restrictions read into a v1 update array."""
    out: list[dict[str, Any]] = []
    for operation in ("read", "update"):
        block = by_operation.get(operation) or {}
        restr = block.get("restrictions") or {}
        users = [{"type": "known", "accountId": u.get("accountId")}
                 for u in (restr.get("user") or {}).get("results", []) if u.get("accountId")]
        groups = [{"type": "group", "name": g.get("name")}
                  for g in (restr.get("group") or {}).get("results", []) if g.get("name")]
        if users or groups:
            out.append({"operation": operation, "restrictions": {"user": users, "group": groups}})
    return out
