import pytest

import samples
from sortsmart.core.detection import detect


@pytest.mark.parametrize("kind", sorted(samples.CATALOG))
def test_detects_every_supported_kind(tmp_path, kind):
    path = samples.write(tmp_path, kind)
    _, _, expected_type, expected_category = samples.CATALOG[kind]
    ftype = detect(path)
    assert ftype.name == expected_type
    assert ftype.category == expected_category


@pytest.mark.parametrize("kind", ["png", "jpg", "pdf", "mp4", "zip", "docx", "mp3", "exe"])
def test_detection_ignores_extension(tmp_path, kind):
    """Type comes from content: a file without extension or with a bogus one
    is still recognized."""
    _, _, expected, _ = samples.CATALOG[kind]
    for name in ("noext", "file.weird", "file.txt"):
        path = samples.write(tmp_path, kind, name=f"{kind}_{name}")
        assert detect(path).name == expected


def test_empty_file(tmp_path):
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    assert detect(p).name == "empty"


def test_unknown_binary(tmp_path):
    p = tmp_path / "blob.dat"
    p.write_bytes(bytes(range(256)) * 4)
    assert detect(p).name == "unknown"
    assert detect(p).category == "Others"


def test_text_variants(tmp_path):
    cases = {
        "page.unknownext": (b"<!DOCTYPE html><html></html>", "html"),
        "data.unknownext": (b'{"a": [1, 2]}', "json"),
        "feed.unknownext": (b'<?xml version="1.0"?><rss/>', "xml"),
        "utf16.txt": ("hello".encode("utf-16"), "txt"),
        "latin.txt": ("caf\xe9 cr\xe8me".encode("cp1252"), "txt"),
        "script.py": (b"print('hi')\n", "code"),
    }
    for name, (data, expected) in cases.items():
        p = tmp_path / name
        p.write_bytes(data)
        assert detect(p).name == expected, name


def test_structured_text_without_extension(tmp_path):
    cases = {
        "table": (b"id,name,price\n1,apple,0.5\n2,pear,0.7\n", "csv"),
        "semi": (b"a;b\n1;2\n3;4\n", "csv"),
        "tabs": (b"a\tb\tc\n1\t2\t3\n", "tsv"),
        "readme": (b"# Project\n\nSome words.\n\n- item\n", "md"),
        "prose": (b"Dear team,\nthe meeting moved to Friday.\nThanks\n", "txt"),
    }
    for name, (data, expected) in cases.items():
        p = tmp_path / name
        p.write_bytes(data)
        assert detect(p).name == expected, name


def test_generic_bin_extension_is_not_claimed(tmp_path):
    from sortsmart.core.validation import validate
    p = tmp_path / "firmware.bin"
    p.write_bytes(samples.mp4())
    assert validate(p, detect(p)).valid


def test_docx_named_zip_is_still_docx(tmp_path):
    p = tmp_path / "report.zip"
    p.write_bytes(samples.docx())
    assert detect(p).name == "docx"


def test_iso_media_disambiguation(tmp_path):
    p = tmp_path / "song.m4a"
    p.write_bytes(samples.mp4(b"isom"))  # generic brand, audio extension
    assert detect(p).name == "m4a"
    p2 = tmp_path / "clip.mp4"
    p2.write_bytes(samples.mp4(b"mp42"))
    assert detect(p2).name == "mp4"


def test_ole_container_uses_extension_to_disambiguate(tmp_path):
    for ext, expected in (("doc", "doc"), ("xls", "xls"), ("ppt", "ppt"), ("bin", "doc")):
        p = tmp_path / f"legacy.{ext}"
        p.write_bytes(samples.ole())
        assert detect(p).name == expected
