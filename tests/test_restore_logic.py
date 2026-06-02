# Tests for pure restore logic (no network)
from confluence_tool.restore import RestoreManager, _restriction_payload


def test_creation_order_parent_before_child():
    pages = [
        {"id": "3", "parentId": "2"},
        {"id": "2", "parentId": "1"},
        {"id": "1", "parentId": None},
        {"id": "4", "parentId": "1"},
    ]
    order = [p["id"] for p in RestoreManager._creation_order(pages)]
    assert order.index("1") < order.index("2") < order.index("3")
    assert order.index("1") < order.index("4")
    assert len(order) == 4


def test_creation_order_orphan_parent_treated_as_root():
    # parentId points outside the set -> the page is still created (as a root)
    pages = [{"id": "10", "parentId": "999"}]
    order = [p["id"] for p in RestoreManager._creation_order(pages)]
    assert order == ["10"]


def test_restriction_payload_extracts_users_and_groups():
    by_op = {
        "read": {"restrictions": {"user": {"results": [{"accountId": "abc"}]},
                                  "group": {"results": []}}},
        "update": {"restrictions": {"user": {"results": []},
                                    "group": {"results": [{"name": "devs"}]}}},
    }
    payload = _restriction_payload(by_op)
    ops = {p["operation"] for p in payload}
    assert ops == {"read", "update"}
    read = next(p for p in payload if p["operation"] == "read")
    assert read["restrictions"]["user"] == [{"type": "known", "accountId": "abc"}]


def test_restriction_payload_empty():
    assert _restriction_payload({}) == []
    assert _restriction_payload({"read": {"restrictions": {}}}) == []


def test_created_at_prefers_top_level():
    assert RestoreManager._created_at({"createdAt": "2026-01-01T00:00:00Z"}) == \
        "2026-01-01T00:00:00Z"


def test_created_at_falls_back_to_version():
    # comments carry the date under version.createdAt, not top-level
    c = {"version": {"createdAt": "2026-02-02T00:00:00Z"}}
    assert RestoreManager._created_at(c) == "2026-02-02T00:00:00Z"


def test_created_at_missing_is_none():
    assert RestoreManager._created_at({}) is None
    assert RestoreManager._created_at({"version": {}}) is None
