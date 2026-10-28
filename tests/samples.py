"""Builds small but genuine sample files of every supported kind."""
from __future__ import annotations

import gzip
import io
import json
import struct
import tarfile
import wave
import zipfile
from pathlib import Path

from PIL import Image


def _image(fmt, color=(200, 30, 30), size=(16, 16), mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format=fmt)
    return buf.getvalue()


def pdf(text="Hello from SortSmart"):
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def _zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def docx(text="Quarterly report"):
    return _zip({"[Content_Types].xml": "<Types/>",
                 "word/document.xml": f"<w:document><w:body><w:t>{text}</w:t></w:body></w:document>"})


def xlsx():
    return _zip({"[Content_Types].xml": "<Types/>", "xl/workbook.xml": "<workbook/>"})


def pptx():
    return _zip({"[Content_Types].xml": "<Types/>", "ppt/presentation.xml": "<p/>"})


def epub():
    return _zip({"mimetype": "application/epub+zip", "META-INF/container.xml": "<c/>"})


def odt():
    return _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": "<x/>"})


def zip_archive(seed="a"):
    return _zip({"readme.txt": f"archive {seed}", "data/values.csv": "a,b\n1,2\n"})


def wav(seconds=0.05):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buf.getvalue()


def mp3():
    return b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x64" + b"\x00" * 400


def flac():
    return b"fLaC\x00\x00\x00\x22" + b"\x00" * 200


def ogg():
    return b"OggS\x00\x02" + b"\x00" * 20 + b"\x01vorbis" + b"\x00" * 100


def mp4(brand=b"isom"):
    return struct.pack(">I", 24) + b"ftyp" + brand + b"\x00\x00\x02\x00" + b"isomiso2" \
        + struct.pack(">I", 8) + b"free" + b"\x00" * 300


def mov():
    return mp4(b"qt  ")


def m4a():
    return mp4(b"M4A ")


def avi():
    return b"RIFF" + struct.pack("<I", 300) + b"AVI LIST" + b"\x00" * 300


def mkv():
    return b"\x1aE\xdf\xa3\x9fB\x86\x81\x01B\xf7\x81\x01B\xf2\x81\x04B\xf3\x81\x08B\x82\x88matroska" + b"\x00" * 200


def webm():
    return b"\x1aE\xdf\xa3\x9fB\x86\x81\x01B\xf7\x81\x01B\xf2\x81\x04B\xf3\x81\x08B\x82\x84webm" + b"\x00" * 200


def gz_archive(text="compressed"):
    return gzip.compress(text.encode() * 20)


def tar_archive():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        data = b"inside the tarball"
        info = tarfile.TarInfo("file.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def seven_z():
    return b"7z\xbc\xaf\x27\x1c\x00\x04" + b"\x00" * 100


def rar():
    return b"Rar!\x1a\x07\x01\x00" + b"\x00" * 100


def exe():
    return b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 120 + b"This program cannot be run in DOS mode"


def rtf():
    return rb"{\rtf1\ansi Hello RTF}"


def ole():
    return bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 504


def svg():
    return b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"></svg>'


# name -> (builder, extension, expected type, expected category)
CATALOG = {
    "png": (lambda s: _image("PNG", (s % 256, 10, 10)), "png", "png", "Images"),
    "jpg": (lambda s: _image("JPEG", (s % 256, 99, 10)), "jpg", "jpg", "Images"),
    "gif": (lambda s: _image("GIF", (s % 256, 10, 99)), "gif", "gif", "Images"),
    "bmp": (lambda s: _image("BMP", (s % 256, 50, 50)), "bmp", "bmp", "Images"),
    "webp": (lambda s: _image("WEBP", (s % 256, 1, 1)), "webp", "webp", "Images"),
    "tiff": (lambda s: _image("TIFF", (s % 256, 2, 2)), "tiff", "tiff", "Images"),
    "ico": (lambda s: _image("ICO", (s % 256, 3, 3)), "ico", "ico", "Images"),
    "svg": (lambda s: svg().replace(b'width="4"', f'width="{s}"'.encode()), "svg", "svg", "Images"),
    "mp4": (lambda s: mp4() + bytes([s % 256]) * 8, "mp4", "mp4", "Videos"),
    "mov": (lambda s: mov() + bytes([s % 256]) * 8, "mov", "mov", "Videos"),
    "avi": (lambda s: avi() + bytes([s % 256]) * 8, "avi", "avi", "Videos"),
    "mkv": (lambda s: mkv() + bytes([s % 256]) * 8, "mkv", "mkv", "Videos"),
    "webm": (lambda s: webm() + bytes([s % 256]) * 8, "webm", "webm", "Videos"),
    "mp3": (lambda s: mp3() + bytes([s % 256]) * 8, "mp3", "mp3", "Audio"),
    "wav": (lambda s: wav(0.01 + (s % 50) / 1000), "wav", "wav", "Audio"),
    "flac": (lambda s: flac() + bytes([s % 256]) * 8, "flac", "flac", "Audio"),
    "ogg": (lambda s: ogg() + bytes([s % 256]) * 8, "ogg", "ogg", "Audio"),
    "m4a": (lambda s: m4a() + bytes([s % 256]) * 8, "m4a", "m4a", "Audio"),
    "pdf": (lambda s: pdf(f"document {s}"), "pdf", "pdf", "Documents"),
    "docx": (lambda s: docx(f"report {s}"), "docx", "docx", "Documents"),
    "xlsx": (lambda s: _zip({"[Content_Types].xml": f"<T n='{s}'/>", "xl/w.xml": "<w/>"}), "xlsx", "xlsx", "Documents"),
    "pptx": (lambda s: _zip({"[Content_Types].xml": f"<T n='{s}'/>", "ppt/p.xml": "<p/>"}), "pptx", "pptx", "Documents"),
    "epub": (lambda s: _zip({"mimetype": "application/epub+zip", "c.xml": f"<c n='{s}'/>"}), "epub", "epub", "Documents"),
    "doc": (lambda s: ole() + bytes([s % 256]) * 8, "doc", "doc", "Documents"),
    "rtf": (lambda s: rtf() + str(s).encode(), "rtf", "rtf", "Documents"),
    "txt": (lambda s: f"plain text note number {s}\n".encode(), "txt", "txt", "Documents"),
    "csv": (lambda s: f"id,value\n{s},{s * 2}\n".encode(), "csv", "csv", "Documents"),
    "json": (lambda s: json.dumps({"n": s}).encode(), "json", "json", "Documents"),
    "html": (lambda s: f"<!doctype html><html><body>{s}</body></html>".encode(), "html", "html", "Documents"),
    "md": (lambda s: f"# Title {s}\n\ntext".encode(), "md", "md", "Documents"),
    "zip": (lambda s: zip_archive(str(s)), "zip", "zip", "Archives"),
    "gz": (lambda s: gz_archive(f"payload {s}"), "gz", "gz", "Archives"),
    "tar": (lambda s: tar_archive() + b"\x00" * 512 * (1 + s % 3), "tar", "tar", "Archives"),
    "7z": (lambda s: seven_z() + bytes([s % 256]) * 8, "7z", "7z", "Archives"),
    "rar": (lambda s: rar() + bytes([s % 256]) * 8, "rar", "rar", "Archives"),
    "exe": (lambda s: exe() + bytes([s % 256]) * 8, "exe", "exe", "Others"),
}


def write(folder: Path, kind: str, name: str | None = None, seed: int = 0) -> Path:
    builder, ext, _, _ = CATALOG[kind]
    path = Path(folder) / (name or f"{kind}_{seed}.{ext}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(builder(seed))
    return path
