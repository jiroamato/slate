"""Dir-anchor normalization and matching (mulch parity, POSIX both sides)."""

from __future__ import annotations

import re

from slate.output import SlateError
from slate.store import to_posix

_ABSOLUTE_RE = re.compile(r"^[a-zA-Z]:[\\/]")


def normalize_dir_anchor(value: str) -> str:
    v = value.strip()
    if v in ("", "."):
        return ""
    v = to_posix(v).rstrip("/")
    if v.startswith("./"):
        v = v[2:].rstrip("/")
    return "" if v in ("", ".") else v


def assert_writable_dir_anchor(raw: str) -> None:
    v = raw.strip()
    if not v:
        return
    if _ABSOLUTE_RE.match(v) or v.startswith(("/", "\\")):
        raise SlateError(
            f'dir-anchor "{raw}" is an absolute path',
            hint='use a project-root-relative path like "src/utils"',
        )
    if ".." in to_posix(v).split("/"):
        raise SlateError(
            f'dir-anchor "{raw}" contains ".." (parent traversal)',
            hint="anchors must stay inside the project root",
        )


def file_lives_under_dir(file: str, directory: str) -> bool:
    f = to_posix(file)
    d = normalize_dir_anchor(directory)
    if d == "":
        return True
    return f == d or f.startswith(d + "/")


def infer_dir_anchors(files: list[str], threshold: int = 3) -> list[str]:
    """Directories that parent >= threshold changed files, deduped and sorted."""
    counts: dict[str, int] = {}
    for raw in files:
        f = to_posix(raw)
        idx = f.rfind("/")
        if idx <= 0:
            continue
        directory = f[:idx]
        counts[directory] = counts.get(directory, 0) + 1
    return sorted(d for d, c in counts.items() if c >= threshold)
