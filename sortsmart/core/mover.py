"""Moving files safely (FR5): files are moved, never deleted or overwritten."""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

log = logging.getLogger("sortsmart.mover")


class MoveError(OSError):
    pass


def unique_path(target: Path, reserved: set | None = None) -> Path:
    """Return ``target`` or ``name (1).ext``, ``name (2).ext``... if taken."""
    target = Path(target)
    candidate, n = target, 1
    while candidate.exists() or (reserved and candidate in reserved):
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        n += 1
    return candidate


def safe_move(src: Path, target: Path, *, attempts: int = 3, delay: float = 0.5) -> Path:
    """Move ``src`` to exactly ``target``; retry locked files, never overwrite."""
    src, target = Path(src), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        if target.exists():
            raise MoveError(f"refusing to overwrite existing file {target}")
        try:
            shutil.move(os.fspath(src), os.fspath(target))
            return target
        except OSError as e:
            last = e
            if not src.exists():
                break
            log.warning("move failed, retrying", extra={
                "event": "move_retry", "file": str(src), "attempt": attempt, "error": str(e)})
            if attempt < attempts:
                time.sleep(delay * attempt)
    raise MoveError(f"could not move {src} after {attempts} attempts: {last}") from last


def wait_for_stable(path: Path, *, interval: float = 0.5, checks: int = 2,
                    timeout: float = 300) -> bool:
    """Block until size and mtime stop changing. False if the file vanished
    or never settled within ``timeout`` seconds."""
    path = Path(path)
    deadline = time.monotonic() + timeout
    last, same = None, 0
    while time.monotonic() < deadline:
        try:
            st = path.stat()
        except FileNotFoundError:
            return False
        snapshot = (st.st_size, st.st_mtime_ns)
        if snapshot == last:
            same += 1
            if same >= checks:
                return True
        else:
            last, same = snapshot, 0
        time.sleep(interval)
    return False
