"""slate CLI entry point.

Command modules are imported lazily so the hook hot path (`slate hook *`)
never pays for argparse subcommand setup it doesn't use.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if "--version" in args:
        from slate import __version__

        print(f"slate {__version__}")
        return 0
    print("usage: slate <command> [options]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
