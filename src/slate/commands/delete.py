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
    records = store.read_for_rewrite(args.domain)
    index, record = resolve_id(records, args.record_id, domain=args.domain)

    if args.dry_run:
        emit(
            {"action": "dry-run", "domain": args.domain, "record": record},
            json_mode=args.json,
            command="delete",
            text=f"dry-run: would delete {record.get('id')} from {args.domain}",
        )
        return 0

    del records[index]
    store.rewrite(args.domain, records)
    emit(
        {"deleted": record, "kept": len(records), "domain": args.domain},
        json_mode=args.json,
        command="delete",
        text=f"Deleted {record.get('id')} from {args.domain} ({len(records)} kept)",
    )
    return 0
