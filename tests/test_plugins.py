import json
import textwrap
from pathlib import Path

import samples
from sortsmart.plugins import Action, Detector

INVOICE_PLUGIN = '''\
from sortsmart.plugins import Detector

class InvoiceDetector(Detector):
    name = "invoice"

    def matches(self, file):
        return file.type == "pdf" and "invoice" in file.text.lower()

    def destination(self, file):
        return "Documents/Invoices"
'''


def write_plugin(workspace, name, code):
    folder = workspace / "plugins"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(textwrap.dedent(code))


def test_dropin_detector_from_plugins_folder(sorter_factory, workspace, inbox, dest):
    write_plugin(workspace, "invoice.py", INVOICE_PLUGIN)
    s = sorter_factory()
    assert s.plugins.describe()["detectors"] == ["invoice"]
    inv = inbox / "scan_0042.pdf"
    inv.write_bytes(samples.pdf("INVOICE #42 total due"))
    other = samples.write(inbox, "pdf", name="paper.pdf", seed=7)
    r = {x.name: x for x in s.sort_paths([inbox])}
    assert Path(r["scan_0042.pdf"].destination).parent == dest / "Documents" / "Invoices"
    assert r["scan_0042.pdf"].rule == "invoice"
    assert Path(r["paper.pdf"].destination).parent == dest / "Documents"
    assert other.name == "paper.pdf"


def test_plugin_detector_runs_before_yaml_rules(sorter_factory, inbox, dest):
    class Everything(Detector):
        name = "everything"

        def matches(self, file):
            return True

        def destination(self, file):
            return "Plugin"
    s = sorter_factory(plugin_objects=[Everything()],
                       rules=[{"match": {"type": "txt"}, "destination": "Rule"}])
    r = s.process(samples.write(inbox, "txt"))
    assert Path(r.destination).parent == dest / "Plugin"


def test_crashing_detector_is_disabled_and_core_keeps_running(sorter_factory, workspace, inbox, dest):
    write_plugin(workspace, "bad.py", '''
        from sortsmart.plugins import Detector
        class Bad(Detector):
            name = "bad"
            def matches(self, file):
                raise RuntimeError("boom")
            def destination(self, file):
                return "x"
    ''')
    s = sorter_factory()
    files = [samples.write(inbox, "txt", name=f"{i}.txt", seed=i) for i in range(3)]
    results = s.sort_paths([inbox])
    assert [r.status for r in results] == ["sorted"] * 3
    assert all(Path(r.destination).parent == dest / "Documents" for r in results)
    d = s.plugins.describe()
    assert d["detectors"] == []
    assert d["disabled"][0]["name"] == "bad" and "boom" in d["disabled"][0]["error"]
    assert not any(f.exists() for f in files)


def test_detector_with_bad_destination_is_disabled(sorter_factory, inbox, dest):
    class Escape(Detector):
        name = "escape"

        def matches(self, file):
            return True

        def destination(self, file):
            return "../../etc"
    s = sorter_factory(plugin_objects=[Escape()])
    r = s.process(samples.write(inbox, "txt"))
    assert Path(r.destination).parent == dest / "Documents"
    assert s.plugins.describe()["disabled"][0]["name"] == "escape"


def test_plugin_with_syntax_or_import_error_is_skipped(sorter_factory, workspace, inbox):
    write_plugin(workspace, "broken.py", "def oops(:\n")
    write_plugin(workspace, "missing.py", "import does_not_exist_anywhere\n")
    write_plugin(workspace, "_private.py", "raise SystemExit('should never be imported')\n")
    write_plugin(workspace, "good.py", INVOICE_PLUGIN)
    s = sorter_factory()
    d = s.plugins.describe()
    assert d["detectors"] == ["invoice"]
    assert sorted(x["name"] for x in d["disabled"]) == ["broken.py", "missing.py"]
    assert s.process(samples.write(inbox, "txt")).status == "sorted"


def test_actions_run_after_sort_and_quarantine(sorter_factory, inbox):
    seen = []

    class Recorder(Action):
        name = "recorder"

        def run(self, result, file):
            seen.append((result.status, file.name, Path(file.path).exists()))
    s = sorter_factory(plugin_objects=[Recorder()])
    samples.write(inbox, "txt", name="ok.txt")
    (inbox / "zero.pdf").write_bytes(b"")
    s.sort_paths([inbox])
    assert sorted(seen) == [("quarantined", "zero.pdf", True), ("sorted", "ok.txt", True)]


def test_action_events_filter_and_crash_isolation(sorter_factory, inbox):
    class OnlyQuarantine(Action):
        name = "q"
        events = ("quarantined",)
        calls = 0

        def run(self, result, file):
            OnlyQuarantine.calls += 1

    class Crashy(Action):
        name = "crashy"

        def run(self, result, file):
            raise ValueError("nope")
    s = sorter_factory(plugin_objects=[OnlyQuarantine(), Crashy()])
    samples.write(inbox, "txt", name="a.txt")
    samples.write(inbox, "txt", name="b.txt", seed=2)
    (inbox / "zero.pdf").write_bytes(b"")
    results = s.sort_paths([inbox])
    assert {r.status for r in results} == {"sorted", "quarantined"}
    assert OnlyQuarantine.calls == 1
    assert [d["name"] for d in s.plugins.describe()["disabled"]] == ["crashy"]


def test_builtin_invoice_and_screenshot(sorter_factory, inbox, dest):
    s = sorter_factory(plugins={"builtin": ["invoice", "screenshot"]})
    (inbox / "march.pdf").write_bytes(samples.pdf("Invoice number 7"))
    samples.write(inbox, "png", name="Screenshot 2026-10-28 101500.png")
    samples.write(inbox, "png", name="holiday.png", seed=5)
    r = {x.name: x for x in s.sort_paths([inbox])}
    assert Path(r["march.pdf"].destination).parent == dest / "Documents" / "Invoices"
    assert Path(r["Screenshot 2026-10-28 101500.png"].destination).parent == dest / "Images" / "Screenshots"
    assert Path(r["holiday.png"].destination).parent == dest / "Images"


def test_text_extraction_without_pypdf(tmp_path, monkeypatch):
    """Text extraction works even without pypdf installed."""
    import builtins
    from sortsmart.core.text import extract_text
    real_import = builtins.__import__

    def no_pypdf(name, *a, **k):
        if name == "pypdf":
            raise ImportError
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_pypdf)
    p = tmp_path / "x.pdf"
    p.write_bytes(samples.pdf("Invoice ACME 2026"))
    assert "Invoice ACME 2026" in extract_text(p, "pdf", False)
    d = tmp_path / "x.docx"
    d.write_bytes(samples.docx("hello docx world"))
    assert "hello docx world" in extract_text(d, "docx", False)


def test_slack_alert_posts_on_quarantine(sorter_factory, inbox, monkeypatch):
    import urllib.request
    posts = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout):
        posts.append((req.full_url, json.loads(req.data)))
        return FakeResp()
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    s = sorter_factory(plugins={"builtin": ["slack_alert"],
                                "settings": {"slack_alert": {"webhook_url": "https://hooks.example/x"}}})
    samples.write(inbox, "txt", name="fine.txt")
    (inbox / "bad.png").write_bytes(b"not a png at all")
    s.sort_paths([inbox])
    assert len(posts) == 1
    assert posts[0][0] == "https://hooks.example/x"
    assert "bad.png" in posts[0][1]["text"] and "quarantined" in posts[0][1]["text"]
    s.plugins.alert("disk low", {})
    assert "disk low" in posts[1][1]["text"]


def test_slack_alert_without_webhook_is_a_noop(sorter_factory, inbox, monkeypatch):
    monkeypatch.delenv("SORTSMART_SLACK_WEBHOOK", raising=False)
    s = sorter_factory(plugins={"builtin": ["slack_alert"]})
    (inbox / "bad.png").write_bytes(b"garbage")
    assert s.sort_paths([inbox])[0].status == "quarantined"
    assert s.plugins.describe()["disabled"] == []


def test_unknown_builtin_is_reported(sorter_factory):
    s = sorter_factory(plugins={"builtin": ["nope"]})
    assert s.plugins.describe()["disabled"][0]["name"] == "nope"


def test_plugins_can_be_turned_off(sorter_factory, workspace):
    write_plugin(workspace, "invoice.py", INVOICE_PLUGIN)
    s = sorter_factory(plugins={"enabled": False})
    assert s.plugins.describe()["detectors"] == []
