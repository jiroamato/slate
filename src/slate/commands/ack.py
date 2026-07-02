"""slate ack — escape valve for the stop gate."""

from __future__ import annotations

from slate import sessions
from slate.commands._common import base_parser
from slate.output import emit
from slate.store import require_store


def run(argv: list[str]) -> int:
    parser = base_parser("ack", "Acknowledge that this session has no lessons to record.")
    parser.add_argument(
        "--no-lessons",
        dest="reason",
        required=True,
        metavar="reason",
        help="why there is nothing worth recording",
    )
    args = parser.parse_args(argv)

    store = require_store()
    marker = sessions.write_ack(store.root, args.reason)
    emit(
        {"acknowledged": True, "reason": args.reason, "ts": marker["ts"]},
        json_mode=args.json,
        command="ack",
        text="Acknowledged — the stop gate will stay quiet for this session.",
    )
    return 0
