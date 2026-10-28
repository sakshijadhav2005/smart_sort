"""Content-based file type detection (magic bytes), FR1.

The extension is only used to break ties between formats that share a
signature (e.g. .doc vs .xls inside an OLE container). It never decides the
type on its own.
"""
from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

HEADER_SIZE = 8192

IMAGES, VIDEOS, AUDIO, DOCUMENTS, ARCHIVES, OTHERS = (
    "Images", "Videos", "Audio", "Documents", "Archives", "Others",
)
CATEGORIES = (IMAGES, VIDEOS, AUDIO, DOCUMENTS, ARCHIVES, OTHERS)


@dataclass(frozen=True)
class FileType:
    name: str
    mime: str
    category: str
    extensions: tuple = ()
    is_text: bool = False

    def __str__(self) -> str:
        return self.name


TYPES: dict[str, FileType] = {}


def _t(name, mime, category, *exts, text=False):
    TYPES[name] = FileType(name, mime, category, tuple(exts) or (name,), text)


# Images
_t("jpg", "image/jpeg", IMAGES, "jpg", "jpeg", "jpe", "jfif")
_t("png", "image/png", IMAGES)
_t("gif", "image/gif", IMAGES)
_t("bmp", "image/bmp", IMAGES, "bmp", "dib")
_t("webp", "image/webp", IMAGES)
_t("tiff", "image/tiff", IMAGES, "tif", "tiff")
_t("ico", "image/x-icon", IMAGES, "ico", "cur")
_t("heic", "image/heic", IMAGES, "heic", "heif")
_t("avif", "image/avif", IMAGES)
_t("psd", "image/vnd.adobe.photoshop", IMAGES)
_t("svg", "image/svg+xml", IMAGES, "svg", text=True)
# Videos (ISO media files are interchangeable between .mp4 and .mov)
_t("mp4", "video/mp4", VIDEOS, "mp4", "m4v", "mov", "3gp", "3g2")
_t("mov", "video/quicktime", VIDEOS, "mov", "qt", "mp4", "m4v")
_t("avi", "video/x-msvideo", VIDEOS)
_t("mkv", "video/x-matroska", VIDEOS, "mkv", "mk3d")
_t("webm", "video/webm", VIDEOS, "webm", "mkv")
_t("flv", "video/x-flv", VIDEOS)
_t("wmv", "video/x-ms-wmv", VIDEOS, "wmv", "asf")
_t("mpeg", "video/mpeg", VIDEOS, "mpg", "mpeg", "vob")
_t("ogv", "video/ogg", VIDEOS, "ogv")
# Audio
_t("mp3", "audio/mpeg", AUDIO)
_t("wav", "audio/wav", AUDIO, "wav", "wave")
_t("flac", "audio/flac", AUDIO)
_t("ogg", "audio/ogg", AUDIO, "ogg", "oga", "opus", "spx")
_t("m4a", "audio/mp4", AUDIO, "m4a", "m4b", "m4p", "mp4")
_t("aac", "audio/aac", AUDIO)
_t("wma", "audio/x-ms-wma", AUDIO, "wma", "asf")
_t("mid", "audio/midi", AUDIO, "mid", "midi")
_t("aiff", "audio/aiff", AUDIO, "aif", "aiff", "aifc")
_t("amr", "audio/amr", AUDIO)
# Documents
_t("pdf", "application/pdf", DOCUMENTS)
_t("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
   DOCUMENTS, "docx", "docm", "dotx", "dotm")
_t("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
   DOCUMENTS, "xlsx", "xlsm", "xltx", "xltm")
_t("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
   DOCUMENTS, "pptx", "pptm", "ppsx", "potx")
_t("odt", "application/vnd.oasis.opendocument.text", DOCUMENTS)
_t("ods", "application/vnd.oasis.opendocument.spreadsheet", DOCUMENTS)
_t("odp", "application/vnd.oasis.opendocument.presentation", DOCUMENTS)
_t("epub", "application/epub+zip", DOCUMENTS)
_t("doc", "application/msword", DOCUMENTS, "doc", "dot")
_t("xls", "application/vnd.ms-excel", DOCUMENTS, "xls", "xlt")
_t("ppt", "application/vnd.ms-powerpoint", DOCUMENTS, "ppt", "pps", "pot")
_t("msg", "application/vnd.ms-outlook", DOCUMENTS)
_t("rtf", "application/rtf", DOCUMENTS)
# Plain-text formats: one type per extension family.
_TEXT_FAMILIES = {
    "txt": ("text/plain", ("txt", "text")),
    "log": ("text/plain", ("log",)),
    "csv": ("text/csv", ("csv",)),
    "tsv": ("text/tab-separated-values", ("tsv", "tab")),
    "md": ("text/markdown", ("md", "markdown", "rst")),
    "json": ("application/json", ("json", "geojson", "ipynb")),
    "xml": ("application/xml", ("xml", "xsd", "xsl", "plist", "rss")),
    "html": ("text/html", ("html", "htm", "xhtml")),
    "yaml": ("application/yaml", ("yaml", "yml")),
    "ini": ("text/plain", ("ini", "cfg", "conf", "toml", "env", "properties")),
    "srt": ("text/plain", ("srt", "vtt", "sub")),
    "tex": ("text/x-tex", ("tex", "bib")),
    "code": ("text/plain", (
        "py", "js", "mjs", "ts", "tsx", "jsx", "css", "scss", "sql", "sh", "ps1",
        "bat", "cmd", "c", "h", "cpp", "hpp", "cc", "cs", "java", "kt", "go", "rs",
        "rb", "php", "pl", "lua", "r", "swift", "vb")),
}
for _name, (_mime, _exts) in _TEXT_FAMILIES.items():
    _t(_name, _mime, DOCUMENTS, *_exts, text=True)
# Archives
_t("zip", "application/zip", ARCHIVES, "zip", "cbz", "whl", "xpi", "nupkg")
_t("rar", "application/vnd.rar", ARCHIVES, "rar", "cbr")
_t("7z", "application/x-7z-compressed", ARCHIVES)
_t("gz", "application/gzip", ARCHIVES, "gz", "tgz")
_t("bz2", "application/x-bzip2", ARCHIVES, "bz2", "tbz", "tbz2")
_t("xz", "application/x-xz", ARCHIVES, "xz", "txz")
_t("zst", "application/zstd", ARCHIVES, "zst")
_t("tar", "application/x-tar", ARCHIVES)
_t("cab", "application/vnd.ms-cab-compressed", ARCHIVES)
_t("iso", "application/x-iso9660-image", ARCHIVES)
_t("jar", "application/java-archive", ARCHIVES, "jar", "war", "ear")
# Others
_t("exe", "application/x-msdownload", OTHERS,
   "exe", "dll", "sys", "scr", "com", "ocx", "cpl", "efi", "mui")
_t("msi", "application/x-msi", OTHERS, "msi", "msp")
_t("elf", "application/x-elf", OTHERS, "so", "elf", "o")
_t("class", "application/java-vm", OTHERS)
_t("apk", "application/vnd.android.package-archive", OTHERS)
_t("sqlite", "application/vnd.sqlite3", OTHERS, "db", "sqlite", "sqlite3")
_t("ttf", "font/ttf", OTHERS)
_t("otf", "font/otf", OTHERS)
_t("woff", "font/woff", OTHERS, "woff", "woff2")
_t("empty", "application/x-empty", OTHERS, "")
_t("unknown", "application/octet-stream", OTHERS, "")

# Extensions we know how to verify. An extension outside this set is never
# reported as a mismatch, because we have nothing to compare it with.
KNOWN_EXTENSIONS = frozenset(e for t in TYPES.values() for e in t.extensions if e)
TEXT_EXTENSIONS = {e: t.name for t in TYPES.values() if t.is_text and t.name != "svg"
                   for e in t.extensions}

_ASF_GUID = bytes.fromhex("3026B2758E66CF11A6D900AA0062CE6C")
_OLE = bytes.fromhex("D0CF11E0A1B11AE1")
_OLE_BY_EXT = {"doc": "doc", "dot": "doc", "xls": "xls", "xlt": "xls", "ppt": "ppt",
               "pps": "ppt", "pot": "ppt", "msg": "msg", "msi": "msi", "msp": "msi"}


def extension_of(path) -> str:
    return Path(path).suffix.lower().lstrip(".")


def detect(path) -> FileType:
    """Return the FileType of ``path`` judged by its content."""
    path = Path(path)
    ext = extension_of(path)
    with open(path, "rb") as f:
        head = f.read(HEADER_SIZE)
    if not head:
        return TYPES["empty"]
    name = _sniff(head, ext, path)
    if name == "unknown":
        name = _sniff_iso(path) or name
    ftype = TYPES[name]
    if name == "unknown":
        ftype = _magic_fallback(path) or ftype
    return ftype


def _sniff(h: bytes, ext: str, path: Path) -> str:
    if h.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if h[:2] == b"BM" and len(h) >= 18 and h[6:10] == b"\0\0\0\0" \
            and int.from_bytes(h[14:18], "little") in (12, 40, 52, 56, 64, 108, 124):
        return "bmp"
    if h[:4] == b"RIFF" and len(h) >= 12:
        kind = {b"WEBP": "webp", b"WAVE": "wav", b"AVI ": "avi"}.get(h[8:12])
        if kind:
            return kind
    if h[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if h[:4] == b"\x00\x00\x01\x00" and len(h) > 6 and h[4:6] != b"\0\0":
        return "ico"
    if h[4:8] == b"ftyp":
        return _ftyp(h[8:12], ext)
    if h[:4] == b"8BPS":
        return "psd"
    if h[:4] == b"\x1aE\xdf\xa3":
        return "webm" if b"webm" in h[:64] else "mkv"
    if h[:3] == b"FLV":
        return "flv"
    if h[:16] == _ASF_GUID:
        return "wma" if ext == "wma" else "wmv"
    if h[:4] in (b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3"):
        return "mpeg"
    if h[:3] == b"ID3":
        return "mp3"
    if h[:4] == b"fLaC":
        return "flac"
    if h[:4] == b"OggS":
        return "ogv" if ext == "ogv" or b"theora" in h[:128] else "ogg"
    if h[:4] == b"MThd":
        return "mid"
    if h[:4] == b"FORM" and h[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if h[:6] == b"#!AMR\n":
        return "amr"
    if h[:2] in (b"\xff\xfe", b"\xfe\xff"):  # UTF-16 BOM looks like an MPEG frame sync
        kind = _text_kind(h, ext)
        if kind:
            return kind
    if len(h) >= 3 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0:
        if (h[1] & 0xF6) == 0xF0:
            return "aac"
        if (h[1] >> 3) & 3 != 1 and (h[1] >> 1) & 3 != 0 and (h[2] >> 4) != 0xF:
            return "mp3"
    if h.startswith(b"%PDF-"):
        return "pdf"
    if h[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return _zip_kind(path, ext)
    if h[:8] == _OLE:
        return _OLE_BY_EXT.get(ext, "doc")
    if h.startswith(b"{\\rtf"):
        return "rtf"
    if h[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z"
    if h[:6] == b"Rar!\x1a\x07":
        return "rar"
    if h[:2] == b"\x1f\x8b":
        return "gz"
    if h[:3] == b"BZh" and len(h) > 3 and h[3:4].isdigit():
        return "bz2"
    if h[:6] == b"\xfd7zXZ\x00":
        return "xz"
    if h[:4] == b"\x28\xb5\x2f\xfd":
        return "zst"
    if len(h) >= 262 and h[257:262] == b"ustar":
        return "tar"
    if h[:4] == b"MSCF":
        return "cab"
    if h[:2] == b"MZ":
        return "exe"
    if h[:4] == b"\x7fELF":
        return "elf"
    if h[:4] == b"\xca\xfe\xba\xbe":
        return "class"
    if h.startswith(b"SQLite format 3\x00"):
        return "sqlite"
    if h[:5] == b"\x00\x01\x00\x00\x00":
        return "ttf"
    if h[:4] == b"OTTO":
        return "otf"
    if h[:4] in (b"wOFF", b"wOF2"):
        return "woff"
    return _text_kind(h, ext) or "unknown"


def _ftyp(brand: bytes, ext: str) -> str:
    if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"):
        return "heic"
    if brand in (b"avif", b"avis"):
        return "avif"
    if brand in (b"M4A ", b"M4B ", b"M4P "):
        return "m4a"
    # Generic ISO brands carry either audio or video; trust an audio extension.
    if ext in ("m4a", "m4b", "m4p"):
        return "m4a"
    if brand == b"qt  ":
        return "mov"
    return "mp4"


def _zip_kind(path: Path, ext: str) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if "mimetype" in names:
                mt = zf.read("mimetype").decode("ascii", "ignore").strip()
                for name in ("epub", "odt", "ods", "odp"):
                    if mt == TYPES[name].mime:
                        return name
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError):
        return "zip"  # damaged archive; validation will report why
    prefixes = {n.split("/", 1)[0] for n in names}
    if "[Content_Types].xml" in names:
        for folder, name in (("word", "docx"), ("xl", "xlsx"), ("ppt", "pptx")):
            if folder in prefixes:
                return name
    if "AndroidManifest.xml" in names:
        return "apk"
    if "META-INF/MANIFEST.MF" in names and ext not in TYPES["zip"].extensions:
        return "jar"
    return "zip"


def _sniff_iso(path: Path) -> str | None:
    try:
        with open(path, "rb") as f:
            f.seek(0x8001)
            if f.read(5) == b"CD001":
                return "iso"
    except OSError:
        pass
    return None


def _text_kind(h: bytes, ext: str) -> str | None:
    if h.startswith((b"\xff\xfe", b"\xfe\xff")):
        s = h.decode("utf-16", errors="ignore")
    else:
        if b"\x00" in h:
            return None
        try:
            s = h.decode("utf-8")
        except UnicodeDecodeError as e:
            if e.start < len(h) - 4:  # not just a character cut off by the read
                s = h.decode("cp1252", errors="replace")
                printable = sum(c.isprintable() or c in "\r\n\t\f" for c in s)
                if printable / len(s) < 0.95 or "�" in s:
                    return None
            else:
                s = h[:e.start].decode("utf-8")
        if s and sum(c.isprintable() or c in "\r\n\t\f\x1b" for c in s) / len(s) < 0.95:
            return None
    if ext in TEXT_EXTENSIONS:
        return TEXT_EXTENSIONS[ext]
    lead = s.lstrip("﻿ \t\r\n").lower()
    if "<svg" in lead[:4096] and lead.startswith(("<?xml", "<svg", "<!doctype svg")):
        return "svg"
    if lead.startswith(("<!doctype html", "<html")):
        return "html"
    if lead.startswith("<?xml"):
        return "xml"
    if lead.startswith(("{", "[")) and len(h) < HEADER_SIZE:
        try:
            json.loads(s)
            return "json"
        except ValueError:
            pass
    return _plain_text_kind(s)


_MD_LINE = re.compile(r"^(#{1,6} \S|```|\* \S|- \[[ x]\] )", re.M)


def _plain_text_kind(s: str) -> str:
    """Tell CSV/TSV and Markdown apart from plain text by their structure."""
    lines = [ln for ln in s.splitlines()[:20] if ln.strip()]
    if len(lines) >= 2 and len(s) == len(s.rstrip("�")):
        complete = lines[:-1] if len(lines) > 2 else lines  # last line may be cut off
        for delim, kind in (("\t", "tsv"), (",", "csv"), (";", "csv")):
            counts = {ln.count(delim) for ln in complete}
            if len(counts) == 1 and counts.pop() >= 1:
                return kind
    if _MD_LINE.search(s[:4096]):
        return "md"
    return "txt"


def _magic_fallback(path: Path) -> FileType | None:
    """Use libmagic, when installed, for formats we have no signature for."""
    try:
        import magic  # type: ignore
        mime = magic.from_file(os.fspath(path), mime=True)
    except Exception:
        return None
    if not mime or mime in ("application/octet-stream", "inode/x-empty"):
        return None
    top = mime.split("/", 1)[0]
    category = {"image": IMAGES, "video": VIDEOS, "audio": AUDIO,
                "text": DOCUMENTS}.get(top, OTHERS)
    return FileType("unknown", mime, category, ("",))
