import samples
from sortsmart.core.detection import detect
from sortsmart.core.validation import validate


def check(path):
    return validate(path, detect(path))


def test_valid_samples_pass(tmp_path):
    for kind in samples.CATALOG:
        p = samples.write(tmp_path, kind)
        v = check(p)
        assert v.valid, f"{kind}: {v.reason}"


def test_zero_byte_file(tmp_path):
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"")
    v = check(p)
    assert not v.valid and v.reason.startswith("empty")


def test_truncated_png_is_corrupt(tmp_path):
    from PIL import Image
    p = tmp_path / "big.png"
    Image.effect_noise((200, 200), 64).save(p)
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 2])
    v = check(p)
    assert not v.valid and v.reason.startswith("corrupt"), v.reason


def test_truncated_jpeg_is_corrupt(tmp_path):
    from PIL import Image
    p = tmp_path / "photo.jpg"
    Image.effect_noise((200, 200), 64).convert("RGB").save(p, "JPEG")
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 2])
    v = check(p)
    assert not v.valid and v.reason.startswith("corrupt")


def test_truncated_pdf_is_corrupt(tmp_path):
    p = tmp_path / "doc.pdf"
    data = samples.pdf()
    p.write_bytes(data[: data.rfind(b"%%EOF")])
    v = check(p)
    assert not v.valid and "truncated" in v.reason


def test_damaged_zip_is_corrupt(tmp_path):
    p = tmp_path / "archive.zip"
    data = bytearray(samples.zip_archive())
    data[40:60] = b"\xff" * 20  # stomp on compressed data -> CRC failure
    p.write_bytes(bytes(data))
    v = check(p)
    assert not v.valid and v.reason.startswith("corrupt")


def test_truncated_docx_is_corrupt(tmp_path):
    p = tmp_path / "report.docx"
    data = samples.docx()
    p.write_bytes(data[: len(data) - 30])
    v = check(p)
    assert not v.valid
    assert v.reason.startswith(("corrupt", "mismatch"))


def test_truncated_gzip_and_json(tmp_path):
    g = tmp_path / "x.gz"
    g.write_bytes(samples.gz_archive()[:-10])
    assert not check(g).valid
    j = tmp_path / "x.json"
    j.write_bytes(b'{"a": [1, 2')
    assert not check(j).valid


def test_extension_mismatch(tmp_path):
    p = tmp_path / "holiday.jpg"
    p.write_bytes(samples.CATALOG["png"][0](1))
    v = check(p)
    assert not v.valid
    assert v.reason == "mismatch: extension is .jpg but content is png"


def test_executable_disguised_as_pdf(tmp_path):
    p = tmp_path / "invoice.pdf"
    p.write_bytes(samples.exe())
    v = check(p)
    assert not v.valid and "content is exe" in v.reason


def test_compatible_extensions_are_not_mismatches(tmp_path):
    cases = [("clip.mov", samples.mp4()), ("clip.mp4", samples.mov()),
             ("photo.jpeg", samples.CATALOG["jpg"][0](0)), ("scan.tif", samples.CATALOG["tiff"][0](0)),
             ("report.docm", samples.docx()), ("notes.log", b"log line\n")]
    for name, data in cases:
        p = tmp_path / name
        p.write_bytes(data)
        assert check(p).valid, name


def test_unknown_extension_is_never_a_mismatch(tmp_path):
    p = tmp_path / "picture.myformat"
    p.write_bytes(samples.CATALOG["png"][0](0))
    assert check(p).valid


def test_mismatch_check_can_be_disabled(tmp_path):
    p = tmp_path / "holiday.jpg"
    p.write_bytes(samples.CATALOG["png"][0](1))
    assert validate(p, detect(p), check_mismatch=False).valid
