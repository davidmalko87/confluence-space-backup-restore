# utils.py — Shared utilities for Confluence Space Backup & Restore Tool
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""Shared helpers: logging, JSON I/O (incl. streaming writes), filename
sanitization, cross-version rmtree, storage-format text extraction, and
ASCII-safe console output that never crashes on a legacy Windows (cp1252)
console.
"""

import json
import logging
import os
import re
import shutil
import stat
import sys
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Callable, IO

LOGGER_NAME = "confluence_tool"

# Reconfigure the standard streams defensively so a stray non-ASCII byte in a
# page title or comment never raises UnicodeEncodeError on a legacy console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

def setup_logging(log_dir: str = ".", name: str = LOGGER_NAME) -> logging.Logger:
    """Configure dual logging: a DEBUG file handler + an INFO console handler.

    The DEBUG file log can capture truncated API response bodies (page text)
    for troubleshooting, so it MUST be gitignored and treated as sensitive.

    Args:
        log_dir: Directory for the log file (created if missing).
        name: Logger name.

    Returns:
        The configured logger (idempotent — repeat calls reuse handlers).
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"{name}_{timestamp}.log")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.debug("Log file: %s", log_file)
    return logger


# ----------------------------------------------------------------------
# Filenames / time
# ----------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Strip characters illegal in Windows/Linux filenames."""
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def utc_stamp() -> str:
    """Return a compact UTC timestamp suitable for directory names."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def format_size(num_bytes: int) -> str:
    """Render a byte count as a human-readable B/KB/MB/GB string."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


# ----------------------------------------------------------------------
# JSON I/O
# ----------------------------------------------------------------------

def load_json(path: str) -> Any:
    """Read and parse a JSON file (UTF-8)."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Any, path: str) -> None:
    """Write data to a JSON file with pretty formatting (creates dirs)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class StreamingJsonArray:
    """Append-as-you-go JSON array writer.

    Writes each item to disk the moment it arrives instead of buffering the
    whole collection in memory. This is the key defense against OOM on large
    spaces / small hosts: the caller keeps only lightweight references in RAM.

    Usage:
        with StreamingJsonArray(path) as out:
            for item in source:
                out.append(item)
        print(out.count)
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.count = 0
        self._first = True
        self._f: IO[str] | None = None

    def __enter__(self) -> "StreamingJsonArray":
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._f = open(self.path, "w", encoding="utf-8")
        self._f.write("[")
        return self

    def append(self, item: Any) -> None:
        """Serialize and write one item, preserving valid JSON array syntax."""
        assert self._f is not None, "StreamingJsonArray used outside context"
        self._f.write("\n" if self._first else ",\n")
        self._first = False
        text = json.dumps(item, ensure_ascii=False, indent=2)
        # Indent each line by two spaces so the array stays human-readable.
        self._f.write("\n".join("  " + line for line in text.splitlines()))
        self.count += 1

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._f is not None:
            self._f.write("\n]\n" if self.count else "]\n")
            self._f.close()
            self._f = None


# ----------------------------------------------------------------------
# Filesystem
# ----------------------------------------------------------------------

def force_rmtree(path: str) -> None:
    """Recursively delete a directory, handling read-only files on Windows.

    shutil.rmtree's error-callback keyword changed across versions: ``onexc``
    was added in Python 3.12 and ``onerror`` is removed there. Branch on the
    interpreter version so the tool runs cleanly on 3.10-3.13.
    """
    if not os.path.exists(path):
        return

    def _on_error(func: Callable[..., Any], target: str, _exc: Any) -> None:
        # Read-only files (common with Windows attachment dumps) reject unlink
        # until the write bit is restored; then retry the original operation.
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=lambda f, p, e: _on_error(f, p, e))
    else:
        shutil.rmtree(path, onerror=lambda f, p, e: _on_error(f, p, e))


def dir_size_bytes(path: str) -> int:
    """Return the total size in bytes of all files under a directory."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


# ----------------------------------------------------------------------
# Confluence storage-format helpers
# ----------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def storage_to_text(storage: str, limit: int = 200) -> str:
    """Reduce a Confluence storage-format (XHTML) body to a short text preview.

    This is a best-effort flattening for CSV/inspection only — it strips tags
    and macro markup; it is NOT a faithful renderer.

    Args:
        storage: Raw storage-format body.
        limit: Maximum characters to return (0 = no limit).

    Returns:
        Whitespace-collapsed plain text, truncated to ``limit`` chars.
    """
    if not storage:
        return ""
    text = _TAG_RE.sub(" ", storage)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    text = _WS_RE.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


# ----------------------------------------------------------------------
# ASCII-safe console output (optional `rich`, never required)
# ----------------------------------------------------------------------

try:
    from rich.console import Console

    _CON: "Console | None" = Console()
    _ERR: "Console | None" = Console(stderr=True)
    _HAVE_RICH = True
    _RICH_UNICODE = not _CON.legacy_windows
except ImportError:  # pragma: no cover - depends on environment
    _CON = _ERR = None
    _HAVE_RICH = _RICH_UNICODE = False


def section(title: str) -> None:
    """Print a section header (ASCII rule, never Unicode box-drawing)."""
    if _RICH_UNICODE and _CON is not None:
        _CON.rule(f"[steel_blue]{title}[/]", style="grey50")
    else:
        print(f"\n=== {title} ===")


def info(msg: str) -> None:
    """Print an informational line."""
    if _HAVE_RICH and _CON is not None:
        _CON.print(f"[grey62][INFO][/] {msg}")
    else:
        print(f"[INFO] {msg}")


def ok(msg: str) -> None:
    """Print a success line."""
    if _HAVE_RICH and _CON is not None:
        _CON.print(f"[sea_green3][OK][/] {msg}")
    else:
        print(f"[OK] {msg}")


def warn(msg: str) -> None:
    """Print a warning to stdout (a warning is not a failure)."""
    if _HAVE_RICH and _CON is not None:
        _CON.print(f"[gold3][WARN][/] {msg}")
    else:
        print(f"[WARN] {msg}")


def error(msg: str) -> None:
    """Print an error to stderr."""
    if _HAVE_RICH and _ERR is not None:
        _ERR.print(f"[indian_red][ERROR][/] {msg}")
    else:
        print(f"[ERROR] {msg}", file=sys.stderr)


def print_kv(rows: list[tuple[str, str]], title: str | None = None) -> None:
    """Print an aligned two-column key/value block (ASCII-safe, no borders)."""
    if title:
        print(title)
    width = max((len(k) for k, _ in rows), default=0)
    for key, value in rows:
        print(f"  {key.ljust(width)} : {value}")
