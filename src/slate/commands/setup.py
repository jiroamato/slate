"""slate setup claude — install (or remove) enforcement hooks and permission
rules in .claude/settings.json. Idempotent; --remove deletes only slate's
entries. Hook commands are single plain argv invocations — no pipes, no &&,
no $() — so the identical text works on cmd, PowerShell and bash.
"""

from __future__ import annotations

import json
from pathlib import Path

from slate.commands._common import base_parser, git_root
from slate.output import SlateError, emit
from slate.store import atomic_write, require_store

_HOOK_PREFIX = "slate hook"

# (event, matcher, command)
_HOOKS = (
    ("SessionStart", None, "slate hook session-start"),
    ("PreToolUse", "Edit|Write", "slate hook pre-tool"),
    ("Stop", None, "slate hook stop"),
)

CLAUDE_MD_SNIPPET = """\
## Slate memory

This repo uses slate (git-native agent memory). An index of recorded lessons
is injected at session start; file-scoped lessons appear when you first touch
an anchored file.

- Fetch a full record: `slate query <domain> --id <id>`
- Search lessons: `slate search "<query>"`
- Record as you learn: `slate record <domain> --type <convention|pattern|failure|decision|reference|guide> ...`
- If a session ends with significant changes and nothing recorded, the stop
  gate asks once. Either record a lesson or run:
  `slate ack --no-lessons "<why there was nothing to record>"`
"""


def _slate_entry(matcher: str | None, command: str) -> dict:
    entry: dict = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        entry["matcher"] = matcher
    return entry


def _has_slate_hook(entries: list[dict]) -> bool:
    return any(
        hook.get("command", "").startswith(_HOOK_PREFIX)
        for entry in entries
        for hook in entry.get("hooks", [])
    )


def _deny_rules(store_dir_name: str) -> list[str]:
    return [
        f"Edit({store_dir_name}/expertise/**)",
        f"Write({store_dir_name}/expertise/**)",
    ]


def _install(settings: dict, store_dir_name: str) -> dict:
    hooks = settings.setdefault("hooks", {})
    for event, matcher, command in _HOOKS:
        entries = hooks.setdefault(event, [])
        if not _has_slate_hook(entries):
            entries.append(_slate_entry(matcher, command))
    permissions = settings.setdefault("permissions", {})
    deny = permissions.setdefault("deny", [])
    for rule in _deny_rules(store_dir_name):
        if rule not in deny:
            deny.append(rule)
    return settings


def _remove(settings: dict) -> dict:
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        pruned_entries = []
        for entry in hooks[event]:
            kept = [
                h for h in entry.get("hooks", []) if not h.get("command", "").startswith(_HOOK_PREFIX)
            ]
            if kept:
                pruned_entries.append({**entry, "hooks": kept})
        if pruned_entries:
            hooks[event] = pruned_entries
        else:
            del hooks[event]
    if not hooks and "hooks" in settings:
        del settings["hooks"]

    deny = settings.get("permissions", {}).get("deny")
    if deny is not None:
        slate_rules = {rule for name in (".slate", ".mulch") for rule in _deny_rules(name)}
        settings["permissions"]["deny"] = [r for r in deny if r not in slate_rules]
    return settings


def run(argv: list[str]) -> int:
    parser = base_parser("setup", "Install enforcement hooks for a harness.")
    parser.add_argument("target", choices=("claude",))
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--settings", default=None, help="path to settings.json (default: <repo>/.claude/settings.json)")
    args = parser.parse_args(argv)

    store = require_store()
    if args.settings:
        settings_path = Path(args.settings)
    else:
        root = git_root() or Path.cwd()
        settings_path = root / ".claude" / "settings.json"

    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            raise SlateError(
                f"{settings_path} is not valid JSON: {err}",
                hint="fix the file manually; slate will not overwrite it",
            ) from err

    settings = _remove(settings) if args.remove else _install(settings, store.root.name)

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    # atomic: an interrupted plain write would corrupt settings.json and
    # silently disable every hook in it (slate's and the user's alike)
    atomic_write(settings_path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")

    if args.remove:
        emit(
            {"removed": True, "settings": str(settings_path)},
            json_mode=args.json,
            command="setup",
            text=f"Removed slate hooks and permissions from {settings_path}",
        )
        return 0

    emit(
        {"installed": True, "settings": str(settings_path), "claude_md_snippet": CLAUDE_MD_SNIPPET},
        json_mode=args.json,
        command="setup",
        text=(
            f"Installed slate hooks and permissions into {settings_path}\n\n"
            "Add this to your CLAUDE.md so agents know the workflow:\n\n"
            + CLAUDE_MD_SNIPPET
        ),
    )
    return 0
