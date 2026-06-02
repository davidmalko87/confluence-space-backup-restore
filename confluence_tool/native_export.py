# native_export.py — OPTIONAL best-effort native XML space export
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""Trigger a native Confluence XML space export and download the resulting ZIP.

WARNING — UNDOCUMENTED & UNVERIFIED PATH
========================================
Confluence Cloud has NO supported public REST API for space export
(feature request CONFCLOUD-40457, open for years). This module drives the same
*undocumented* `.action` endpoints the Confluence UI uses, which Atlassian can
change or remove without notice. It is therefore:
  * OFF by default (enable with NATIVE_EXPORT=true / --native-export),
  * BEST-EFFORT (any failure is logged and never aborts the REST backup),
  * UNVERIFIED in this build — the exact request/response shapes are
    tenant-dependent and MUST be confirmed on a NON-PROD site (Phase 4).

The produced ZIP is a high-fidelity DR artifact you import MANUALLY via the
Confluence UI ("Import a space"); this tool never imports it.

Flow (per Atlassian community findings):
  1. GET  /spaces/exportspacexml.action?key=KEY        -> page carrying atl_token
  2. POST /spaces/doexportspace.action?key=KEY          -> starts the export task
  3. GET  /rest/internals/1.0/io/export/{id}            -> poll until complete
  4. GET  <result download link>                        -> stream the ZIP to disk
"""

import logging
import re
import time
from pathlib import Path
from typing import Any

from confluence_tool.api_client import ConfluenceClient
from confluence_tool.config import ConfluenceConfig
from confluence_tool import manifest
from confluence_tool.utils import sanitize_filename

logger = logging.getLogger("confluence_tool")

# The .action endpoints are WebUI (not REST), so unlike the rest of the tool they
# may expect a browser-like User-Agent (Atlassian serves HTML to non-browser UAs
# on these). The session UA is deliberately non-browser (for XSRF on uploads), so
# these requests override it locally.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_ATL_TOKEN_RE = re.compile(r'(?:name="atl_token"\s+(?:value|content)="|ajs-atl-token"\s+content=")([^"]+)')
_EXPORT_ID_RE = re.compile(r"export/(\d+)")


def export_space(
    client: ConfluenceClient,
    config: ConfluenceConfig,
    space_key: str,
    backup_dir: str,
) -> dict[str, Any]:
    """Attempt a native XML export. Returns a manifest-ready native_export dict.

    Never raises: the caller treats native export as best-effort. On failure the
    returned dict has ``present: False`` and an ``error`` string.
    """
    session = client.session
    base = client.base_url
    timeout = (10, 60)

    try:
        atl_token = _fetch_atl_token(session, base, space_key, timeout)
        export_id = _trigger_export(session, base, space_key, atl_token, timeout)
        if not export_id:
            return {"present": False, "error": "could not determine export task id"}

        download_link = _poll_until_done(
            session, base, export_id, config.native_export_timeout
        )
        if not download_link:
            return {"present": False, "error": "export did not complete in time"}

        dest = Path(backup_dir) / "native" / f"{sanitize_filename(space_key)}_native.xml.zip"
        if not client.download_file(download_link, str(dest)):
            return {"present": False, "error": "failed to download export file"}

        ok, msg = manifest.verify_native_zip(dest)
        logger.info("Native export check: %s", msg)
        return {
            "present": True,
            "file": f"native/{dest.name}",
            "sha256": manifest.sha256_file(dest),
            "zip_valid": ok,
            "note": msg,
        }
    except Exception as exc:  # noqa: BLE001 - undocumented path; never fatal
        logger.warning("Native export error (non-fatal): %s", exc)
        return {"present": False, "error": str(exc)}


def _fetch_atl_token(session: Any, base: str, space_key: str, timeout: Any) -> str | None:
    """Fetch the export form and parse the CSRF atl_token if present."""
    url = f"{base}/spaces/exportspacexml.action?key={space_key}"
    resp = session.get(url, timeout=timeout, headers={"User-Agent": _BROWSER_UA})
    if resp.status_code != 200:
        logger.debug("Export form GET -> %d", resp.status_code)
        return None
    match = _ATL_TOKEN_RE.search(resp.text)
    return match.group(1) if match else None


def _trigger_export(
    session: Any, base: str, space_key: str, atl_token: str | None, timeout: Any
) -> str | None:
    """POST the export request and try to recover the export task id."""
    url = f"{base}/spaces/doexportspace.action?key={space_key}"
    data: dict[str, str] = {
        "exportType": "TYPE_XML",
        "contentOption": "all",
        "includeComments": "true",
        "confirm": "Export",
    }
    if atl_token:
        data["atl_token"] = atl_token
    resp = session.post(
        url, data=data,
        headers={"X-Atlassian-Token": "no-check", "User-Agent": _BROWSER_UA},
        timeout=timeout, allow_redirects=True,
    )
    # The task id may surface in the body, the final redirect URL, or a header.
    haystack = " ".join([resp.text or "", resp.url or "", resp.headers.get("Location", "")])
    match = _EXPORT_ID_RE.search(haystack)
    return match.group(1) if match else None


def _poll_until_done(
    session: Any, base: str, export_id: str, timeout_s: int
) -> str | None:
    """Poll the export progress endpoint until complete; return the download link."""
    url = f"{base}/rest/internals/1.0/io/export/{export_id}"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = session.get(url, timeout=(10, 60), headers={"User-Agent": _BROWSER_UA})
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if data.get("complete") or data.get("successful"):
            # The download link key varies by tenant; try the common shapes.
            return (
                data.get("result")
                or (data.get("entity") or {}).get("downloadPath")
                or data.get("downloadPath")
            )
        pct = data.get("percentageComplete")
        if pct is not None:
            logger.info("  native export: %s%% complete", pct)
        time.sleep(5)
    return None
