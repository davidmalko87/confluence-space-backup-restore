# macros.py — Remap content-ID references in page bodies after restore
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""On restore, every page/blog post gets a NEW numeric content ID. Any body
that references an OLD ID (links, include/excerpt-include macros, ID-rooted
children-display / page-tree) would break. This module rewrites those ID
references from the tool's old->new map, in a second pass once all new IDs exist.

Scope & honesty: the robust, safe target is the ``ri:content-id`` attribute used
by ``<ri:page>`` / ``<ri:blog-post>`` references (covers the large majority of
ID-based links and include macros). Numeric-only macro parameters (e.g. a raw
``<ac:parameter ac:name="pageId">123</ac:parameter>``) are NOT auto-rewritten —
blindly replacing bare numbers risks corrupting unrelated content — but their
presence is reported so the operator knows to check those macros.
"""

import json
import re
from typing import Any

# ri:content-id="12345" inside <ri:page>/<ri:blog-post> references.
_RI_CONTENT_ID_RE = re.compile(r'(ri:content-id=")(\d+)(")')

# Structured-macro names that commonly embed a page/content ID and may need a
# manual look if an unmapped ID remains. Used for reporting only.
ID_BEARING_MACROS = (
    "include",
    "excerpt-include",
    "children",
    "pagetree",
    "detailssummary",
)
_MACRO_NAME_RE = re.compile(r'ac:name="([^"]+)"')


def remap_storage(storage: str, id_map: dict[str, str]) -> tuple[str, set[str]]:
    """Rewrite ri:content-id references in a storage-format body.

    Args:
        storage: The storage-format (XHTML) body.
        id_map: old content ID -> new content ID (strings).

    Returns:
        (new_storage, unmapped) where ``unmapped`` is the set of old IDs that
        were referenced but have no mapping (their references are left as-is and
        will be broken until the referenced content is also restored).
    """
    if not storage:
        return storage, set()

    unmapped: set[str] = set()

    def _sub(match: re.Match[str]) -> str:
        old_id = match.group(2)
        new_id = id_map.get(old_id)
        if new_id is None:
            unmapped.add(old_id)
            return match.group(0)
        return f"{match.group(1)}{new_id}{match.group(3)}"

    return _RI_CONTENT_ID_RE.sub(_sub, storage), unmapped


def remap_adf(adf: str, id_map: dict[str, str]) -> tuple[str, set[str]]:
    """Best-effort ID remap for an atlas_doc_format (ADF JSON) body.

    Walks the JSON and replaces string values under common content-ID keys
    (``contentId``, ``content-id``) when present in the map. ADF round-trips are
    inherently lossier for legacy macros; storage format is recommended.
    """
    if not adf:
        return adf, set()
    try:
        doc = json.loads(adf)
    except (ValueError, TypeError):
        return adf, set()

    unmapped: set[str] = set()
    id_keys = {"contentId", "content-id"}

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            new: dict[str, Any] = {}
            for key, value in node.items():
                if key in id_keys and isinstance(value, str) and value.isdigit():
                    mapped = id_map.get(value)
                    if mapped is None:
                        unmapped.add(value)
                        new[key] = value
                    else:
                        new[key] = mapped
                else:
                    new[key] = _walk(value)
            return new
        if isinstance(node, list):
            return [_walk(item) for item in node]
        return node

    return json.dumps(_walk(doc), ensure_ascii=False), unmapped


def remap_body(
    value: str,
    representation: str,
    id_map: dict[str, str],
) -> tuple[str, set[str]]:
    """Dispatch ID remapping by body representation (storage or ADF)."""
    if representation == "atlas_doc_format":
        return remap_adf(value, id_map)
    return remap_storage(value, id_map)


def body_has_content_ids(value: str, representation: str) -> bool:
    """True if a body references any content ID (so a second-pass PUT is needed)."""
    if not value:
        return False
    if representation == "atlas_doc_format":
        return '"contentId"' in value or '"content-id"' in value
    return bool(_RI_CONTENT_ID_RE.search(value))


def scan_id_macros(storage: str) -> set[str]:
    """Return the set of ID-bearing macro names present in a storage body.

    Reporting aid: lets restore warn that a page uses e.g. include/pagetree
    macros, which the operator may want to verify after an ID remap.
    """
    if not storage:
        return set()
    found: set[str] = set()
    for name in _MACRO_NAME_RE.findall(storage):
        if name in ID_BEARING_MACROS:
            found.add(name)
    return found
