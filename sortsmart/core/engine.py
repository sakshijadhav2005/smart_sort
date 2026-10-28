"""The core engine: Detect -> Check -> Decide -> Act.

The CLI and the library both call ``Sorter``, so a file gets
the same result whichever entry point is used.
"""
from __future__ import annotations

import fnmatch
import logging
import shutil
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from ..catalog import Catalog, setup_logging, teardown_logging
from ..plugins import FileInfo, PluginManager
from .config import Config
from .detection import FileType, detect, extension_of
from .hashing import sha256
from .mover import MoveError, safe_move, unique_path, wait_for_stable
from .rules import category_overrides, date_subfolder, rule_matches, safe_relative
from .validation import validate

log = logging.getLogger("sortsmart.core")


@dataclass
class Classification:
    name: str
    path: str
    type: str
    mime: str
    category: str
    size: int
    hash: str
    valid: bool
    reason: str | None
    duplicate: bool
    duplicate_of: int | None
    planned_folder: str        # relative to the destination root
    rule: str | None           # plugin or rule that decided the folder

    def to_dict(self):
        return asdict(self)


@dataclass
class ProcessResult:
    status: str                # sorted | duplicate | quarantined | failed | skipped
    name: str
    original: str
    destination: str | None
    type: str | None = None
    mime: str | None = None
    category: str | None = None
    size: int | None = None
    hash: str | None = None
    reason: str | None = None
    rule: str | None = None
    duplicate_of: int | None = None
    id: int | None = None

    def to_dict(self):
        return asdict(self)


class Sorter:
    """Public library entry point (FR9).

    >>> sorter = Sorter(config="rules.yaml")
    >>> result = sorter.process("uploads/file123")
    """

    def __init__(self, config=None, *, plugins=None, **overrides):
        self.config = Config.load(config, **overrides)
        cfg = self.config
        lc = cfg["logging"]
        self._log_handlers = setup_logging(cfg.log_dir, level=lc["level"],
                                           max_bytes=lc["max_bytes"], backups=lc["backups"],
                                           console=lc["console"])
        self.catalog = Catalog(cfg.catalog_path)
        fixed = self.catalog.reconcile()
        if fixed:
            log.warning("reconciled interrupted moves", extra={"event": "reconcile", "count": fixed})
        self.plugins = PluginManager(cfg["plugins"]["settings"])
        if cfg["plugins"]["enabled"]:
            self.plugins.load_builtin(cfg["plugins"]["builtin"])
            self.plugins.load_dir(cfg.plugins_dir)
        for plugin in plugins or []:
            self.plugins.add(plugin)
        self._overrides = category_overrides(cfg["categories"])
        self._lock = threading.RLock()
        self._closed = False

    # -- lifecycle --------------------------------------------------------
    def close(self):
        if not self._closed:
            self._closed = True
            self.catalog.close()
            teardown_logging(self._log_handlers)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- single steps -----------------------------------------------------
    def detect_type(self, path) -> str:
        """Content type name only (e.g. ``"png"``); nothing is moved."""
        return detect(path).name

    def file_type(self, path) -> FileType:
        return detect(path)

    def is_duplicate(self, path) -> bool:
        """Hash check only; True if identical content was already sorted."""
        return self._duplicate_of(sha256(path)) is not None

    def classify(self, path) -> Classification:
        """Everything ``process`` would decide, without moving anything."""
        path = Path(path).resolve()
        info, ftype = self._inspect(path)
        check = self._validate(path, ftype, info.size)
        dup = self._duplicate_of(info.hash) if check.valid else None
        folder, rule = self._decide(info, path) if check.valid and dup is None else (None, None)
        category = info.category
        if not check.valid:
            folder = self.config["folders"]["quarantine"]
        elif dup is not None:
            folder = self.config["folders"]["duplicates"]
        elif rule:
            category = Path(folder).parts[0]
        return Classification(info.name, str(path), info.type, info.mime, category,
                              info.size, info.hash, check.valid, check.reason, dup is not None,
                              dup, folder, rule)

    # -- full pipeline ----------------------------------------------------
    def process(self, path, *, wait_stable: bool = False, skip_restored: bool = False) -> ProcessResult:
        """Detect, check, decide and move one file; record it in the catalog."""
        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"no such file: {path}")
        if self.is_protected(path):
            raise ValueError(f"refusing to sort SortSmart's own file: {path}")
        if wait_stable:
            st = self.config["stability"]
            if not wait_for_stable(path, interval=st["interval"], checks=st["checks"],
                                   timeout=st["timeout"]):
                return ProcessResult("skipped", path.name, str(path), None,
                                     reason="file vanished or never stopped changing")
        with self._lock:
            return self._process_locked(path, skip_restored)

    def _process_locked(self, path: Path, skip_restored: bool) -> ProcessResult:
        info, ftype = self._inspect(path)
        if skip_restored and self.catalog.restored_to(str(path), info.hash):
            return ProcessResult("skipped", info.name, str(path), None, info.type, info.mime,
                                 info.category, info.size, info.hash,
                                 reason="restored by user; left in place")
        check = self._validate(path, ftype, info.size)
        rule = dup = None
        if not check.valid:
            status, folder = "quarantined", self.config.quarantine_dir
        elif (dup := self._duplicate_of(info.hash)) is not None:
            status, folder = "duplicate", self.config.duplicates_dir
        else:
            status = "sorted"
            rel, rule = self._decide(info, path)
            folder = self.config.destination / rel

        target = unique_path(folder / path.name)
        category = info.category if status == "sorted" else None
        if status == "sorted" and rule:
            category = Path(rel).parts[0]
        file_id = self.catalog.begin(
            name=info.name, type=info.type, mime=info.mime, category=category or info.category,
            size=info.size, hash=info.hash, old_path=str(path), new_path=str(target),
            status=status, reason=check.reason, plugin=rule, duplicate_of=dup)
        result = ProcessResult(status, info.name, str(path), str(target), info.type, info.mime,
                               category or info.category, info.size, info.hash, check.reason,
                               rule, dup, file_id)
        retry = self.config["retry"]
        try:
            safe_move(path, target, attempts=retry["attempts"], delay=retry["delay"])
        except (MoveError, OSError) as e:
            self.catalog.fail(file_id, str(e))
            result.status, result.destination, result.reason = "failed", None, str(e)
            log.error("move failed", extra={"event": "failed", "id": file_id,
                                            "file": str(path), "error": str(e)})
        else:
            self.catalog.complete(file_id, str(target))
            level = logging.INFO if status == "sorted" else logging.WARNING
            log.log(level, f"{status}: {info.name}", extra={
                "event": status, "id": file_id, "file": str(path), "destination": str(target),
                "type": info.type, "size": info.size, "hash": info.hash,
                "reason": check.reason, "rule": rule})
        info.path = Path(result.destination or path)
        self.plugins.run_actions(result, info)
        return result

    def sort_paths(self, paths, *, recursive=False, wait_stable=False) -> list[ProcessResult]:
        """Process files and/or every file in the given folders."""
        results = []
        for p in paths:
            p = Path(p)
            files = [p] if p.is_file() else self.iter_folder(p, recursive=recursive)
            for f in files:
                try:
                    results.append(self.process(f, wait_stable=wait_stable))
                except (FileNotFoundError, ValueError) as e:
                    results.append(ProcessResult("skipped", f.name, str(f), None, reason=str(e)))
        return results

    def iter_folder(self, folder, *, recursive=False):
        folder = Path(folder).resolve()
        if not folder.is_dir():
            raise FileNotFoundError(f"no such folder: {folder}")
        it = folder.rglob("*") if recursive else folder.iterdir()
        return sorted(p for p in it if p.is_file() and not self.is_ignored(p))

    # -- restore, search, stats -------------------------------------------
    def restore(self, file_id: int) -> dict:
        """Move a file back to the path it had before SortSmart moved it."""
        with self._lock:
            row = self.catalog.get(int(file_id))
            if row is None:
                raise KeyError(f"no catalog entry with id {file_id}")
            if row["restored_at"]:
                raise ValueError(f"file {file_id} was already restored to {row['restored_path']}")
            if row["status"] == "failed" or not row["completed"]:
                raise ValueError(f"file {file_id} was never moved (status {row['status']})")
            src = Path(row["new_path"])
            if not src.exists():
                raise FileNotFoundError(f"file {file_id} is no longer at {src}")
            target = unique_path(Path(row["old_path"]))
            retry = self.config["retry"]
            safe_move(src, target, attempts=retry["attempts"], delay=retry["delay"])
            self.catalog.mark_restored(row["id"], str(target))
        log.info(f"restored: {row['name']}", extra={
            "event": "restored", "id": row["id"], "from": str(src), "to": str(target)})
        return {"id": row["id"], "name": row["name"], "from": str(src), "restored_to": str(target)}

    def restore_last(self, n: int) -> list[dict]:
        out = []
        for row in self.catalog.last_restorable(int(n)):
            try:
                out.append(self.restore(row["id"]))
            except (OSError, ValueError) as e:
                out.append({"id": row["id"], "name": row["name"], "error": str(e)})
        return out

    def search(self, **filters) -> list[dict]:
        return self.catalog.search(**filters)

    def get(self, file_id: int) -> dict | None:
        return self.catalog.get(int(file_id))

    def stats(self) -> dict:
        return self.catalog.stats()

    def health(self, watcher=None) -> dict:
        from .health import check_health
        return check_health(self, watcher)

    # -- helpers ----------------------------------------------------------
    def protected_paths(self) -> list[Path]:
        cfg = self.config
        db = cfg.catalog_path
        paths = [db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm"),
                 db.with_name(db.name + "-journal"), cfg.log_dir, cfg.destination,
                 cfg.plugins_dir]
        if cfg.source:
            paths.append(cfg.source)
        return paths

    def is_protected(self, path: Path) -> bool:
        path = Path(path).resolve()
        return any(path == p or p in path.parents for p in self.protected_paths())

    def is_ignored(self, path: Path) -> bool:
        name = Path(path).name
        if any(fnmatch.fnmatch(name, pat) for pat in self.config["ignore"]):
            return True
        return self.is_protected(path)

    def _inspect(self, path: Path) -> tuple[FileInfo, FileType]:
        ftype = detect(path)
        size = path.stat().st_size
        category = self._overrides.get(ftype.name) or self._overrides.get(
            extension_of(path)) or ftype.category
        info = FileInfo(path=path, name=path.name, ext=extension_of(path), type=ftype.name,
                        mime=ftype.mime, category=category, size=size, hash=sha256(path),
                        is_text=ftype.is_text)
        return info, ftype

    def _validate(self, path, ftype, size):
        return validate(path, ftype, size=size,
                        check_mismatch=self.config["quarantine_mismatch"],
                        deep_check_max_bytes=int(self.config["deep_check_max_mb"] * 2**20))

    def _duplicate_of(self, sha: str) -> int | None:
        for row in self.catalog.sorted_with_hash(sha):
            if row["new_path"] and Path(row["new_path"]).exists():
                return row["id"]
        return None

    def _decide(self, info: FileInfo, path: Path) -> tuple[str, str | None]:
        """Relative destination folder: plugins first, then YAML rules,
        then the category; plus an optional date subfolder."""
        rule = None
        hit = self.plugins.detect(info)
        if hit:
            rel, rule = hit
        else:
            rel = info.category
            for i, r in enumerate(self.config["rules"]):
                if rule_matches(r["match"], info):
                    rel = str(safe_relative(r["destination"]))
                    rule = f"rule:{r.get('name', i + 1)}"
                    break
        if self.config["date_subfolders"]:
            rel = f"{rel}/{date_subfolder(path, self.config['date_format'], self.config['date_source'])}"
        return rel, rule


def disk_usage(path: Path):
    path = Path(path)
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path)
