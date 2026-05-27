# manifest.py — Backup manifest: file index, sha256 checksums, completion flag
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""A manifest.json is written LAST when a per-space backup completes.

Its presence with ``"complete": true`` marks the backup as trustworthy (mirrors
the sibling tools' convention), and it records a sha256 for every file so
integrity can be verified later and incomplete backups can be cleaned up safely.
"""

import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
SCHEMA_VERSION = 1

# A healthy native Confluence XML space export contains these entries; their
# absence in a "valid ZIP" is surfaced as a warning, not a hard failure.
_NATIVE_EXPORT_MARKERS = ("entities.xml", "exportDescriptor.properties")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Return the hex sha256 of a file, read in 1 MiB blocks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _index_files(backup_dir: Path) -> list[dict[str, Any]]:
    """Build a sorted file index (relative path, size, sha256).

    Excludes the manifest itself and any *.log (logs are not part of the
    backup payload and are gitignored as potentially sensitive).
    """
    entries: list[dict[str, Any]] = []
    for path in sorted(backup_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == MANIFEST_NAME or path.suffix == ".log":
            continue
        rel = path.relative_to(backup_dir).as_posix()
        entries.append({
            "path": rel,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return entries


def build(
    backup_dir: Path,
    space_key: str,
    *,
    tool_version: str,
    source_site_slug: str = "",
    counts: dict[str, int] | None = None,
    native_export: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a manifest describing a completed backup directory."""
    return {
        "schema": SCHEMA_VERSION,
        "tool_version": tool_version,
        "space_key": space_key,
        "source_site_slug": source_site_slug,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "counts": counts or {},
        "native_export": native_export or {"present": False},
        "files": _index_files(backup_dir),
    }


def write(manifest: dict[str, Any], backup_dir: Path) -> Path:
    """Write the manifest to backup_dir/manifest.json and return its path."""
    path = backup_dir / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def read(backup_dir: Path) -> dict[str, Any] | None:
    """Read and parse the manifest, or None if missing/corrupt."""
    path = backup_dir / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def is_complete(backup_dir: Path) -> bool:
    """True if backup_dir has a manifest flagged complete."""
    man = read(backup_dir)
    return bool(man and man.get("complete"))


def validate(backup_dir: Path) -> tuple[bool, list[str]]:
    """Verify every file in the manifest against its recorded size + sha256.

    Returns (ok, issues). A missing manifest, an incomplete flag, a missing
    file, or a checksum mismatch each appends an issue.
    """
    man = read(backup_dir)
    if not man:
        return False, ["No manifest found — backup incomplete or missing"]

    issues: list[str] = []
    if not man.get("complete"):
        issues.append("manifest is marked incomplete")

    for entry in man.get("files", []):
        rel = entry.get("path", "")
        target = backup_dir / rel
        if not target.exists():
            issues.append(f"missing file: {rel}")
            continue
        if target.stat().st_size != entry.get("size"):
            issues.append(f"size mismatch: {rel}")
        elif sha256_file(target) != entry.get("sha256"):
            issues.append(f"sha256 mismatch (corrupt): {rel}")

    return (not issues), issues


def verify_native_zip(zip_path: Path) -> tuple[bool, str]:
    """Sanity-check a native XML export ZIP before trusting it.

    ok=False means the file is clearly not a usable export (not a ZIP / empty /
    corrupt). ok=True with a "WARNING:"-prefixed message means it is a valid ZIP
    but is missing the entries a space import expects.
    """
    if not zipfile.is_zipfile(zip_path):
        head = b""
        try:
            head = zip_path.read_bytes()[:80]
        except OSError:
            pass
        return False, (
            f"not a ZIP (starts with {head!r}) — likely an HTML error/login page "
            "or a truncated download, not a space export"
        )
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            bad = zf.testzip()
    except zipfile.BadZipFile as exc:
        return False, f"corrupt ZIP: {exc}"
    if bad is not None:
        return False, f"corrupt entry in ZIP: {bad}"
    if not names:
        return False, "ZIP is empty"

    basenames = {n.rsplit("/", 1)[-1] for n in names}
    missing = [m for m in _NATIVE_EXPORT_MARKERS if m not in basenames]
    if missing:
        return True, (
            f"WARNING: valid ZIP but missing expected entries {missing} among "
            f"{len(names)} entries — verify it imports before relying on it"
        )
    return True, f"valid native export ({len(names)} entries)"
