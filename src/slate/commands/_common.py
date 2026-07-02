"""Shared helpers for command modules."""

from __future__ import annotations

import argparse
from pathlib import Path


def base_parser(prog: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"slate {prog}", description=description)
    parser.add_argument("--json", action="store_true", help="emit a JSON envelope")
    return parser


def git_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / ".git").exists():
            return directory
    return None


def csv_list(value: str | None) -> list[str] | None:
    if value is None:
        return None
    items = [item.strip() for item in value.split(",")]
    return [item for item in items if item]
