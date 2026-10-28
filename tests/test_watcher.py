import threading
import time
from pathlib import Path

import pytest

import samples
from sortsmart.watcher import Watcher


def wait_until(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def watcher(sorter):
    w = Watcher(sorter, rescan_interval=2).start()
    yield w
    w.stop()


def test_new_file_sorted_within_5_seconds(watcher, inbox, dest):
    data = samples.CATALOG["jpg"][0](1)
    tmp = inbox.parent / "staging.jpg"
    tmp.write_bytes(data)
    start = time.monotonic()
    tmp.replace(inbox / "photo.jpg")
    target = dest / "Images" / "photo.jpg"
    assert wait_until(target.exists, timeout=5)
    assert time.monotonic() - start < 5
    assert target.read_bytes() == data


def test_existing_files_are_sorted_on_start(sorter, inbox, dest):
    samples.write(inbox, "pdf", name="before.pdf")
    with Watcher(sorter):
        assert wait_until((dest / "Documents" / "before.pdf").exists)


def test_waits_for_file_to_finish_writing(watcher, inbox, dest):
    """A file being copied slowly must not be processed half-written."""
    data = samples.CATALOG["png"][0](7)
    path = inbox / "slow.png"

    def slow_copy():
        with open(path, "wb") as f:
            for i in range(0, len(data), 10):
                f.write(data[i:i + 10])
                f.flush()
                time.sleep(0.03)
    t = threading.Thread(target=slow_copy)
    t.start()
    t.join()
    target = dest / "Images" / "slow.png"
    assert wait_until(target.exists)
    assert target.read_bytes() == data
    assert not (dest / "Quarantine").exists()


def test_partial_download_names_are_ignored(watcher, inbox, dest):
    (inbox / "movie.mp4.crdownload").write_bytes(samples.mp4())
    samples.write(inbox, "txt", name="marker.txt")
    assert wait_until((dest / "Documents" / "marker.txt").exists)
    time.sleep(0.5)
    assert (inbox / "movie.mp4.crdownload").exists()
    # When the browser renames it, it gets sorted.
    (inbox / "movie.mp4.crdownload").rename(inbox / "movie.mp4")
    assert wait_until((dest / "Videos" / "movie.mp4").exists)


def test_restored_files_are_not_resorted(watcher, sorter, inbox, dest):
    samples.write(inbox, "txt", name="keep-here.txt")
    target = dest / "Documents" / "keep-here.txt"
    assert wait_until(target.exists)
    row = sorter.search(name="keep-here")[0]
    sorter.restore(row["id"])
    time.sleep(1.5)
    assert (inbox / "keep-here.txt").exists() and not target.exists()


def test_destination_inside_inbox_is_not_rewatched(sorter_factory, workspace, inbox):
    s = sorter_factory(destination=str(inbox / "Sorted"), recursive=True)
    with Watcher(s, rescan_interval=1) as w:
        samples.write(inbox, "gif", name="anim.gif")
        target = inbox / "Sorted" / "Images" / "anim.gif"
        assert wait_until(target.exists)
        time.sleep(1.5)  # a rescan happens; the sorted file must stay put
        assert target.exists()
        assert s.stats()["total"] == 1 and w.queue_size == 0


def test_burst_of_100_files_each_sorted_within_5_seconds(sorter_factory, inbox, dest):
    """Stability waits overlap, so a burst is not serialized behind them.
    Uses the production stability settings (0.5 s x 2 checks)."""
    s = sorter_factory(stability={"interval": 0.5, "checks": 2, "timeout": 300})
    with Watcher(s):
        time.sleep(0.2)
        start = time.monotonic()
        for i in range(100):
            samples.write(inbox, "txt", name=f"note{i}.txt", seed=i)
        assert wait_until(lambda: len(list((dest / "Documents").glob("*.txt"))) == 100, timeout=5)
        elapsed = time.monotonic() - start
    print(f"\n100-file burst sorted in {elapsed:.2f}s")
    assert s.stats()["by_status"]["sorted"] == 100


def test_file_rewritten_while_settling_is_sorted_once_complete(watcher, inbox, dest):
    path = inbox / "report.pdf"
    data = samples.pdf("final version")
    path.write_bytes(data[:50])  # first partial write: would be corrupt
    for i in range(1, 6):
        time.sleep(0.08)
        path.write_bytes(data[: 50 + i * (len(data) - 50) // 5])
    target = dest / "Documents" / "report.pdf"
    assert wait_until(target.exists)
    assert target.read_bytes() == data
    assert not (dest / "Quarantine").exists()


def test_health_alert_fires_once(sorter_factory, workspace):
    s = sorter_factory(health={"min_free_mb": 10**12})
    alerts = []
    s.plugins.alert = lambda msg, details: alerts.append(msg)
    with Watcher(s) as w:
        r1 = w.check_health()
        w.check_health()
        assert r1["status"] == "degraded" and r1["queue"]["running"]
    assert len(alerts) == 1 and "low disk space" in alerts[0]


def test_stuck_files_reported(sorter_factory, inbox):
    s = sorter_factory(health={"stuck_after": -1})
    samples.write(inbox, "txt", name="waiting.txt")
    h = s.health()
    assert h["stuck_count"] == 1 and h["stuck_files"][0].endswith("waiting.txt")


def test_watch_requires_folder(sorter_factory):
    s = sorter_factory(inbox=None)
    with pytest.raises(ValueError):
        Watcher(s)
