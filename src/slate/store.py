"""Store discovery and JSONL storage — the single choke point for store file I/O.

Portability contract: every file this module writes is UTF-8 with \\n newlines
and POSIX path separators, on every OS. The tolerant reader skips malformed
lines with a warning (one corrupt line never bricks a domain) and passes
unknown-type records through untouched.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from slate import schema
from slate.locks import file_lock
from slate.output import EXIT_NO_STORE, SlateError

ARCHIVE_BANNER = "# ARCHIVED — not for active use. Run `slate restore <id>` to revive."
_REPLACE_RETRIES = 10
_REPLACE_BACKOFF_S = 0.02


def to_posix(path: str) -> str:
    """Normalize path separators to POSIX for storage and comparison."""
    return path.replace("\\", "/")


def dumps_record(record: dict) -> str:
    """Compact JSON, non-ASCII preserved — byte-compatible with JSON.stringify."""
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False)


def _atomic_write(path: Path, content: str) -> None:
    """Same-directory temp file + os.replace, with a bounded retry for the
    Windows PermissionError when another process momentarily holds the target."""
    tmp = path.with_name(f"{path.name}.tmp.{uuid.uuid4().hex[:8]}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    try:
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


class Store:
    def __init__(self, root: Path, kind: str) -> None:
        self.root = root
        self.kind = kind  # "slate" | "mulch"

    @property
    def expertise_dir(self) -> Path:
        return self.root / "expertise"

    @property
    def archive_dir(self) -> Path:
        return self.root / "archive"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    def domain_path(self, domain: str) -> Path:
        return self.expertise_dir / f"{domain}.jsonl"

    def archive_path(self, domain: str) -> Path:
        return self.archive_dir / f"{domain}.jsonl"

    def config_path(self) -> Path | None:
        for name in ("slate.config.yaml", "mulch.config.yaml"):
            candidate = self.root / name
            if candidate.is_file():
                return candidate
        return None

    def domains(self) -> list[str]:
        if not self.expertise_dir.is_dir():
            return []
        return sorted(p.stem for p in self.expertise_dir.glob("*.jsonl"))

    # --- reading ---

    def _display_path(self, path: Path) -> str:
        """Repo-relative POSIX path for warnings (portable, snapshot-stable)."""
        try:
            return to_posix(str(path.relative_to(self.root.parent)))
        except ValueError:
            return to_posix(str(path))

    def _read_file(self, path: Path) -> tuple[list[dict], list[str]]:
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                lines = fh.read().split("\n")
        except FileNotFoundError:
            return [], []
        records: list[dict] = []
        warnings: list[str] = []
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as err:
                preview = stripped[:77] + "..." if len(stripped) > 80 else stripped
                warnings.append(f"{self._display_path(path)}:{lineno}: malformed JSONL ({err.msg}). Line: {preview}")
                continue
            if isinstance(raw, dict):
                records.append(raw)
            else:
                warnings.append(f"{self._display_path(path)}:{lineno}: expected a JSON object")
        return records, warnings

    def read(self, domain: str) -> tuple[list[dict], list[str]]:
        return self._read_file(self.domain_path(domain))

    def read_archive(self, domain: str) -> tuple[list[dict], list[str]]:
        return self._read_file(self.archive_path(domain))

    def read_for_rewrite(self, domain: str) -> list[dict]:
        """Read a domain that is about to be rewritten whole-file.

        Refuses domains with unreadable lines: the tolerant reader skips them,
        so a rewrite would silently drop those bytes from disk.
        """
        records, warnings = self.read(domain)
        if warnings:
            raise SlateError(
                f"domain '{domain}' has {len(warnings)} unreadable line(s); "
                "rewriting would silently drop them",
                hint=warnings[0],
                retry="slate doctor",
            )
        return records

    # --- writing ---

    def append(self, domain: str, record: dict) -> None:
        if not record.get("id"):
            record["id"] = schema.generate_id(record)
        path = self.domain_path(domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path):
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(dumps_record(record) + "\n")

    def rewrite(self, domain: str, records: list[dict]) -> None:
        """Locked whole-file rewrite (edit/delete/move/prune)."""
        for record in records:
            if not record.get("id"):
                record["id"] = schema.generate_id(record)
        path = self.domain_path(domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "".join(dumps_record(r) + "\n" for r in records)
        with file_lock(path):
            _atomic_write(path, content)

    def append_archive(self, domain: str, records: list[dict]) -> None:
        path = self.archive_path(domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path):
            needs_banner = not path.exists() or path.stat().st_size == 0
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                if needs_banner:
                    fh.write(ARCHIVE_BANNER + "\n")
                for record in records:
                    fh.write(dumps_record(record) + "\n")

    def latest_mtime(self) -> float | None:
        """Newest mtime across live store files (used by the stop-gate)."""
        newest: float | None = None
        for directory in (self.expertise_dir, self.archive_dir):
            if not directory.is_dir():
                continue
            for path in directory.glob("*.jsonl"):
                mtime = path.stat().st_mtime
                if newest is None or mtime > newest:
                    newest = mtime
        return newest


def resolve_id(records: list[dict], identifier: str, *, domain: str = "") -> tuple[int, dict]:
    """Resolve mx-abc123 / abc123 / unique prefix to (index, record)."""
    hash_part = identifier[3:] if identifier.startswith("mx-") else identifier
    target = f"mx-{hash_part}"
    for index, record in enumerate(records):
        if record.get("id") == target:
            return index, record
    matches = [(i, r) for i, r in enumerate(records) if (r.get("id") or "").startswith(target)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ids = ", ".join(r.get("id", "?") for _, r in matches)
        raise SlateError(
            f"ambiguous identifier '{identifier}' matches {len(matches)} records: {ids}",
            code="ambiguous_id",
            hint="use more characters to disambiguate",
        )
    raise SlateError(
        f"record '{identifier}' not found" + (f" in domain '{domain}'" if domain else ""),
        code="not_found",
        hint="list records to see valid ids",
        retry=f"slate query {domain}".strip(),
    )


def find_store(start: Path | None = None) -> Store | None:
    """Walk up from start (default cwd) to the git root, preferring .slate/ over .mulch/."""
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        for name, kind in ((".slate", "slate"), (".mulch", "mulch")):
            candidate = directory / name
            if candidate.is_dir():
                return Store(candidate, kind)
        if (directory / ".git").exists():
            return None  # reached the repo root without finding a store
    return None


def require_store(start: Path | None = None) -> Store:
    found = find_store(start)
    if found is None:
        raise SlateError(
            "no slate store found (looked for .slate/ or .mulch/ up to the git root)",
            code="no_store",
            exit_code=EXIT_NO_STORE,
            hint="initialize a store in the repo root first",
            retry="slate init",
        )
    return found
