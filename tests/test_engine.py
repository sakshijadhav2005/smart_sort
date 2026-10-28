import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import pytest

import samples
from sortsmart import ConfigError, Sorter
from sortsmart.core import mover


def all_files(root: Path):
    return sorted(p for p in root.rglob("*") if p.is_file())


def test_sorts_into_category_folders(sorter, inbox, dest):
    expected = {}
    for i, kind in enumerate(samples.CATALOG):
        p = samples.write(inbox, kind, seed=i)
        expected[p.name] = samples.CATALOG[kind][3]
    results = sorter.sort_paths([inbox])
    assert {r.status for r in results} == {"sorted"}
    for r in results:
        assert Path(r.destination) == dest / expected[r.name] / r.name
        assert Path(r.destination).exists()
        assert r.category == expected[r.name]
    assert not any(inbox.iterdir())


def test_library_api_shape(sorter, inbox):
    """The calls shown in the PRD."""
    p = samples.write(inbox, "png", name="file123")  # no extension
    assert sorter.detect_type(p) == "png"
    assert sorter.is_duplicate(p) is False
    assert p.exists()  # neither call moves anything
    result = sorter.process(p)
    assert (result.category, result.status) == ("Images", "sorted")
    assert Path(result.destination).name == "file123"


def test_duplicates_go_to_duplicates_folder(sorter, inbox, dest):
    a = samples.write(inbox, "pdf", name="a.pdf", seed=1)
    b = inbox / "b.pdf"
    b.write_bytes(a.read_bytes())
    r1 = sorter.process(a)
    assert sorter.is_duplicate(b)
    r2 = sorter.process(b)
    assert r1.status == "sorted"
    assert r2.status == "duplicate" and r2.duplicate_of == r1.id
    assert Path(r2.destination).parent == dest / "Duplicates"
    # The same content is stored exactly once in the sorted tree.
    sorted_copies = [p for p in all_files(dest) if "Duplicates" not in p.parts]
    assert len(sorted_copies) == 1


def test_duplicate_of_a_restored_file_is_not_a_duplicate(sorter, inbox):
    a = samples.write(inbox, "png", name="a.png", seed=3)
    data = a.read_bytes()
    r1 = sorter.process(a)
    sorter.restore(r1.id)
    b = inbox / "b.png"
    b.write_bytes(data)
    assert sorter.process(b).status == "sorted"


def test_duplicate_check_ignores_files_deleted_from_sorted_tree(sorter, inbox):
    a = samples.write(inbox, "png", name="a.png", seed=4)
    data = a.read_bytes()
    r1 = sorter.process(a)
    Path(r1.destination).unlink()  # user removed it by hand
    b = inbox / "b.png"
    b.write_bytes(data)
    assert sorter.process(b).status == "sorted"


def test_quarantine_reasons(sorter, inbox, dest):
    (inbox / "empty.txt").write_bytes(b"")
    (inbox / "fake.jpg").write_bytes(samples.CATALOG["png"][0](9))
    broken = inbox / "broken.pdf"
    broken.write_bytes(samples.pdf()[:-20])
    results = {r.name: r for r in sorter.sort_paths([inbox])}
    assert all(r.status == "quarantined" for r in results.values())
    assert results["empty.txt"].reason.startswith("empty")
    assert results["fake.jpg"].reason.startswith("mismatch")
    assert results["broken.pdf"].reason.startswith("corrupt")
    for r in results.values():
        assert Path(r.destination).parent == dest / "Quarantine"
    rows = sorter.search(status="quarantined")
    assert {row["reason"] for row in rows} == {r.reason for r in results.values()}


def test_files_are_never_deleted(sorter, inbox, dest):
    """Every input file ends up somewhere, byte-for-byte."""
    hashes = {}
    for i, kind in enumerate(list(samples.CATALOG) * 2):
        p = samples.write(inbox, kind, name=f"f{i}.{samples.CATALOG[kind][1]}", seed=i % 5)
        hashes.setdefault(p.read_bytes(), 0)
        hashes[p.read_bytes()] += 1
    (inbox / "empty.txt").write_bytes(b"")
    n_in = len(list(inbox.iterdir()))
    sorter.sort_paths([inbox])
    out = all_files(dest)
    assert len(out) == n_in
    seen = {}
    for p in out:
        seen[p.read_bytes()] = seen.get(p.read_bytes(), 0) + 1
    assert seen == {**hashes, b"": 1}


def test_name_collisions_never_overwrite(sorter, inbox, dest):
    for i in range(3):
        sub = inbox / f"batch{i}"
        samples.write(sub, "txt", name="notes.txt", seed=i)
    results = sorter.sort_paths([inbox], recursive=True)
    names = sorted(Path(r.destination).name for r in results)
    assert names == ["notes (1).txt", "notes (2).txt", "notes.txt"]


def test_date_subfolders(sorter_factory, inbox, dest):
    s = sorter_factory(date_subfolders=True)
    p = samples.write(inbox, "jpg", name="photo.jpg")
    ts = datetime(2026, 10, 5, 12, 0).timestamp()
    os.utime(p, (ts, ts))
    r = s.process(p)
    assert Path(r.destination) == dest / "Images" / "2026" / "10" / "photo.jpg"


def test_date_subfolders_processed_time(sorter_factory, inbox, dest):
    s = sorter_factory(date_subfolders=True, date_source="processed", date_format="%Y")
    p = samples.write(inbox, "jpg", name="photo.jpg")
    os.utime(p, (0, 0))
    r = s.process(p)
    assert Path(r.destination).parent == dest / "Images" / str(datetime.now().year)


def test_yaml_rules_and_category_overrides(sorter_factory, inbox, dest):
    s = sorter_factory(
        categories={"Code": ["code"], "Data": ["csv", "json"]},
        rules=[{"name": "statements", "match": {"type": "pdf", "name_contains": "statement"},
                "destination": "Finance/Statements"},
               {"match": {"category": "Images", "min_size_mb": 0.0001, "name_glob": "big*"},
                "destination": "Images/Large"}])
    (inbox / "tool.py").write_text("print(1)\n")
    samples.write(inbox, "csv", name="table.csv")
    samples.write(inbox, "pdf", name="Bank Statement March.pdf")
    samples.write(inbox, "pdf", name="other.pdf", seed=2)
    big = inbox / "big_photo.bmp"
    from PIL import Image
    Image.new("RGB", (100, 100)).save(big)
    r = {x.name: x for x in s.sort_paths([inbox])}
    assert Path(r["tool.py"].destination).parent == dest / "Code"
    assert Path(r["table.csv"].destination).parent == dest / "Data"
    assert Path(r["Bank Statement March.pdf"].destination).parent == dest / "Finance" / "Statements"
    assert r["Bank Statement March.pdf"].rule == "rule:statements"
    assert r["Bank Statement March.pdf"].category == "Finance"
    assert Path(r["other.pdf"].destination).parent == dest / "Documents"
    assert Path(r["big_photo.bmp"].destination).parent == dest / "Images" / "Large"


def test_rule_cannot_escape_destination(sorter_factory, inbox):
    s = sorter_factory(rules=[{"match": {"type": "txt"}, "destination": "../outside"}])
    p = samples.write(inbox, "txt")
    with pytest.raises(ValueError):
        s.process(p)
    assert p.exists()


def test_catalog_records_every_field(sorter, inbox):
    p = samples.write(inbox, "mp3", name="song.mp3")
    size, original = p.stat().st_size, str(p.resolve())
    r = sorter.process(p)
    row = sorter.get(r.id)
    assert row["name"] == "song.mp3"
    assert row["type"] == "mp3" and row["category"] == "Audio"
    assert row["size"] == size and len(row["hash"]) == 64
    assert row["old_path"] == original and row["new_path"] == r.destination
    assert row["status"] == "sorted" and row["created_at"] and row["completed"] == 1


def test_classify_moves_nothing_and_predicts_process(sorter, inbox):
    p = samples.write(inbox, "docx", name="r.docx")
    c = sorter.classify(p)
    assert p.exists()
    assert (c.type, c.category, c.valid, c.duplicate) == ("docx", "Documents", True, False)
    r = sorter.process(p)
    assert r.hash == c.hash
    assert Path(r.destination).parent.name == c.planned_folder


def test_restore_one_and_last_n(sorter, inbox):
    originals = [samples.write(inbox, "txt", name=f"n{i}.txt", seed=i) for i in range(5)]
    results = sorter.sort_paths([inbox])
    assert not any(p.exists() for p in originals)
    out = sorter.restore(results[0].id)
    assert Path(out["restored_to"]) == originals[0].resolve() and originals[0].exists()
    with pytest.raises(ValueError):
        sorter.restore(results[0].id)
    last = sorter.restore_last(2)
    assert [x["id"] for x in last] == [results[4].id, results[3].id]
    assert originals[3].exists() and originals[4].exists()
    assert not originals[1].exists()
    assert sorter.stats()["restored"] == 3


def test_restore_does_not_overwrite_new_file_at_original_path(sorter, inbox):
    p = samples.write(inbox, "txt", name="a.txt", seed=1)
    r = sorter.process(p)
    p.write_text("a different, newer file")
    out = sorter.restore(r.id)
    assert Path(out["restored_to"]).name == "a (1).txt"
    assert p.read_text() == "a different, newer file"


def test_restore_errors(sorter, inbox):
    with pytest.raises(KeyError):
        sorter.restore(999)
    p = samples.write(inbox, "txt")
    r = sorter.process(p)
    Path(r.destination).unlink()
    with pytest.raises(FileNotFoundError):
        sorter.restore(r.id)


def test_stats(sorter, inbox):
    a = samples.write(inbox, "png", name="a.png", seed=1)
    png_size = a.stat().st_size
    (inbox / "a2.png").write_bytes(a.read_bytes())
    samples.write(inbox, "mp4", name="v.mp4")
    (inbox / "zero.txt").write_bytes(b"")
    sorter.sort_paths([inbox])
    s = sorter.stats()
    assert s["total"] == 4
    assert s["by_status"] == {"sorted": 2, "duplicate": 1, "quarantined": 1, "failed": 0}
    assert set(s["by_category"]) == {"Images", "Videos"}
    assert s["duplicates"]["count"] == 1
    assert s["duplicates"]["space_saved_bytes"] == png_size
    assert s["quarantine"] == {"count": 1, "reasons": {"empty": 1}}
    assert s["storage_bytes"] == sum(c["bytes"] for c in s["by_category"].values())


def test_search_filters(sorter, inbox):
    samples.write(inbox, "png", name="cat.png")
    samples.write(inbox, "mp4", name="dog.mp4")
    sorter.sort_paths([inbox])
    assert [r["name"] for r in sorter.search(type="png")] == ["cat.png"]
    assert [r["name"] for r in sorter.search(category="Videos")] == ["dog.mp4"]
    assert [r["name"] for r in sorter.search(name="DO")] == ["dog.mp4"]
    assert len(sorter.search(limit=1)) == 1


def test_locked_file_is_retried(sorter, inbox, monkeypatch):
    p = samples.write(inbox, "txt")
    real_move, calls = shutil.move, []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) < 3:
            raise PermissionError("file is locked")
        return real_move(src, dst)
    monkeypatch.setattr(mover.shutil, "move", flaky)
    r = sorter.process(p)
    assert r.status == "sorted" and len(calls) == 3


def test_permanently_locked_file_fails_but_is_logged(sorter, inbox, monkeypatch, workspace):
    p = samples.write(inbox, "txt")
    monkeypatch.setattr(mover.shutil, "move", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
    r = sorter.process(p)
    assert r.status == "failed" and "locked" in r.reason
    assert p.exists()  # left in place, not lost
    row = sorter.get(r.id)
    assert row["status"] == "failed" and row["new_path"] is None
    assert sorter.stats()["by_status"]["failed"] == 1
    # A failed file can be processed again later.
    monkeypatch.undo()
    assert sorter.process(p).status == "sorted"


def test_refuses_to_sort_its_own_files(sorter_factory, workspace):
    s = sorter_factory(inbox=str(workspace), catalog=str(workspace / "catalog.db"))
    samples.write(workspace, "txt", name="real.txt")
    results = s.sort_paths([workspace])
    assert [r.name for r in results if r.status == "sorted"] == ["real.txt"]
    assert (workspace / "catalog.db").exists()
    with pytest.raises(ValueError):
        s.process(workspace / "catalog.db")


def test_ignored_patterns_are_skipped_by_folder_scan(sorter, inbox):
    (inbox / "movie.mp4.part").write_bytes(samples.mp4())
    (inbox / "~$draft.docx").write_bytes(samples.docx())
    samples.write(inbox, "txt", name="keep.txt")
    assert [r.name for r in sorter.sort_paths([inbox])] == ["keep.txt"]


def test_reconcile_interrupted_moves(make_config, inbox):
    cfg = make_config()
    s = Sorter(cfg)
    p = samples.write(inbox, "txt", name="a.txt")
    dest_path = Path(cfg["destination"]) / "Documents" / "a.txt"
    # Simulate a crash: row written, file moved, but not finalized.
    fid = s.catalog.begin(name="a.txt", old_path=str(p), new_path=str(dest_path), status="sorted")
    q = samples.write(inbox, "txt", name="b.txt", seed=2)
    fid2 = s.catalog.begin(name="b.txt", old_path=str(q), new_path=str(dest_path.with_name("b.txt")),
                           status="sorted")
    dest_path.parent.mkdir(parents=True)
    shutil.move(p, dest_path)
    s.close()
    s2 = Sorter(cfg)
    try:
        assert s2.get(fid)["completed"] == 1 and s2.get(fid)["status"] == "sorted"
        assert s2.get(fid2)["status"] == "failed"
    finally:
        s2.close()


def test_structured_rotating_logs(sorter_factory, inbox, workspace):
    s = sorter_factory(logging={"max_bytes": 2000, "backups": 2})
    for i in range(30):
        samples.write(inbox, "txt", name=f"n{i}.txt", seed=i)
    (inbox / "zero.txt").write_bytes(b"")
    s.sort_paths([inbox])
    s.close()
    logs = sorted((workspace / "logs").glob("sortsmart.log*"))
    assert len(logs) == 3  # current + 2 rotated backups
    records = [json.loads(line) for f in logs for line in f.read_text("utf-8").splitlines()]
    levels = {r["level"] for r in records}
    assert {"INFO", "WARNING"} <= levels
    sorted_rec = next(r for r in records if r.get("event") == "sorted")
    assert {"time", "file", "destination", "hash", "type", "id"} <= set(sorted_rec)
    warn = next(r for r in records if r.get("event") == "quarantined")
    assert warn["level"] == "WARNING" and warn["reason"].startswith("empty")


def test_config_from_yaml_relative_paths(tmp_path):
    cfg = tmp_path / "conf" / "rules.yaml"
    cfg.parent.mkdir()
    cfg.write_text("inbox: ./in\ndestination: ./out\ncatalog: ./c.db\nlogging: {dir: ./logs}\n"
                   "rules:\ncategories:\n")
    s = Sorter(str(cfg))
    try:
        assert s.config.destination == (cfg.parent / "out").resolve()
        assert s.config.catalog_path == (cfg.parent / "c.db").resolve()
    finally:
        s.close()


def test_config_errors(tmp_path):
    with pytest.raises(ConfigError):
        Sorter({"no_such_key": 1})
    with pytest.raises(ConfigError):
        Sorter({"rules": [{"match": {}}]})
    with pytest.raises(ConfigError):
        Sorter(str(tmp_path / "missing.yaml"))


def test_default_destination_is_inside_inbox(tmp_path):
    s = Sorter({"inbox": str(tmp_path / "Downloads"), "catalog": str(tmp_path / "c.db"),
                "logging": {"dir": str(tmp_path / "logs")}})
    try:
        assert s.config.destination == (tmp_path / "Downloads" / "Sorted").resolve()
    finally:
        s.close()


def test_wait_for_stable_detects_growth(tmp_path):
    import threading
    p = tmp_path / "growing.bin"
    p.write_bytes(b"x")

    def grow():
        for _ in range(6):
            time.sleep(0.1)
            with open(p, "ab") as f:
                f.write(b"x" * 1000)
    t = threading.Thread(target=grow)
    t.start()
    start = time.monotonic()
    assert mover.wait_for_stable(p, interval=0.1, checks=3, timeout=10)
    t.join()
    assert time.monotonic() - start >= 0.6
    assert p.stat().st_size == 6001
    assert not mover.wait_for_stable(tmp_path / "gone", interval=0.05, checks=2, timeout=1)
