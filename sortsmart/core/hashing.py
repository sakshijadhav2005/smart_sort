"""SHA-256 content hashing used for duplicate detection (FR3)."""
from __future__ import annotations

import hashlib

CHUNK = 1024 * 1024


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()
