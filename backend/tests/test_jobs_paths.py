import sys
import threading
import time
from pathlib import Path

from birdedit import winpath
from birdedit.jobs import JobManager


def test_failure_in_one_item_does_not_stop_batch():
    jm = JobManager()

    def work(job, item):
        if item == 2:
            raise ValueError("boom")
        return {"item": item, "ok": True, "message": "ok"}

    job = jm.submit("t", "test", [1, 2, 3], work)
    while job.finished is None:
        time.sleep(0.01)
    assert job.status == "done" and [r["ok"] for r in job.results] == [True, False, True]
    jm.shutdown()


def test_cancellation_stops_remaining_items():
    jm = JobManager()
    gate = threading.Event()

    def work(job, item):
        gate.wait(2)
        if job.cancelled:
            raise InterruptedError
        return {"item": item, "ok": True, "message": "ok"}

    job = jm.submit("t", "test", list(range(10)), work)
    time.sleep(0.05)
    assert jm.cancel(job.id)
    gate.set()
    while job.finished is None:
        time.sleep(0.01)
    assert job.status == "cancelled" and job.done < 10
    assert job.results[0]["message"] == "Cancelled"
    jm.shutdown()


def test_safe_stem():
    assert winpath.safe_stem('bad:name*?"<>|') == "bad_name______"
    assert winpath.safe_stem("CON") == "_CON"
    assert winpath.safe_stem("lpt1.backup") == "_lpt1.backup"
    assert winpath.safe_stem("trailing dots... ") == "trailing dots"
    assert winpath.safe_stem("") == "photo"
    assert winpath.safe_stem("Héron cendré 鷺") == "Héron cendré 鷺"
    assert len(winpath.safe_stem("x" * 400)) <= 120


def test_reserve_unique_path_never_overwrites(tmp_path):
    folder = tmp_path / "with space ü"
    folder.mkdir()
    (folder / "bird_edited.jpg").write_bytes(b"existing")
    p1 = winpath.reserve_unique_path(folder, "bird_edited", ".jpg")
    p2 = winpath.reserve_unique_path(folder, "bird_edited", ".jpg")
    assert p1.name == "bird_edited (2).jpg" and p2.name == "bird_edited (3).jpg"
    assert (folder / "bird_edited.jpg").read_bytes() == b"existing"


def test_long_windows_path_prefix(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    import ntpath
    monkeypatch.setattr(winpath.os, "path", ntpath)
    long = "C:\\Users\\Photographer\\Pictures\\" + "\\".join(["very long folder name"] * 12) + "\\DSC_0001.NEF"
    assert winpath.io_path(long).startswith("\\\\?\\C:\\")
    assert winpath.io_path("C:\\short\\a.NEF") == "C:\\short\\a.NEF"
    unc = "\\\\server\\share\\" + "x" * 250 + "\\a.NEF"
    assert winpath.io_path(unc).startswith("\\\\?\\UNC\\server\\share")


def test_data_dir_is_per_user_on_windows(monkeypatch):
    from birdedit import config
    monkeypatch.delenv("BIRDEDIT_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\Ana\\AppData\\Local")
    assert str(config.default_data_dir()).endswith("BirdPhotoEditor")
    assert "Program Files" not in str(config.default_data_dir())
