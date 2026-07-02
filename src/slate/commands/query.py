"""slate query — list records, or fetch one full record by id (--id)."""

from __future__ import annotations

import json

from slate import priming
from slate.commands._common import base_parser
from slate.output import SlateError, emit
from slate.store import require_store, resolve_id


def run(argv: list[str]) -> int:
    parser = base_parser("query", "List records in a domain (or --all).")
    parser.add_argument("domain", nargs="?")
    parser.add_argument("--all", action="store_true", dest="all_domains")
    parser.add_argument("--type", dest="rtype")
    parser.add_argument("--classification")
    parser.add_argument("--file")
    parser.add_argument("--id", dest="record_id")
    parser.add_argument("--format", choices=("index", "full"), default="index")
    args = parser.parse_args(argv)

    store = require_store()

    if args.record_id:
        if not args.domain:
            raise SlateError("--id requires a domain", retry="slate query <domain> --id <id>")
        records, _ = store.read(args.domain)
        _, record = resolve_id(records, args.record_id, domain=args.domain)
        if args.json:
            emit({"domain": args.domain, "record": record}, json_mode=True, command="query")
        else:
            print(json.dumps(record, indent=2, ensure_ascii=False))
        return 0

    if not args.domain and not args.all_domains:
        raise SlateError(
            "provide a domain or --all",
            code="usage",
            retry="slate query <domain>",
            hint=f"available domains: {', '.join(store.domains()) or '(none)'}",
        )

    domains = store.domains() if args.all_domains else [args.domain]
    result: dict[str, list[dict]] = {}
    total = 0
    for domain in domains:
        records, _ = store.read(domain)
        if args.rtype:
            records = [r for r in records if r.get("type") == args.rtype]
        if args.classification:
            records = [r for r in records if r.get("classification") == args.classification]
        if args.file:
            needle = args.file.lower()
            records = [
                r
                for r in records
                if any(needle in f.lower() for f in r.get("files") or [])
            ]
        if records:
            result[domain] = records
            total += len(records)

    if args.json:
        emit({"domains": result, "total": total}, json_mode=True, command="query")
        return 0

    if not result:
        print("no records found")
        return 0
    lines: list[str] = []
    for domain in sorted(result):
        lines.append(f"## {domain} ({len(result[domain])} records)")
        if args.format == "full":
            for record in result[domain]:
                lines.extend(priming._full_lines(record))
        else:
            lines.extend(priming.index_line(r) for r in result[domain])
        lines.append("")
    print("\n".join(lines).strip())
    return 0
