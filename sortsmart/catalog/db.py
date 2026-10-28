"""SQL catalog of every move (FR6).

Each row is written *before* the file is moved (completed=0) and finalized
afterwards, so an interrupted move can always be traced and reconciled.
The SQL is plain ANSI-ish so the backend can be swapped for SQL Server later.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    type          TEXT,
    mime          TEXT,
    category      TEXT,
    size          INTEGER,
    hash          TEXT,
    old_path      TEXT    NOT NULL,
    new_path      TEXT,
    status        TEXT    NOT NULL,
    reason        TEXT,
    plugin        TEXT,
    duplicate_of  INTEGER,
    completed     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    restored_at   TEXT,
    restored_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_type ON files(type);
"""

STATUSES = ("sorted", "duplicate", "quarantined", "failed")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Catalog:
    def __init__(self, path: Path | str):
        self.path = Path(path) if str(path) != ":memory:" else path
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)

    def close(self):
        with self._lock:
            self._conn.close()

    def _query(self, sql, params=()):
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _write(self, sql, params=()):
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def ping(self) -> bool:
        return self._query("SELECT 1 AS ok")[0]["ok"] == 1

    # -- writes ---------------------------------------------------------
    def begin(self, **fields) -> int:
        fields.setdefault("created_at", now_iso())
        fields["completed"] = 0
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = self._write(f"INSERT INTO files ({cols}) VALUES ({marks})", tuple(fields.values()))
        return cur.lastrowid

    def complete(self, file_id: int, new_path: str):
        self._write("UPDATE files SET new_path = ?, completed = 1 WHERE id = ?",
                    (new_path, file_id))

    def fail(self, file_id: int, reason: str):
        self._write("UPDATE files SET status = 'failed', reason = ?, new_path = NULL, "
                    "completed = 1 WHERE id = ?", (reason, file_id))

    def mark_restored(self, file_id: int, restored_path: str):
        self._write("UPDATE files SET restored_at = ?, restored_path = ? WHERE id = ?",
                    (now_iso(), restored_path, file_id))

    def reconcile(self) -> int:
        """Finish rows left half-done by a crash. Returns how many were fixed."""
        fixed = 0
        for row in self._query("SELECT * FROM files WHERE completed = 0"):
            if row["new_path"] and Path(row["new_path"]).exists():
                self.complete(row["id"], row["new_path"])
            else:
                self.fail(row["id"], "interrupted before the move finished")
            fixed += 1
        return fixed

    # -- reads ----------------------------------------------------------
    def get(self, file_id: int) -> dict | None:
        rows = self._query("SELECT * FROM files WHERE id = ?", (file_id,))
        return rows[0] if rows else None

    def sorted_with_hash(self, sha: str) -> list[dict]:
        return self._query(
            "SELECT * FROM files WHERE hash = ? AND status = 'sorted' AND completed = 1 "
            "AND restored_at IS NULL ORDER BY id", (sha,))

    def restored_to(self, path: str, sha: str) -> bool:
        return bool(self._query(
            "SELECT id FROM files WHERE restored_path = ? AND hash = ?", (path, sha)))

    def last_restorable(self, n: int) -> list[dict]:
        return self._query(
            "SELECT * FROM files WHERE completed = 1 AND status != 'failed' "
            "AND restored_at IS NULL ORDER BY id DESC LIMIT ?", (n,))

    def search(self, *, type=None, category=None, status=None, name=None, hash=None,
               restored=None, limit=100, offset=0) -> list[dict]:
        where, params = ["completed = 1"], []
        for col, val in (("type", type), ("category", category), ("status", status),
                         ("hash", hash)):
            if val:
                where.append(f"{col} = ?")
                params.append(val)
        if name:
            where.append("LOWER(name) LIKE ?")
            params.append(f"%{name.lower()}%")
        if restored is not None:
            where.append("restored_at IS NOT NULL" if restored else "restored_at IS NULL")
        sql = (f"SELECT * FROM files WHERE {' AND '.join(where)} "
               "ORDER BY id DESC LIMIT ? OFFSET ?")
        return self._query(sql, (*params, int(limit), int(offset)))

    def stats(self) -> dict:
        by_status = {s: 0 for s in STATUSES}
        for r in self._query("SELECT status, COUNT(*) AS n FROM files WHERE completed = 1 "
                             "GROUP BY status"):
            by_status[r["status"]] = r["n"]
        restored = self._query("SELECT COUNT(*) AS n FROM files WHERE restored_at IS NOT NULL")[0]["n"]
        live = "completed = 1 AND restored_at IS NULL"
        by_category = {r["category"]: {"count": r["n"], "bytes": r["b"] or 0} for r in self._query(
            f"SELECT category, COUNT(*) AS n, SUM(size) AS b FROM files "
            f"WHERE status = 'sorted' AND {live} GROUP BY category ORDER BY b DESC")}
        by_type = {r["type"]: {"count": r["n"], "bytes": r["b"] or 0} for r in self._query(
            f"SELECT type, COUNT(*) AS n, SUM(size) AS b FROM files "
            f"WHERE status = 'sorted' AND {live} GROUP BY type ORDER BY b DESC")}
        dup = self._query(f"SELECT COUNT(*) AS n, SUM(size) AS b FROM files "
                          f"WHERE status = 'duplicate' AND {live}")[0]
        reasons = {}
        for r in self._query(f"SELECT reason FROM files WHERE status = 'quarantined' AND {live}"):
            key = (r["reason"] or "unknown").split(":", 1)[0]
            reasons[key] = reasons.get(key, 0) + 1
        return {
            "total": sum(by_status.values()),
            "by_status": by_status,
            "restored": restored,
            "by_category": by_category,
            "by_type": by_type,
            "storage_bytes": sum(c["bytes"] for c in by_category.values()),
            "duplicates": {"count": dup["n"], "space_saved_bytes": dup["b"] or 0},
            "quarantine": {"count": sum(reasons.values()), "reasons": reasons},
        }
