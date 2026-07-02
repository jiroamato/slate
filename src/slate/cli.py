"""slate CLI entry point.

Dispatch imports exactly one command module per invocation, so the hook hot
path (`slate hook *`) never pays for parsers or dependencies it doesn't use.
"""

from __future__ import annotations

import importlib
import sys

from slate.output import EXIT_LOCK, EXIT_UNEXPECTED, EXIT_USAGE, SlateError, fail

COMMANDS: dict[str, str] = {
    "init": "slate.commands.init",
    "record": "slate.commands.record",
    "query": "slate.commands.query",
    "prime": "slate.commands.prime",
    "search": "slate.commands.search_cmd",
    "edit": "slate.commands.edit",
    "delete": "slate.commands.delete",
    "move": "slate.commands.move",
    "sync": "slate.commands.sync",
    "prune": "slate.commands.prune",
    "doctor": "slate.commands.doctor",
    "status": "slate.commands.status",
    "setup": "slate.commands.setup",
    "hook": "slate.commands.hook",
    "ack": "slate.commands.ack",
}

USAGE = "usage: slate <command> [options]\ncommands: " + ", ".join(COMMANDS)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in args

    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    if args[0] == "--version":
        from slate import __version__

        print(f"slate {__version__}")
        return 0

    command = args[0]
    module_path = COMMANDS.get(command)
    if module_path is None:
        err = SlateError(
            f"unknown command '{command}'",
            code="usage",
            exit_code=EXIT_USAGE,
            hint=f"valid commands: {', '.join(COMMANDS)}",
            retry="slate --help",
        )
        return fail(err, json_mode=json_mode)

    try:
        module = importlib.import_module(module_path)
        return module.run(args[1:])
    except SlateError as err:
        return fail(err, json_mode=json_mode)
    except Exception as err:  # noqa: BLE001 — CLI boundary
        from slate.locks import LockTimeout

        if isinstance(err, LockTimeout):
            wrapped = SlateError(
                str(err),
                code="lock_timeout",
                exit_code=EXIT_LOCK,
                hint="another slate process holds the lock; retry in a few seconds",
            )
        else:
            wrapped = SlateError(
                f"unexpected error: {err}", code="unexpected", exit_code=EXIT_UNEXPECTED
            )
        return fail(wrapped, json_mode=json_mode)


if __name__ == "__main__":
    sys.exit(main())
