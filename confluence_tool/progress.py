# progress.py — Resumability and state tracking for restore
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""ProgressTracker persists restore state across runs so an interrupted restore
can resume without duplicating work.

It maintains, in the backup directory:
- id_maps.json        : old->new ID maps per kind (pages, blogposts, comments)
- restore_progress.json : completed phases and per-phase done items
- user_cache.json     : email/accountId resolution cache

State is written immediately after every change, so a crash loses at most the
in-flight item. In dry-run mode nothing is written to disk.
"""

import logging
import os
from typing import Any

from confluence_tool.utils import load_json, save_json

logger = logging.getLogger("confluence_tool")


class ProgressTracker:
    """Tracks restore progress for resumability."""

    def __init__(self, backup_dir: str, *, dry_run: bool = False) -> None:
        self.backup_dir = backup_dir
        self._dry_run = dry_run
        self._id_maps_path = os.path.join(backup_dir, "id_maps.json")
        self._progress_path = os.path.join(backup_dir, "restore_progress.json")
        self._user_cache_path = os.path.join(backup_dir, "user_cache.json")

        if dry_run:
            self._id_maps: dict[str, dict[str, str]] = {}
            self._progress: dict[str, Any] = {}
            self._user_cache: dict[str, str | None] = {}
        else:
            self._id_maps = self._load_or_empty(self._id_maps_path)
            self._progress = self._load_or_empty(self._progress_path)
            self._user_cache = self._load_or_empty(self._user_cache_path)

    # ------------------------------------------------------------------
    # ID maps (old content ID -> new content ID), keyed by kind
    # ------------------------------------------------------------------

    def map_id(self, kind: str, old_id: str, new_id: str) -> None:
        """Record an old->new ID mapping for a kind and persist immediately."""
        self._id_maps.setdefault(kind, {})[str(old_id)] = str(new_id)
        if not self._dry_run:
            save_json(self._id_maps, self._id_maps_path)

    def get_new_id(self, kind: str, old_id: str) -> str | None:
        """Return the new ID for an old ID of the given kind, or None."""
        return self._id_maps.get(kind, {}).get(str(old_id))

    def is_mapped(self, kind: str, old_id: str) -> bool:
        """True if an old ID of the given kind has already been created."""
        return str(old_id) in self._id_maps.get(kind, {})

    def id_map(self, kind: str) -> dict[str, str]:
        """Return the full old->new map for a kind (empty dict if none)."""
        return dict(self._id_maps.get(kind, {}))

    def combined_content_map(self) -> dict[str, str]:
        """Merge page + blogpost maps for body/macro ID remapping."""
        merged: dict[str, str] = {}
        merged.update(self._id_maps.get("pages", {}))
        merged.update(self._id_maps.get("blogposts", {}))
        return merged

    # ------------------------------------------------------------------
    # Phase tracking
    # ------------------------------------------------------------------

    def mark_phase_complete(self, phase: str) -> None:
        """Mark a restore phase as fully complete and persist."""
        phases = self._progress.setdefault("completed_phases", [])
        if phase not in phases:
            phases.append(phase)
            self._save_progress()
        logger.info("Phase '%s' marked complete", phase)

    def is_phase_complete(self, phase: str) -> bool:
        """True if a phase was already completed in a prior run."""
        return phase in self._progress.get("completed_phases", [])

    # ------------------------------------------------------------------
    # Per-item tracking within a phase
    # ------------------------------------------------------------------

    def mark_item_done(self, phase: str, item_id: str) -> None:
        """Mark a specific item within a phase as done and persist."""
        items = self._progress.setdefault("items", {})
        phase_items = items.setdefault(phase, [])
        if str(item_id) not in phase_items:
            phase_items.append(str(item_id))
            self._save_progress()

    def is_item_done(self, phase: str, item_id: str) -> bool:
        """True if a specific item was already processed in this phase."""
        items = self._progress.get("items", {})
        return str(item_id) in items.get(phase, [])

    # ------------------------------------------------------------------
    # User cache (email/accountId -> resolved accountId)
    # ------------------------------------------------------------------

    def cache_user(self, key: str, account_id: str | None) -> None:
        """Cache a user lookup result (account_id may be None = not found)."""
        self._user_cache[key] = account_id
        if not self._dry_run:
            save_json(self._user_cache, self._user_cache_path)

    def get_cached_user(self, key: str) -> tuple[bool, str | None]:
        """Return (found, account_id). found is True even when account_id is None."""
        if key in self._user_cache:
            return True, self._user_cache[key]
        return False, None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_progress(self) -> None:
        if not self._dry_run:
            save_json(self._progress, self._progress_path)

    @staticmethod
    def _load_or_empty(path: str) -> dict:
        if os.path.exists(path):
            try:
                return load_json(path)
            except Exception as exc:  # noqa: BLE001 - corrupt state -> start fresh
                logger.warning("Could not load %s: %s — starting fresh", path, exc)
        return {}
