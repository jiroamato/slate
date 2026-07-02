"""Read-only git context: evidence auto-fill and stop-gate diff stats."""

from __future__ import annotations

import subprocess
from pathlib import Path

from slate.store import to_posix


def _git(args: list[str], cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def head_commit(cwd: Path | None = None) -> str | None:
    out = _git(["rev-parse", "HEAD"], cwd)
    return out.strip() if out else None


def changed_files(cwd: Path | None = None) -> list[str]:
    """Union of staged and unstaged changed paths, POSIX, sorted."""
    files: set[str] = set()
    for args in (["diff", "--name-only", "--cached"], ["diff", "--name-only"]):
        out = _git(args, cwd)
        if out:
            files.update(to_posix(line) for line in out.splitlines() if line.strip())
    return sorted(files)


def diff_stats(cwd: Path | None = None) -> tuple[int, int]:
    """(files changed, lines added+deleted) for the working tree vs HEAD."""
    out = _git(["diff", "HEAD", "--numstat"], cwd)
    if not out:
        return (0, 0)
    files = 0
    lines = 0
    for row in out.splitlines():
        parts = row.split("\t")
        if len(parts) < 3:
            continue
        files += 1
        for cell in parts[:2]:
            if cell.isdigit():
                lines += int(cell)
    return (files, lines)
