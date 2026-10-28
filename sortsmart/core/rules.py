"""Sorting rules (FR2): category overrides, custom YAML rules, date subfolders."""
from __future__ import annotations

import fnmatch
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

MB = 2**20


def category_overrides(categories: dict) -> dict:
    """{Category: [type-or-ext, ...]} -> {type-or-ext: Category}."""
    out = {}
    for category, names in categories.items():
        for name in names or []:
            out[str(name).lower().lstrip(".")] = category
    return out


def rule_matches(match: dict, file) -> bool:
    """``file`` is a plugins.FileInfo. All given conditions must hold."""
    for key, want in match.items():
        if key == "type":
            ok = file.type in _as_list(want)
        elif key == "category":
            ok = file.category in _as_list(want)
        elif key == "extension":
            ok = file.ext in [str(e).lower().lstrip(".") for e in _as_list(want)]
        elif key == "name_contains":
            ok = any(str(w).lower() in file.name.lower() for w in _as_list(want))
        elif key == "name_glob":
            ok = any(fnmatch.fnmatch(file.name.lower(), str(w).lower()) for w in _as_list(want))
        elif key == "name_regex":
            ok = re.search(str(want), file.name, re.IGNORECASE) is not None
        elif key == "text_contains":
            ok = any(str(w).lower() in file.text.lower() for w in _as_list(want))
        elif key == "min_size_mb":
            ok = file.size >= float(want) * MB
        elif key == "max_size_mb":
            ok = file.size <= float(want) * MB
        else:
            raise ValueError(f"unknown rule condition: {key}")
        if not ok:
            return False
    return True


def _as_list(v):
    return v if isinstance(v, (list, tuple, set)) else [v]


def safe_relative(dest: str) -> PurePosixPath:
    """Normalize a rule/plugin destination; refuse anything leaving the root."""
    rel = PurePosixPath(str(dest).replace("\\", "/").strip("/"))
    if not rel.parts or rel.is_absolute() or ".." in rel.parts or ":" in str(rel):
        raise ValueError(f"destination must be a relative folder inside the root: {dest!r}")
    return rel


def date_subfolder(path: Path, fmt: str, source: str, now: datetime | None = None) -> str:
    if source == "modified":
        when = datetime.fromtimestamp(Path(path).stat().st_mtime)
    else:
        when = now or datetime.now()
    return when.strftime(fmt)
