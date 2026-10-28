"""Validity checks (FR4): empty, corrupt and extension-mismatched files."""
from __future__ import annotations

import gzip
import json
import tarfile
import wave
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from .detection import KNOWN_EXTENSIONS, FileType, extension_of

_PILLOW_TYPES = {"jpg", "png", "gif", "bmp", "webp", "tiff", "ico", "psd"}
_ZIP_TYPES = {"zip", "docx", "xlsx", "pptx", "odt", "ods", "odp", "epub", "jar", "apk"}


@dataclass(frozen=True)
class Validation:
    valid: bool
    reason: str | None = None


OK = Validation(True)


def validate(path, ftype: FileType, *, size: int | None = None,
             check_mismatch: bool = True, deep_check_max_bytes: int = 200 * 2**20) -> Validation:
    path = Path(path)
    size = path.stat().st_size if size is None else size
    if size == 0 or ftype.name == "empty":
        return Validation(False, "empty: file is 0 bytes")
    if size <= deep_check_max_bytes:
        problem = _corruption(path, ftype)
        if problem:
            return Validation(False, f"corrupt: {problem}")
    ext = extension_of(path)
    if check_mismatch and ext and ext in KNOWN_EXTENSIONS and ext not in ftype.extensions:
        detected = "unrecognized data" if ftype.name == "unknown" else ftype.name
        return Validation(False, f"mismatch: extension is .{ext} but content is {detected}")
    return OK


def _corruption(path: Path, ftype: FileType) -> str | None:
    name = ftype.name
    try:
        if name in _PILLOW_TYPES:
            return _check_image(path)
        if name in _ZIP_TYPES:
            with zipfile.ZipFile(path) as zf:
                try:
                    bad = zf.testzip()
                except RuntimeError:  # encrypted entries: cannot verify, not corrupt
                    return None
            return f"archive member {bad!r} fails CRC check" if bad else None
        if name == "pdf":
            with open(path, "rb") as f:
                f.seek(max(0, path.stat().st_size - 2048))
                if b"%%EOF" not in f.read():
                    return "PDF has no end-of-file marker (truncated)"
        elif name == "gz":
            with gzip.open(path, "rb") as f:
                while f.read(2**20):
                    pass
        elif name == "tar":
            with tarfile.open(path) as tf:
                tf.getmembers()
        elif name == "wav":
            with wave.open(str(path), "rb") as w:
                w.getnframes()
        elif name == "json":
            with open(path, "rb") as f:
                json.loads(f.read().decode("utf-8-sig"))
    except zipfile.BadZipFile as e:
        return f"bad archive: {e}"
    except (OSError, EOFError, zlib.error, tarfile.TarError, wave.Error, ValueError) as e:
        return f"{name} data is damaged: {e}"
    return None


def _check_image(path: Path) -> str | None:
    try:
        from PIL import Image, ImageFile
    except ImportError:
        return None
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im.load()
    except Image.DecompressionBombError as e:
        return f"suspicious image: {e}"
    except Exception as e:  # Pillow raises many types for broken data
        return f"image data is damaged: {e}"
    return None
