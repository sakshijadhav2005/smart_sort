import json
import subprocess
import sys
from pathlib import Path

import yaml

import samples
from sortsmart.cli import main

ROOT = Path(__file__).resolve().parents[1]


def write_config(make_config, workspace, **extra):
    path = workspace / "rules.yaml"
    path.write_text(yaml.safe_dump(make_config(**extra)))
    return str(path)


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    return code, out


def test_sort_stats_search_restore_flow(make_config, workspace, inbox, capsys):
    cfg = write_config(make_config, workspace)
    a = samples.write(inbox, "png", name="a.png")
    (inbox / "a_copy.png").write_bytes(a.read_bytes())
    samples.write(inbox, "pdf", name="doc.pdf")
    (inbox / "fake.mp4").write_bytes(b"this is text, not a video")

    code, out = run(capsys, "sort", str(inbox), "--config", cfg)
    assert code == 0
    assert "2 sorted, 1 duplicate, 1 quarantined" in out or (
        "2 sorted" in out and "1 duplicate" in out and "1 quarantined" in out)

    code, out = run(capsys, "--config", cfg, "stats", "--json")
    stats = json.loads(out)
    assert stats["by_status"]["sorted"] == 2 and stats["duplicates"]["count"] == 1

    code, out = run(capsys, "stats", "--config", cfg)
    assert "Files processed: 4" in out and "Quarantine reasons" in out

    code, out = run(capsys, "search", "--config", cfg, "--status", "quarantined", "--json")
    rows = json.loads(out)
    assert [r["name"] for r in rows] == ["fake.mp4"]

    code, out = run(capsys, "restore", "--last", "10", "--config", cfg)
    assert code == 0 and out.count("->") == 4
    assert sorted(p.name for p in inbox.iterdir()) == ["a.png", "a_copy.png", "doc.pdf", "fake.mp4"]

    code, out = run(capsys, "restore", "--last", "10", "--config", cfg)
    assert "nothing to restore" in out


def test_restore_by_id_and_errors(make_config, workspace, inbox, capsys):
    cfg = write_config(make_config, workspace)
    samples.write(inbox, "txt", name="n.txt")
    run(capsys, "sort", str(inbox), "-c", cfg)
    code, out = run(capsys, "restore", "--id", "1", "-c", cfg)
    assert code == 0 and "#1: n.txt" in out
    code, out = run(capsys, "restore", "--id", "1", "42", "-c", cfg)
    assert code == 1 and "already restored" in out and "#42: ERROR" in out


def test_classify_json(make_config, workspace, inbox, capsys):
    cfg = write_config(make_config, workspace)
    p = samples.write(inbox, "jpg", name="photo")
    code, out = run(capsys, "classify", str(p), "--json", "-c", cfg)
    data = json.loads(out)[0]
    assert data["type"] == "jpg" and data["valid"] and len(data["hash"]) == 64
    assert p.exists()


def test_health(make_config, workspace, capsys):
    cfg = write_config(make_config, workspace)
    code, out = run(capsys, "health", "--json", "-c", cfg)
    h = json.loads(out)
    assert code == 0 and h["status"] == "ok" and h["catalog"]["status"] == "ok"


def test_health_reports_low_disk(make_config, workspace, capsys):
    cfg = write_config(make_config, workspace, health={"min_free_mb": 10**12})
    code, out = run(capsys, "health", "-c", cfg)
    assert code == 2 and "low disk space" in out


def test_config_error_exit_code(workspace, capsys):
    bad = workspace / "bad.yaml"
    bad.write_text("bogus_key: 1\n")
    assert main(["stats", "-c", str(bad)]) == 2
    assert "unknown config keys" in capsys.readouterr().err


def test_missing_path(make_config, workspace, capsys):
    cfg = write_config(make_config, workspace)
    assert main(["sort", str(workspace / "nope"), "-c", cfg]) == 1


def test_env_config(make_config, workspace, inbox, capsys, monkeypatch):
    cfg = write_config(make_config, workspace)
    monkeypatch.setenv("SORTSMART_CONFIG", cfg)
    samples.write(inbox, "txt")
    assert main(["sort", str(inbox)]) == 0
    assert (workspace / "sorted" / "Documents").is_dir()


def test_python_dash_m_entry_point(make_config, workspace, inbox):
    cfg = write_config(make_config, workspace)
    samples.write(inbox, "mp3", name="song.mp3")
    proc = subprocess.run([sys.executable, "-m", "sortsmart", "sort", str(inbox), "-c", cfg],
                          cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "sorted" in proc.stdout and (workspace / "sorted" / "Audio" / "song.mp3").exists()
    proc = subprocess.run([sys.executable, "-m", "sortsmart", "--version"], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)
    assert proc.stdout.strip() == "sortsmart 0.1.0"
