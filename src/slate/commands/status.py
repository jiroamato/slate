"""slate status — per-domain store summary."""

from __future__ import annotations

from slate import schema
from slate.commands._common import base_parser
from slate.output import emit
from slate.store import require_store


def run(argv: list[str]) -> int:
    parser = base_parser("status", "Summarize the store's domains and health.")
    args = parser.parse_args(argv)

    store = require_store()

    from slate import config as config_mod

    cfg = config_mod.load(store)
    shelf_life = cfg["classification_defaults"]["shelf_life"]
    governance = cfg["governance"]
    now = schema.parse_iso(schema.now_iso())

    domains = []
    for domain in store.domains():
        records, warnings = store.read(domain)
        stale = sum(1 for r in records if schema.is_stale(r, now, shelf_life))
        newest = max((r.get("recorded_at", "") for r in records), default="")
        types: dict[str, int] = {}
        for record in records:
            types[record.get("type", "?")] = types.get(record.get("type", "?"), 0) + 1
        domains.append(
            {
                "domain": domain,
                "count": len(records),
                "stale": stale,
                "newest": newest or None,
                "types": types,
                "utilization": round(len(records) / governance["max_entries"] * 100)
                if governance["max_entries"]
                else 0,
                "warnings": len(warnings),
            }
        )

    if args.json:
        emit(
            {"domains": domains, "governance": governance, "shelf_life": shelf_life},
            json_mode=True,
            command="status",
        )
        return 0

    if not domains:
        print("empty store — record a lesson with: slate record <domain> --type <type> ...")
        return 0
    for entry in domains:
        parts = [f"{entry['domain']}: {entry['count']} records"]
        parts.append(f"{entry['utilization']}% of budget")
        if entry["stale"]:
            parts.append(f"{entry['stale']} stale")
        if entry["warnings"]:
            parts.append(f"{entry['warnings']} unreadable lines")
        print(" — ".join(parts))
    return 0
