# Tests for confluence_tool.progress.ProgressTracker
from confluence_tool.progress import ProgressTracker


def test_id_maps_and_combined(tmp_path):
    p = ProgressTracker(str(tmp_path))
    p.map_id("pages", "1", "1001")
    p.map_id("blogposts", "2", "2002")
    assert p.get_new_id("pages", "1") == "1001"
    assert p.is_mapped("pages", "1")
    assert not p.is_mapped("pages", "9")
    combined = p.combined_content_map()
    assert combined == {"1": "1001", "2": "2002"}


def test_phase_and_item_tracking(tmp_path):
    p = ProgressTracker(str(tmp_path))
    assert not p.is_phase_complete("pages")
    p.mark_phase_complete("pages")
    assert p.is_phase_complete("pages")
    assert not p.is_item_done("attachments", "a1")
    p.mark_item_done("attachments", "a1")
    assert p.is_item_done("attachments", "a1")


def test_user_cache(tmp_path):
    p = ProgressTracker(str(tmp_path))
    found, val = p.get_cached_user("acct1")
    assert not found and val is None
    p.cache_user("acct1", "Jane Doe")
    found, val = p.get_cached_user("acct1")
    assert found and val == "Jane Doe"
    # caching a None result is remembered (user does not exist)
    p.cache_user("acct2", None)
    found, val = p.get_cached_user("acct2")
    assert found and val is None


def test_state_persists_to_disk_and_reloads(tmp_path):
    p1 = ProgressTracker(str(tmp_path))
    p1.map_id("pages", "5", "500")
    p1.mark_phase_complete("space")
    p1.mark_item_done("comments", "c1")
    # a fresh tracker on the same dir reloads persisted state
    p2 = ProgressTracker(str(tmp_path))
    assert p2.get_new_id("pages", "5") == "500"
    assert p2.is_phase_complete("space")
    assert p2.is_item_done("comments", "c1")


def test_dry_run_writes_nothing(tmp_path):
    p = ProgressTracker(str(tmp_path), dry_run=True)
    p.map_id("pages", "1", "1001")
    p.mark_phase_complete("space")
    # nothing persisted in dry-run
    assert not (tmp_path / "id_maps.json").exists()
    assert not (tmp_path / "restore_progress.json").exists()
