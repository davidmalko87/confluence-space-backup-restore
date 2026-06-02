# Tests for confluence_tool.macros — the two-pass ID remap
from confluence_tool.macros import (
    body_has_content_ids,
    remap_adf,
    remap_body,
    remap_storage,
    scan_id_macros,
)

STORAGE = (
    '<p>see <ac:link><ri:page ri:content-id="100"/></ac:link> and '
    '<ac:structured-macro ac:name="include"><ri:page ri:content-id="200"/>'
    '</ac:structured-macro></p>'
)


def test_body_has_content_ids():
    assert body_has_content_ids(STORAGE, "storage")
    assert not body_has_content_ids("<p>no refs</p>", "storage")
    assert not body_has_content_ids("", "storage")


def test_remap_storage_rewrites_mapped_ids():
    new, unmapped = remap_storage(STORAGE, {"100": "999", "200": "888"})
    assert 'ri:content-id="999"' in new
    assert 'ri:content-id="888"' in new
    assert unmapped == set()


def test_remap_storage_leaves_unmapped_and_reports_them():
    new, unmapped = remap_storage(STORAGE, {"100": "999"})
    assert 'ri:content-id="999"' in new
    assert 'ri:content-id="200"' in new  # unchanged
    assert unmapped == {"200"}


def test_remap_storage_no_ids_is_noop():
    body = "<p>plain</p>"
    new, unmapped = remap_storage(body, {"1": "2"})
    assert new == body and unmapped == set()


def test_scan_id_macros():
    assert "include" in scan_id_macros(STORAGE)
    assert scan_id_macros("<p>nothing</p>") == set()


def test_remap_body_dispatches_storage():
    new, unmapped = remap_body(STORAGE, "storage", {"100": "1", "200": "2"})
    assert 'ri:content-id="1"' in new and unmapped == set()


def test_remap_adf_rewrites_content_id():
    adf = '{"type":"doc","content":[{"type":"inlineCard","attrs":{"contentId":"100"}}]}'
    new, unmapped = remap_adf(adf, {"100": "555"})
    assert '"555"' in new and unmapped == set()


def test_remap_adf_reports_unmapped():
    adf = '{"attrs":{"contentId":"777"}}'
    new, unmapped = remap_adf(adf, {"100": "1"})
    assert unmapped == {"777"}


def test_remap_adf_tolerates_bad_json():
    new, unmapped = remap_adf("not json", {"1": "2"})
    assert new == "not json" and unmapped == set()


# --- ri:space-key remap (cross-space links into the source space) ---

LINK_SRC = '<ac:link><ri:page ri:content-title="B" ri:space-key="SRC" /></ac:link>'
LINK_OTHER = '<ac:link><ri:page ri:content-title="X" ri:space-key="OTHER" /></ac:link>'


def test_remap_storage_rewrites_source_space_key():
    new, _ = remap_storage(LINK_SRC, {}, {"SRC": "DST"})
    assert 'ri:space-key="DST"' in new
    assert 'ri:space-key="SRC"' not in new


def test_remap_storage_leaves_other_space_keys_untouched():
    new, _ = remap_storage(LINK_OTHER, {}, {"SRC": "DST"})
    assert 'ri:space-key="OTHER"' in new  # unchanged


def test_remap_storage_no_space_map_is_noop():
    new, _ = remap_storage(LINK_SRC, {})
    assert new == LINK_SRC


def test_remap_body_threads_space_key_map():
    new, _ = remap_body(LINK_SRC, "storage", {}, {"SRC": "DST"})
    assert 'ri:space-key="DST"' in new
