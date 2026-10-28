"""Best-effort text extraction so detectors can look inside documents."""
from __future__ import annotations

import re
import zipfile
import zlib
from pathlib import Path

MAX_TEXT = 1_000_000
MAX_READ = 20 * 2**20


def extract_text(path, type_name: str, is_text: bool) -> str:
    path = Path(path)
    try:
        if is_text:
            with open(path, "rb") as f:
                return f.read(MAX_TEXT).decode("utf-8", errors="replace")
        if type_name == "pdf":
            return _pdf_text(path)[:MAX_TEXT]
        if type_name in ("docx", "pptx", "xlsx", "odt", "odp", "ods"):
            return _office_text(path)[:MAX_TEXT]
    except Exception:
        return ""
    return ""


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # optional, best quality
        reader = PdfReader(str(path))
        text = " ".join((page.extract_text() or "") for page in reader.pages[:50])
        if text.strip():
            return text
    except Exception:
        pass
    with open(path, "rb") as f:
        data = f.read(MAX_READ)
    chunks = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        chunks.append(raw)
    strings = [s for c in (chunks or [data]) for s in re.findall(rb"\(((?:\\.|[^\\)])*)\)", c)]
    return " ".join(s.decode("latin-1") for s in strings)


def _office_text(path: Path) -> str:
    parts = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.endswith(".xml") and name.startswith(
                    ("word/document", "ppt/slides/slide", "xl/sharedStrings", "content.xml")):
                xml = zf.read(name).decode("utf-8", errors="replace")
                parts.append(re.sub(r"<[^>]+>", " ", xml))
    return re.sub(r"\s+", " ", " ".join(parts))
