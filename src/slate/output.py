"""Agent-legible output contract: stable exit codes, error/success envelopes.

Every error names the problem, the valid options, and the exact retry
command — in text and in the --json envelope.
"""

from __future__ import annotations

import json
import sys

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_DEDUP = 3
EXIT_LOCK = 4
EXIT_NO_STORE = 5


class SlateError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "validation",
        exit_code: int = EXIT_USAGE,
        hint: str | None = None,
        retry: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.exit_code = exit_code
        self.hint = hint
        self.retry = retry


def _dump(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def emit(data: dict, *, json_mode: bool, command: str, text: str | None = None) -> None:
    """Print a success payload: JSON envelope in --json mode, plain text otherwise."""
    if json_mode:
        print(_dump({"ok": True, "command": command, **data}))
    elif text is not None:
        print(text)


def fail(err: SlateError, *, json_mode: bool) -> int:
    """Print an error envelope to stderr and return the exit code to use."""
    if json_mode:
        payload = {
            "ok": False,
            "error": {
                "code": err.code,
                "message": err.message,
                "hint": err.hint,
                "retry": err.retry,
            },
        }
        print(_dump(payload), file=sys.stderr)
    else:
        lines = [f"error: {err.message}"]
        if err.hint:
            lines.append(f"hint: {err.hint}")
        if err.retry:
            lines.append(f"retry: {err.retry}")
        print("\n".join(lines), file=sys.stderr)
    return err.exit_code
