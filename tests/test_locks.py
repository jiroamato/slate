import os
import time

import pytest

from slate import locks
from slate.locks import LockTimeout, file_lock


def test_lock_created_and_released(tmp_path):
    target = tmp_path / "data.jsonl"
    lock_path = tmp_path / "data.jsonl.lock"
    with file_lock(target):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_lock_released_on_exception(tmp_path):
    target = tmp_path / "data.jsonl"
    with pytest.raises(RuntimeError):
        with file_lock(target):
            raise RuntimeError("boom")
    assert not (tmp_path / "data.jsonl.lock").exists()


def test_contended_lock_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, "LOCK_TIMEOUT_MS", 200)
    monkeypatch.setattr(locks, "LOCK_RETRY_INTERVAL_MS", 10)
    target = tmp_path / "data.jsonl"
    (tmp_path / "data.jsonl.lock").touch()  # held by "another process", fresh mtime
    start = time.monotonic()
    with pytest.raises(LockTimeout):
        with file_lock(target):
            pass
    assert time.monotonic() - start < 2.0


def test_stale_lock_is_cleaned_and_acquired(tmp_path):
    target = tmp_path / "data.jsonl"
    stale = tmp_path / "data.jsonl.lock"
    stale.touch()
    old = time.time() - 31
    os.utime(stale, (old, old))
    with file_lock(target):
        assert stale.exists()  # re-created by us after stale cleanup
    assert not stale.exists()


def test_default_protocol_constants():
    assert locks.LOCK_RETRY_INTERVAL_MS == 50
    assert locks.LOCK_TIMEOUT_MS == 5000
    assert locks.LOCK_STALE_MS == 30000
