"""Session state and ack markers in the platform temp dir.

State file: <tempdir>/slate/<session_id>.json — session-start timestamp, seen
files, injected record ids. Ack marker: <tempdir>/slate/ack-<repo_key>.json.
Known edge (documented in the spec): two simultaneous sessions in the same
repo share ack markers.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
import traceback
from pathlib import Path

from slate.store import to_posix


def slate_tmp_dir() -> Path:
    directory = Path(tempfile.gettempdir()) / "slate"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def state_path(session_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id) or "unknown"
    return slate_tmp_dir() / f"{safe}.json"


def load_state(session_id: str) -> dict | None:
    path = state_path(session_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def new_state(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "started_at": time.time(),
        "seen_files": [],
        "injected_ids": [],
        "stop_blocked": False,
    }


def save_state(state: dict) -> None:
    path = state_path(state["session_id"])
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(state, fh)


def repo_key(store_root: Path) -> str:
    canonical = to_posix(str(store_root.resolve())).lower()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def ack_path(store_root: Path) -> Path:
    return slate_tmp_dir() / f"ack-{repo_key(store_root)}.json"


def write_ack(store_root: Path, reason: str) -> dict:
    marker = {"ts": time.time(), "reason": reason}
    with open(ack_path(store_root), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(marker, fh)
    return marker


def read_ack(store_root: Path) -> dict | None:
    try:
        return json.loads(ack_path(store_root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def log_hook_error() -> None:
    """Fail-open support: append the current exception to the hook error log."""
    try:
        with open(slate_tmp_dir() / "hook-errors.log", "a", encoding="utf-8", newline="\n") as fh:
            fh.write(traceback.format_exc() + "\n")
    except OSError:
        pass
