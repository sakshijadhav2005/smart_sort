"""Command-line tool (FR8): watch, sort, restore, stats and friends."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .core.config import ConfigError
from .core.engine import Sorter


def _human(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _config_path(args):
    if getattr(args, "config", None):
        return args.config
    env = os.environ.get("SORTSMART_CONFIG")
    if env:
        return env
    return "rules.yaml" if Path("rules.yaml").is_file() else None


def _print_json(data):
    print(json.dumps(data, indent=2, default=str))


def _print_result(r):
    where = r.destination or r.reason or ""
    extra = f"  ({r.reason})" if r.reason and r.destination else ""
    print(f"{r.status:<11} {r.type or '-':<7} {r.name}  ->  {where}{extra}")


def cmd_watch(sorter, args):
    from .watcher import Watcher
    w = Watcher(sorter, args.folder, recursive=args.recursive or None)
    print(f"Watching {w.folder} -> {sorter.config.destination}  (Ctrl+C to stop)")
    w.run_forever()
    return 0


def cmd_sort(sorter, args):
    results = sorter.sort_paths(args.paths, recursive=args.recursive, wait_stable=args.wait)
    if args.json:
        _print_json([r.to_dict() for r in results])
    else:
        for r in results:
            _print_result(r)
        counts = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        print("\n" + (", ".join(f"{v} {k}" for k, v in counts.items()) or "no files found"))
    return 1 if any(r.status == "failed" for r in results) else 0


def cmd_classify(sorter, args):
    out = [sorter.classify(p).to_dict() for p in args.paths]
    if args.json:
        _print_json(out)
    else:
        for c in out:
            state = "valid" if c["valid"] else f"INVALID ({c['reason']})"
            dup = f", duplicate of #{c['duplicate_of']}" if c["duplicate"] else ""
            print(f"{c['name']}: {c['type']} [{c['mime']}] {c['category']}, {state}{dup}"
                  f"\n  sha256 {c['hash']}\n  would go to {c['planned_folder']}")
    return 0


def cmd_restore(sorter, args):
    if args.id:
        out = []
        for i in args.id:
            try:
                out.append(sorter.restore(i))
            except (KeyError, ValueError, OSError) as e:
                out.append({"id": i, "error": str(e).strip("'\"")})
    else:
        out = sorter.restore_last(args.last)
    if args.json:
        _print_json(out)
    else:
        if not out:
            print("nothing to restore")
        for r in out:
            if "error" in r:
                print(f"#{r['id']}: ERROR {r['error']}")
            else:
                print(f"#{r['id']}: {r['name']} -> {r['restored_to']}")
    return 1 if any("error" in r for r in out) else 0


def cmd_stats(sorter, args):
    s = sorter.stats()
    if args.json:
        _print_json(s)
        return 0
    bs = s["by_status"]
    print(f"Files processed: {s['total']}  (sorted {bs['sorted']}, duplicates {bs['duplicate']}, "
          f"quarantined {bs['quarantined']}, failed {bs['failed']}, restored {s['restored']})")
    print(f"Storage sorted:  {_human(s['storage_bytes'])}")
    print(f"Space saved:     {_human(s['duplicates']['space_saved_bytes'])} "
          f"in {s['duplicates']['count']} duplicate(s)")
    if s["by_category"]:
        print("\nBy category:")
        for cat, v in s["by_category"].items():
            print(f"  {cat:<12} {v['count']:>6} files  {_human(v['bytes']):>10}")
    if s["quarantine"]["count"]:
        print("\nQuarantine reasons:")
        for reason, n in s["quarantine"]["reasons"].items():
            print(f"  {reason:<12} {n:>6}")
    return 0


def cmd_search(sorter, args):
    rows = sorter.search(type=args.type, category=args.category, status=args.status,
                         name=args.name, limit=args.limit)
    if args.json:
        _print_json(rows)
    else:
        for r in rows:
            restored = "  [restored]" if r["restored_at"] else ""
            print(f"#{r['id']:<5} {r['status']:<11} {r['type'] or '-':<7} {_human(r['size']):>9}  "
                  f"{r['name']}  ->  {r['new_path']}{restored}")
        print(f"\n{len(rows)} result(s)")
    return 0


def cmd_health(sorter, args):
    h = sorter.health()
    if args.json:
        _print_json(h)
    else:
        print(f"Status: {h['status']}")
        print(f"Catalog: {h['catalog']['status']}   Disk: {h['disk']['status']} "
              f"({_human(h['disk']['free_bytes'])} free)   Files waiting in inbox: {h['stuck_count']}")
        for p in h["problems"]:
            print(f"  ! {p}")
        for d in h["plugins"]["disabled"]:
            print(f"  ! plugin {d['name']} disabled: {d['error']}")
    return 0 if h["status"] == "ok" else 2


def cmd_dashboard(sorter, args):
    import subprocess
    script = Path(__file__).with_name("dashboard.py")
    env = dict(os.environ)
    if sorter.config.source:
        env["SORTSMART_CONFIG"] = str(sorter.config.source)
    sorter.close()
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(script)], env=env)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", "-c", default=argparse.SUPPRESS,
                        help="YAML rules file (default: $SORTSMART_CONFIG or ./rules.yaml)")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output")

    p = argparse.ArgumentParser(prog="sortsmart", parents=[common],
                                description="Sort files by their real content type.")
    p.add_argument("--version", action="version", version=f"sortsmart {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("watch", parents=[common], help="watch a folder and sort new files")
    s.add_argument("folder", nargs="?", help="inbox folder (default: 'inbox' from config)")
    s.add_argument("--recursive", "-r", action="store_true")
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("sort", parents=[common], help="sort files or folders once")
    s.add_argument("paths", nargs="+")
    s.add_argument("--recursive", "-r", action="store_true")
    s.add_argument("--wait", action="store_true", help="wait for each file's size to settle")
    s.set_defaults(func=cmd_sort)

    s = sub.add_parser("classify", parents=[common], help="show type, hash, validity; move nothing")
    s.add_argument("paths", nargs="+")
    s.set_defaults(func=cmd_classify)

    s = sub.add_parser("restore", parents=[common], help="move files back to where they came from")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--last", type=int, metavar="N", help="restore the N most recent moves")
    g.add_argument("--id", type=int, nargs="+", help="restore catalog entries by id")
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser("stats", parents=[common], help="counts, storage by type, duplicates")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("search", parents=[common], help="search the catalog")
    s.add_argument("--type")
    s.add_argument("--category")
    s.add_argument("--status", choices=["sorted", "duplicate", "quarantined", "failed"])
    s.add_argument("--name", help="substring of the file name")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("health", parents=[common], help="catalog, disk and inbox status")
    s.set_defaults(func=cmd_health)

    s = sub.add_parser("dashboard", parents=[common], help="open the Streamlit dashboard")
    s.set_defaults(func=cmd_dashboard)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    args.json = getattr(args, "json", False)
    overrides = {}
    if args.command == "watch":
        if args.folder:
            overrides["inbox"] = str(Path(args.folder).expanduser().resolve())
        overrides["logging"] = {"console": True}
    try:
        sorter = Sorter(_config_path(args), **overrides)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    try:
        return args.func(sorter, args)
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        sorter.close()


if __name__ == "__main__":
    sys.exit(main())
