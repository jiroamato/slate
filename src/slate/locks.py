"""Advisory .lock files serializing store writers (mulch protocol, ported).

O_CREAT|O_EXCL exclusivity, 50ms retry, 5s timeout, >30s stale auto-clean.
Readers never lock.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_RETRY_INTERVAL_MS = 50
LOCK_TIMEOUT_MS = 5_000
LOCK_STALE_MS = 30_000


class LockTimeout(Exception):
    def __init__(self, lock_path: Path) -> None:
        super().__init__(
            f"timed out waiting for lock {lock_path}; if no other slate process is "
            "running, delete the lock file manually"
        )
        self.lock_path = lock_path


def _is_stale(lock_path: Path) -> bool:
    try:
        age_ms = (time.time() - lock_path.stat().st_mtime) * 1000
    except OSError:
        return False  # disappeared between checks — not stale, just gone
    return age_ms > LOCK_STALE_MS


@contextmanager
def file_lock(target: Path):
    lock_path = Path(f"{target}.lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_MS / 1000
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if _is_stale(lock_path):
                try:
                    lock_path.unlink()
                except OSError:
                    pass  # another process beat us to the cleanup
                continue
            if time.monotonic() >= deadline:
                raise LockTimeout(lock_path) from None
            time.sleep(LOCK_RETRY_INTERVAL_MS / 1000)
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass
