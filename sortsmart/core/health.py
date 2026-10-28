"""Health checks (FR13): service, catalog, disk, queue and stuck files."""
from __future__ import annotations

import time
from datetime import datetime, timezone


def check_health(sorter, watcher=None) -> dict:
    from .engine import disk_usage
    cfg = sorter.config
    hc = cfg["health"]
    problems = []

    try:
        sorter.catalog.ping()
        catalog = {"status": "ok", "path": str(cfg.catalog_path)}
    except Exception as e:
        catalog = {"status": "error", "error": str(e)}
        problems.append(f"catalog unavailable: {e}")

    usage = disk_usage(cfg.destination)
    free_mb = usage.free / 2**20
    disk = {"status": "ok" if free_mb >= hc["min_free_mb"] else "low",
            "path": str(cfg.destination), "free_bytes": usage.free, "total_bytes": usage.total,
            "free_pct": round(100 * usage.free / usage.total, 1) if usage.total else None}
    if disk["status"] != "ok":
        problems.append(f"low disk space: {free_mb:.0f} MB free")

    if watcher is not None:
        size = watcher.queue_size
        queue = {"status": "ok" if size <= hc["max_queue"] else "backlog", "size": size,
                 "running": watcher.running, "folder": str(watcher.folder)}
        if not watcher.running:
            queue["status"] = "stopped"
            problems.append("watcher is not running")
        elif size > hc["max_queue"]:
            problems.append(f"queue backlog: {size} files waiting")
    else:
        queue = {"status": "not_watching", "size": 0}

    stuck = []
    folder = watcher.folder if watcher is not None else cfg.inbox
    if folder and folder.is_dir():
        cutoff = time.time() - hc["stuck_after"]
        for p in sorter.iter_folder(folder, recursive=cfg["recursive"]):
            try:
                st = p.stat()  # ctime: copies keep an old mtime but get a new ctime
                if max(st.st_mtime, st.st_ctime) < cutoff:
                    stuck.append(str(p))
            except OSError:
                continue
    if stuck and watcher is not None:
        problems.append(f"{len(stuck)} file(s) stuck in the inbox")

    plugins = sorter.plugins.describe()
    if catalog["status"] != "ok":
        status = "error"
    elif problems:
        status = "degraded"
    else:
        status = "ok"
    return {
        "status": status,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "service": "ok",
        "catalog": catalog,
        "disk": disk,
        "queue": queue,
        "stuck_files": stuck[:50],
        "stuck_count": len(stuck),
        "plugins": plugins,
        "problems": problems,
    }
