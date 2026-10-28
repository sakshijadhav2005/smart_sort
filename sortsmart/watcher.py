"""Watches an inbox folder and sorts each new file once its size is stable.

Files settle in parallel: one thread polls every pending file and hands it
to the worker as soon as its size and mtime stop changing, so a burst of
arrivals is not serialized behind each other's stability wait.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger("sortsmart.watcher")


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "Watcher"):
        self.watcher = watcher

    def on_created(self, event):
        if not event.is_directory:
            self.watcher.enqueue(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.watcher.enqueue(event.dest_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.watcher.enqueue(event.src_path)


class _Pending:
    __slots__ = ("snapshot", "same", "deadline", "ready")

    def __init__(self, timeout: float):
        self.snapshot = None
        self.same = 0
        self.deadline = time.monotonic() + timeout
        self.ready = False


class Watcher:
    def __init__(self, sorter, folder=None, *, recursive=None, rescan_interval: float = 30):
        self.sorter = sorter
        folder = folder or sorter.config.inbox
        if not folder:
            raise ValueError("no folder to watch: pass one or set 'inbox' in the config")
        self.folder = Path(folder).resolve()
        self.recursive = sorter.config["recursive"] if recursive is None else recursive
        self.rescan_interval = rescan_interval
        st = sorter.config["stability"]
        self._interval, self._checks, self._timeout = st["interval"], st["checks"], st["timeout"]
        self._queue: queue.Queue = queue.Queue()
        self._pending: dict[Path, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._observer = None
        self.processed = 0
        self._last_health = "ok"

    @property
    def queue_size(self) -> int:
        with self._pending_lock:
            return len(self._pending)

    @property
    def running(self) -> bool:
        return bool(self._observer and self._observer.is_alive() and not self._stop.is_set())

    def enqueue(self, path):
        path = Path(path)
        try:
            path = path.resolve()
            if not path.is_file() or self.sorter.is_ignored(path):
                return
        except OSError:
            return
        if not self.recursive and path.parent != self.folder:
            return
        with self._pending_lock:
            entry = self._pending.get(path)
            if entry is None:
                self._pending[path] = _Pending(self._timeout)
            elif not entry.ready:
                entry.same = 0  # changed again: restart its stability count

    def scan(self):
        for p in self.sorter.iter_folder(self.folder, recursive=self.recursive):
            self.enqueue(p)

    def start(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._observer = Observer()
        self._observer.schedule(_Handler(self), str(self.folder), recursive=self.recursive)
        self._observer.start()
        for target, name in ((self._work, "sortsmart-worker"), (self._settle, "sortsmart-settle"),
                             (self._background, "sortsmart-health")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        self.scan()  # files that arrived while we were not running
        log.info("watching folder", extra={"event": "watch_start", "folder": str(self.folder),
                                           "recursive": self.recursive})
        return self

    def stop(self, timeout: float = 5):
        self._stop.set()
        self._queue.put(None)
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout)
        for t in self._threads:
            t.join(timeout)
        self._threads.clear()
        log.info("watcher stopped", extra={"event": "watch_stop", "folder": str(self.folder)})

    def run_forever(self):
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def _settle(self):
        """Promote pending files to the work queue once they stop changing."""
        while not self._stop.wait(self._interval):
            now = time.monotonic()
            with self._pending_lock:
                items = [(p, e) for p, e in self._pending.items() if not e.ready]
            for path, entry in items:
                try:
                    st = path.stat()
                except OSError:
                    with self._pending_lock:
                        self._pending.pop(path, None)
                    continue
                snapshot = (st.st_size, st.st_mtime_ns)
                with self._pending_lock:
                    if snapshot == entry.snapshot:
                        entry.same += 1
                    else:
                        entry.snapshot, entry.same = snapshot, 0
                    if entry.same >= self._checks:
                        entry.ready = True
                    elif now > entry.deadline:
                        # still being written; drop it, a later event or rescan re-adds it
                        self._pending.pop(path, None)
                        log.warning("file never stopped changing", extra={
                            "event": "unstable", "file": str(path)})
                        continue
                if entry.ready:
                    self._queue.put(path)

    def _work(self):
        while not self._stop.is_set():
            path = self._queue.get()
            if path is None:
                break
            try:
                if path.exists():
                    result = self.sorter.process(path, skip_restored=True)
                    if result.status != "skipped":
                        self.processed += 1
            except FileNotFoundError:
                pass
            except Exception:
                log.exception("unexpected error processing file",
                              extra={"event": "error", "file": str(path)})
            finally:
                with self._pending_lock:
                    self._pending.pop(path, None)

    def _background(self):
        """Periodic rescan (catches missed events) and health alerts."""
        interval = self.sorter.config["health"]["interval"]
        next_health = time.monotonic() + interval
        next_scan = time.monotonic() + self.rescan_interval
        while not self._stop.wait(1):
            now = time.monotonic()
            if now >= next_scan:
                next_scan = now + self.rescan_interval
                try:
                    self.scan()
                except Exception:
                    log.exception("rescan failed", extra={"event": "error"})
            if now >= next_health:
                next_health = now + interval
                self.check_health()

    def check_health(self) -> dict:
        report = self.sorter.health(watcher=self)
        if report["status"] != "ok" and self._last_health == "ok":
            msg = "; ".join(report["problems"]) or report["status"]
            log.warning(f"health {report['status']}: {msg}",
                        extra={"event": "health_alert", "problems": report["problems"]})
            self.sorter.plugins.alert(msg, report)
        elif report["status"] == "ok" and self._last_health != "ok":
            log.info("health recovered", extra={"event": "health_ok"})
        self._last_health = report["status"]
        return report
