"""slate delete — remove a record (locked whole-file rewrite)."""

from __future__ import annotations

from slate.commands._common import base_parser
from slate.output import emit
from slate.store import require_store, resolve_id


def run(argv: list[str]) -> int:
    parser = base_parser("delete", "Delete a record from a domain.")
    parser.add_argument("domain")
    parser.add_argument("record_id", metavar="id")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    args = parser.parse_args(argv)

    store = require_store()

    if args.dry_run:
        records = store.read_for_rewrite(args.domain)
        _, record = resolve_id(records, args.record_id, domain=args.domain)
        emit(
            {"action": "dry-run", "domain": args.domain, "record": record},
            json_mode=args.json,
            command="delete",
            text=f"dry-run: would delete {record.get('id')} from {args.domain}",
        )
        return 0

    result: dict = {}

    def apply(records: list[dict]) -> list[dict]:
        # under the domain lock — a concurrent append can't be dropped
        index, record = resolve_id(records, args.record_id, domain=args.domain)
        del records[index]
        result["record"] = record
        result["kept"] = len(records)
        return records

    store.mutate(args.domain, apply)
    emit(
        {"deleted": result["record"], "kept": result["kept"], "domain": args.domain},
        json_mode=args.json,
        command="delete",
        text=f"Deleted {result['record'].get('id')} from {args.domain} ({result['kept']} kept)",
    )
    return 0
