"""slate move — relocate a record across domains, preserving its id."""

from __future__ import annotations

from slate.commands._common import base_parser
from slate.output import emit
from slate.store import require_store, resolve_id


def run(argv: list[str]) -> int:
    parser = base_parser("move", "Move a record from one domain to another.")
    parser.add_argument("source")
    parser.add_argument("record_id", metavar="id")
    parser.add_argument("target")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    args = parser.parse_args(argv)

    store = require_store()
    records = store.read_for_rewrite(args.source)
    index, record = resolve_id(records, args.record_id, domain=args.source)

    # Incoming references from any domain (relates_to/supersedes) keep pointing
    # at the old domain-qualified id — surface them so the operator can fix up.
    rid = record.get("id", "")
    incoming: list[dict] = []
    for domain in store.domains():
        others, _ = store.read(domain)
        for other in others:
            if other is record or other.get("id") == rid:
                continue
            for field in ("relates_to", "supersedes"):
                links = other.get(field) or []
                if any(link == rid or link.endswith(f":{rid}") for link in links):
                    incoming.append({"domain": domain, "id": other.get("id"), "field": field})

    if args.dry_run:
        emit(
            {"action": "dry-run", "source": args.source, "target": args.target,
             "record": record, "incoming_references": incoming},
            json_mode=args.json,
            command="move",
            text=f"dry-run: would move {rid} from {args.source} to {args.target}",
        )
        return 0

    # Append to the target before rewriting the source: a crash in between
    # duplicates the record across domains (visible, recoverable) instead of
    # deleting it — same never-lose ordering as prune's archive-then-rewrite.
    store.append(args.target, record)
    del records[index]
    store.rewrite(args.source, records)

    lines = [f"Moved {rid} from {args.source} to {args.target}"]
    for ref in incoming:
        lines.append(
            f"warning: incoming reference from {ref['domain']}/{ref['id']} ({ref['field']})"
        )
    emit(
        {"source": args.source, "target": args.target, "record": record,
         "incoming_references": incoming},
        json_mode=args.json,
        command="move",
        text="\n".join(lines),
    )
    return 0
