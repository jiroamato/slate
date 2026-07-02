"""Advisory .lock files serializing store writers (mulch protocol, ported).

O_CREAT|O_EXCL exclusivity, 50ms retry, 5s timeout, >30s stale auto-clean.
Readers never lock.
"""

from __future__ import annotations

import os
import time
import uuid
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


def _steal_stale_lock(lock_path: Path) -> None:
    """Remove a stale lock without the unlink race.

    A bare unlink lets two contenders that both judged the lock stale delete
    each other's freshly created replacement, breaking mutual exclusion.
    Instead: atomically rename the lock to a unique name (exactly one
    contender wins; rename preserves mtime), re-check staleness on the stolen
    file, and if it turns out to be live — the holder swapped it in between
    our check and the rename — restore it with a no-clobber link.
    """
    doomed = lock_path.with_name(f"{lock_path.name}.stale-{uuid.uuid4().hex[:8]}")
    try:
        os.rename(lock_path, doomed)
    except OSError:
        return  # another contender won the steal, or the lock vanished
    if _is_stale(doomed):
        try:
            doomed.unlink()
        except OSError:
            pass
        return
    try:
        os.link(doomed, lock_path)  # fails if a newer lock already exists
    except OSError:
        pass
    try:
        doomed.unlink()
    except OSError:
        pass


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
                _steal_stale_lock(lock_path)
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
