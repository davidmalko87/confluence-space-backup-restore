# Tests for confluence_tool.utils
import json

from confluence_tool.utils import (
    StreamingJsonArray,
    format_size,
    sanitize_filename,
    storage_to_text,
)


def test_format_size():
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1572864) == "1.5 MB"
    assert format_size(1073741824) == "1.0 GB"


def test_sanitize_filename():
    # replaces each of \ / : * ? " < > | with an underscore
    assert sanitize_filename('a/b:c*?"<>|d') == "a_b_c______d"
    assert sanitize_filename("normal.txt") == "normal.txt"
    assert sanitize_filename(r"a\b") == "a_b"


def test_storage_to_text_strips_tags_and_entities():
    assert storage_to_text("<p>Hello <b>world</b></p>") == "Hello world"
    assert storage_to_text("a &amp; b &lt;c&gt;") == "a & b <c>"
    assert storage_to_text("") == ""


def test_storage_to_text_truncates():
    out = storage_to_text("<p>" + "x" * 500 + "</p>", limit=20)
    assert len(out) <= 20
    assert out.endswith("…")


def test_streaming_json_array_round_trips(tmp_path):
    path = tmp_path / "items.json"
    with StreamingJsonArray(str(path)) as out:
        out.append({"id": "1", "title": "a"})
        out.append({"id": "2", "title": "b"})
    assert out.count == 2
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == [{"id": "1", "title": "a"}, {"id": "2", "title": "b"}]


def test_streaming_json_array_empty_is_valid(tmp_path):
    path = tmp_path / "empty.json"
    with StreamingJsonArray(str(path)):
        pass
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_streaming_json_array_preserves_unicode(tmp_path):
    path = tmp_path / "u.json"
    with StreamingJsonArray(str(path)) as out:
        out.append({"title": "Привіт ✓ café"})
    assert json.loads(path.read_text(encoding="utf-8"))[0]["title"] == "Привіт ✓ café"
