"""slate prune — archive stale records (mulch classification+age rules)."""

from __future__ import annotations

from slate import schema
from slate.commands._common import base_parser
from slate.output import emit
from slate.store import require_store


def run(argv: list[str]) -> int:
    parser = base_parser("prune", "Archive records past their shelf life.")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.add_argument("--hard", action="store_true", help="delete instead of archiving")
    args = parser.parse_args(argv)

    store = require_store()

    from slate import config as config_mod

    shelf_life = config_mod.load(store)["classification_defaults"]["shelf_life"]
    now_str = schema.now_iso()
    now = schema.parse_iso(now_str)

    results = []
    for domain in store.domains():
        records, warnings = store.read(domain)
        if warnings:
            # A whole-file rewrite would drop the unreadable lines — skip.
            results.append(
                {"domain": domain, "stale": 0, "kept": len(records), "action": "skipped",
                 "reason": f"{len(warnings)} unreadable line(s) — run slate doctor"}
            )
            continue
        stale = [r for r in records if schema.is_stale(r, now, shelf_life)]
        if not stale:
            continue
        keep = [r for r in records if r not in stale]
        counts = {"stale": len(stale), "kept": len(keep)}
        if not args.dry_run:

            def apply(current: list[dict]) -> list[dict] | None:
                # re-partition under the domain lock so concurrent appends survive
                live_stale = [r for r in current if schema.is_stale(r, now, shelf_life)]
                live_keep = [r for r in current if r not in live_stale]
                counts["stale"] = len(live_stale)
                counts["kept"] = len(live_keep)
                if not live_stale:
                    return None  # nothing to do — skip the rewrite
                if not args.hard:
                    for record in live_stale:
                        record["status"] = "archived"
                        record["archived_at"] = now_str
                        record["archive_reason"] = "stale"
                    # Archive-then-rewrite: a crash between the two duplicates
                    # a record (doctor flags it) rather than losing it.
                    # Skipping ids already archived keeps re-runs after such a
                    # crash from duplicating archive entries.
                    archived, _ = store.read_archive(domain)
                    archived_ids = {r.get("id") for r in archived} - {None}
                    to_archive = [r for r in live_stale if r.get("id") not in archived_ids]
                    if to_archive:
                        store.append_archive(domain, to_archive)
                return live_keep

            store.mutate(domain, apply)
        results.append(
            {
                "domain": domain,
                "stale": counts["stale"],
                "kept": counts["kept"],
                "action": "dry-run" if args.dry_run else ("deleted" if args.hard else "archived"),
            }
        )

    if args.json:
        emit({"results": results}, json_mode=True, command="prune")
        return 0
    if not results:
        print("nothing stale — no records pruned")
        return 0
    for row in results:
        if row["action"] == "skipped":
            print(f"{row['domain']}: skipped ({row['reason']})")
            continue
        verb = {
            "dry-run": "would delete" if args.hard else "would archive",
            "archived": "archived",
            "deleted": "deleted",
        }[row["action"]]
        print(f"{row['domain']}: {verb} {row['stale']} stale record(s), {row['kept']} kept")
    return 0
