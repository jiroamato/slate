"""slate sync — validate the store, then commit store paths only.

The commit is scoped with `git commit -- <store>` so a user's staged work is
never swept into slate's commit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from slate import schema
from slate.commands._common import base_parser, git_root
from slate.output import SlateError, emit
from slate.store import Store, require_store, to_posix

DEFAULT_MESSAGE = "slate: update expertise"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8"
    )


def validate_store(store: Store) -> list[str]:
    problems: list[str] = []
    for domain in store.domains():
        records, warnings = store.read(domain)
        problems.extend(warnings)
        for record in records:
            for error in schema.validate_record(record):
                problems.append(f"{domain}/{record.get('id', '?')}: {error}")
    return problems


def run(argv: list[str]) -> int:
    parser = base_parser("sync", "Validate the store and commit it to git.")
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--no-validate", action="store_true", dest="no_validate")
    args = parser.parse_args(argv)

    store = require_store()
    root = git_root()
    if root is None:
        raise SlateError("not inside a git repository", hint="slate sync commits via git")

    if not args.no_validate:
        problems = validate_store(store)
        if problems:
            shown = problems[:10]
            more = f"\n…and {len(problems) - 10} more" if len(problems) > 10 else ""
            raise SlateError(
                "store validation failed:\n" + "\n".join(shown) + more,
                hint="fix the records above, or bypass with --no-validate",
                retry="slate doctor",
            )

    store_rel = to_posix(str(store.root.relative_to(root)))
    status = _git(root, "status", "--porcelain", "--", store_rel)
    if status.returncode != 0:
        raise SlateError(f"git status failed: {status.stderr.strip()}")
    if not status.stdout.strip():
        emit(
            {"committed": False, "validated": not args.no_validate},
            json_mode=args.json,
            command="sync",
            text="No changes to commit",
        )
        return 0

    add = _git(root, "add", "--", store_rel)
    if add.returncode != 0:
        raise SlateError(f"git add failed: {add.stderr.strip()}")
    commit = _git(root, "commit", "-m", args.message, "--", store_rel)
    if commit.returncode != 0:
        raise SlateError(f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}")

    emit(
        {"committed": True, "validated": not args.no_validate, "message": args.message},
        json_mode=args.json,
        command="sync",
        text=f"Committed store changes: {args.message}",
    )
    return 0
