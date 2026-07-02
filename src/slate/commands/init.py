"""slate init — create the store, config, and merge=union gitattributes."""

from __future__ import annotations

from pathlib import Path

from slate.commands._common import base_parser, git_root
from slate.output import emit
from slate.store import to_posix

GITATTRIBUTES_LINE = ".slate/expertise/*.jsonl merge=union"

DEFAULT_CONFIG_YAML = """\
# slate store configuration (mulch-compatible schema)
version: "1"
schema_version: 1
governance:
  max_entries: 100
  warn_entries: 150
  hard_limit: 200
classification_defaults:
  shelf_life:
    tactical: 14
    observational: 30
dedup:
  threshold: 0.5
enforcement:
  stop_gate:
    min_files: 3
    min_lines: 40
"""


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return True


def run(argv: list[str]) -> int:
    parser = base_parser("init", "Create a .slate/ store in the repository root.")
    args = parser.parse_args(argv)

    root = git_root() or Path.cwd()
    store_root = root / ".slate"
    created_anything = not store_root.exists()

    (store_root / "expertise").mkdir(parents=True, exist_ok=True)
    (store_root / "cache").mkdir(parents=True, exist_ok=True)
    _write_if_missing(store_root / ".gitignore", "cache/\n")
    _write_if_missing(store_root / "slate.config.yaml", DEFAULT_CONFIG_YAML)

    gitattributes = root / ".gitattributes"
    if gitattributes.exists():
        existing = gitattributes.read_text(encoding="utf-8")
        if GITATTRIBUTES_LINE not in existing:
            suffix = "" if existing.endswith("\n") or not existing else "\n"
            with open(gitattributes, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(f"{suffix}{GITATTRIBUTES_LINE}\n")
    else:
        _write_if_missing(gitattributes, GITATTRIBUTES_LINE + "\n")

    text = (
        f"Initialized .slate/ in {root}"
        if created_anything
        else "Updated .slate/ — filled in any missing artifacts."
    )
    emit(
        {"created": created_anything, "path": to_posix(str(store_root))},
        json_mode=args.json,
        command="init",
        text=text,
    )
    return 0
