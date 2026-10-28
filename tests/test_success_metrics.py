"""One test per success metric in the PRD."""
import json
import random
import time
from pathlib import Path

import pytest
import yaml

import samples
from sortsmart import Sorter
from sortsmart.cli import main
from sortsmart.core.detection import TYPES

KINDS = sorted(samples.CATALOG)
ROOT = Path(__file__).resolve().parents[1]


def build_mixed_set(folder: Path, n=500, seed=1):
    """n distinct valid files across every supported kind; a third of them
    without extensions, so only content can identify them."""
    rng = random.Random(seed)
    expected = {}
    for i in range(n):
        kind = KINDS[i % len(KINDS)]
        _, ext, typ, category = samples.CATALOG[kind]
        name = f"file{i:03d}" if rng.random() < 0.33 else f"file{i:03d}.{ext}"
        samples.write(folder, kind, name=name, seed=i)
        expected[name] = (typ, category)
    return expected


def test_metric_98pct_classified_correctly_on_500_mixed_files(sorter, inbox):
    expected = build_mixed_set(inbox)
    results = sorter.sort_paths([inbox])
    assert len(results) == 500
    correct = sum((r.type, r.category) == expected[r.name] for r in results
                  if r.status in ("sorted", "duplicate"))
    accuracy = correct / 500
    print(f"\naccuracy on mixed 500-file set: {accuracy:.1%}")
    assert accuracy >= 0.98


def test_metric_100pct_renamed_files_detected(sorter, inbox):
    """Every file given another format's extension is caught and quarantined."""
    renamed = 0
    for i, kind in enumerate(KINDS):
        real_type = TYPES[samples.CATALOG[kind][2]]
        for offset in range(1, len(KINDS)):
            wrong_ext = samples.CATALOG[KINDS[(i + offset) % len(KINDS)]][1]
            if wrong_ext not in real_type.extensions and not (
                    real_type.is_text and wrong_ext in ("txt", "csv", "json", "html", "md")):
                break
        samples.write(inbox, kind, name=f"renamed_{kind}.{wrong_ext}", seed=i)
        renamed += 1
    results = sorter.sort_paths([inbox])
    caught = [r for r in results if r.status == "quarantined" and r.reason.startswith("mismatch")]
    print(f"\nrenamed files detected: {len(caught)}/{renamed}")
    assert len(caught) == renamed == len(KINDS)


def test_metric_under_5s_per_file(sorter, inbox):
    build_mixed_set(inbox, n=100, seed=2)
    worst = 0.0
    for p in sorter.iter_folder(inbox):
        t = time.perf_counter()
        sorter.process(p)
        worst = max(worst, time.perf_counter() - t)
    print(f"\nslowest file: {worst * 1000:.1f} ms")
    assert worst < 5


def test_metric_under_5s_per_large_file(sorter, inbox):
    big = inbox / "big.bin"
    with open(big, "wb") as f:
        f.write(samples.mp4())
        f.write(b"\0" * (200 * 2**20))  # 200 MB video
    t = time.perf_counter()
    r = sorter.process(big)
    assert r.status == "sorted" and time.perf_counter() - t < 5


def test_metric_zero_duplicates_stored_twice(sorter, inbox, dest):
    build_mixed_set(inbox, n=60, seed=3)
    for p in list(inbox.iterdir())[:30]:  # copy half of them, some twice
        (inbox / f"copy1_{p.name}").write_bytes(p.read_bytes())
        (inbox / f"copy2_{p.name}").write_bytes(p.read_bytes())
    sorter.sort_paths([inbox])
    contents = [p.read_bytes() for p in dest.rglob("*")
                if p.is_file() and not {"Duplicates", "Quarantine"} & set(p.parts)]
    assert len(contents) == len(set(contents)) == 60


def test_metric_100pct_moved_files_restorable(sorter, inbox):
    build_mixed_set(inbox, n=80, seed=4)
    (inbox / "zero.txt").write_bytes(b"")
    (inbox / "liar.pdf").write_bytes(samples.exe())
    (inbox / "dupe_file000").write_bytes(next(inbox.glob("file000*")).read_bytes())
    before = {p.name: p.read_bytes() for p in inbox.iterdir()}
    results = sorter.sort_paths([inbox])
    assert {r.status for r in results} == {"sorted", "quarantined", "duplicate"}
    assert not any(inbox.iterdir())
    restored = sorter.restore_last(len(results))
    assert all("error" not in r for r in restored)
    after = {p.name: p.read_bytes() for p in inbox.iterdir()}
    assert after == before


def _norm(d: dict, root: Path):
    rel = Path(d["destination"]).resolve().relative_to(root.resolve()).parent.as_posix()
    return (d["status"], d["type"], d["category"], d["hash"], d["reason"], rel)


@pytest.mark.parametrize("kind_or_file", ["png", "pdf", "docx", "mp4", "zero", "fake", "invoice"])
def test_metric_same_result_from_cli_and_library(tmp_path, kind_or_file, capsys):
    if kind_or_file == "zero":
        name, data = "empty.doc", b""
    elif kind_or_file == "fake":
        name, data = "song.mp3", samples.CATALOG["png"][0](1)
    elif kind_or_file == "invoice":
        name, data = "bill.pdf", samples.pdf("INVOICE 99")
    else:
        name, data = f"sample.{samples.CATALOG[kind_or_file][1]}", samples.CATALOG[kind_or_file][0](1)

    def config(sub):
        base = tmp_path / sub
        (base / "inbox").mkdir(parents=True)
        return base, {"inbox": str(base / "inbox"), "destination": str(base / "sorted"),
                      "catalog": str(base / "c.db"), "logging": {"dir": str(base / "logs")},
                      "date_subfolders": True, "date_source": "processed",
                      "plugins": {"builtin": ["invoice"], "dir": str(base / "plugins")}}

    # library
    base, cfg = config("lib")
    (base / "inbox" / name).write_bytes(data)
    with Sorter(cfg) as s:
        lib = _norm(s.process(base / "inbox" / name).to_dict(), base / "sorted")
    # CLI
    base, cfg = config("cli")
    (base / "inbox" / name).write_bytes(data)
    (base / "rules.yaml").write_text(yaml.safe_dump(cfg))
    capsys.readouterr()
    main(["sort", str(base / "inbox" / name), "--json", "-c", str(base / "rules.yaml")])
    cli = _norm(json.loads(capsys.readouterr().out)[0], base / "sorted")
    assert lib == cli


def test_metric_new_detector_plugin_under_20_lines(sorter_factory, workspace, inbox, dest):
    plugin = (ROOT / "plugins" / "README.md").read_text().split("```python\n")[1].split("```")[0]
    assert len(plugin.strip().splitlines()) < 20
    (workspace / "plugins").mkdir()
    (workspace / "plugins" / "invoice.py").write_text(plugin)
    s = sorter_factory()
    (inbox / "a.pdf").write_bytes(samples.pdf("Invoice for October"))
    r = s.process(inbox / "a.pdf")
    assert Path(r.destination).parent == dest / "Documents" / "Invoices"
    builtin = ROOT / "sortsmart" / "plugins" / "builtin" / "invoice.py"
    assert len(builtin.read_text().strip().splitlines()) < 20


def test_metric_crashing_plugin_never_stops_core(sorter_factory, workspace, inbox):
    (workspace / "plugins").mkdir()
    (workspace / "plugins" / "chaos.py").write_text(
        "from sortsmart.plugins import Detector, Action\n"
        "class D(Detector):\n    name='d'\n"
        "    def matches(self, f): raise MemoryError('fake')\n"
        "    def destination(self, f): return 'x'\n"
        "class A(Action):\n    name='a'\n"
        "    def run(self, r, f): 1/0\n"
        "class B(Action):\n    name='b'\n"
        "    def __init__(self): raise RuntimeError('ctor')\n"
        "class S(Detector):\n    name='s'\n"
        "    def setup(self, settings): raise KeyError('cfg')\n")
    s = sorter_factory()
    build_mixed_set(inbox, n=40, seed=5)
    results = s.sort_paths([inbox])
    assert {r.status for r in results} == {"sorted"} and len(results) == 40
    assert sorted(d["name"] for d in s.plugins.describe()["disabled"]) == ["a", "b", "d", "s"]
