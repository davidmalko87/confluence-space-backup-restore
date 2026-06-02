# Tests for confluence_tool.manifest
import zipfile
from pathlib import Path

from confluence_tool import manifest


def _make_backup(tmp_path: Path) -> Path:
    (tmp_path / "pages.json").write_text('[{"id":"1"}]', encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.bin").write_bytes(b"hello")
    return tmp_path


def test_build_write_read_validate_clean(tmp_path):
    bdir = _make_backup(tmp_path)
    man = manifest.build(bdir, "DEMO", tool_version="1.0.0", counts={"pages": 1})
    manifest.write(man, bdir)
    assert manifest.is_complete(bdir)
    ok, issues = manifest.validate(bdir)
    assert ok and issues == []
    # the manifest indexes both files, not itself
    paths = {f["path"] for f in man["files"]}
    assert paths == {"pages.json", "sub/a.bin"}


def test_validate_detects_size_change(tmp_path):
    bdir = _make_backup(tmp_path)
    manifest.write(manifest.build(bdir, "DEMO", tool_version="1.0.0"), bdir)
    (bdir / "pages.json").write_text('[{"id":"1"},{"id":"2"}]', encoding="utf-8")
    ok, issues = manifest.validate(bdir)
    assert not ok
    assert any("size" in i for i in issues)


def test_validate_detects_sha256_tamper(tmp_path):
    bdir = _make_backup(tmp_path)
    manifest.write(manifest.build(bdir, "DEMO", tool_version="1.0.0"), bdir)
    # same byte length, different content -> must be caught by sha256, not size
    (bdir / "pages.json").write_text('[{"id":"9"}]', encoding="utf-8")
    ok, issues = manifest.validate(bdir)
    assert not ok
    assert any("sha256" in i for i in issues)


def test_validate_missing_manifest(tmp_path):
    ok, issues = manifest.validate(tmp_path)
    assert not ok
    assert any("No manifest" in i for i in issues)


def test_verify_native_zip_rejects_non_zip(tmp_path):
    f = tmp_path / "x.zip"
    f.write_text("<html>401</html>", encoding="utf-8")
    ok, msg = manifest.verify_native_zip(f)
    assert not ok and "not a ZIP" in msg


def test_verify_native_zip_warns_on_missing_markers(tmp_path):
    f = tmp_path / "x.zip"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("random.txt", "data")
    ok, msg = manifest.verify_native_zip(f)
    assert ok and msg.startswith("WARNING:")


def test_verify_native_zip_accepts_real_export(tmp_path):
    f = tmp_path / "x.zip"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("entities.xml", "<x/>")
        zf.writestr("exportDescriptor.properties", "k=v")
    ok, msg = manifest.verify_native_zip(f)
    assert ok and "valid native export" in msg
