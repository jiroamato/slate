"""slate confirm — append an outcome to an existing record (locked rewrite).

The post-hoc write path for the confirmation signal: `priming.rank()` /
`priming.stars()` and the search boost all score records by their `outcomes`
list, and until this command the only way to earn one was at record-creation
time.
"""

from __future__ import annotations

from slate import schema
from slate.commands._common import base_parser
from slate.output import SlateError, emit
from slate.store import require_store, resolve_id


def run(argv: list[str]) -> int:
    parser = base_parser("confirm", "Append an outcome confirmation to a record.")
    parser.add_argument("domain")
    parser.add_argument("record_id", metavar="id")
    parser.add_argument("--status", default="success", choices=schema.OUTCOME_STATUSES)
    parser.add_argument("--duration", type=int)
    parser.add_argument("--test-results", dest="test_results")
    parser.add_argument("--agent")
    args = parser.parse_args(argv)

    store = require_store()

    available = store.domains()
    if args.domain not in available:
        raise SlateError(
            f"unknown domain '{args.domain}'",
            hint=f"available domains: {', '.join(available) or '(none)'}",
            retry="slate query --all",
        )

    # same outcome shape as `slate record --outcome-*` — no extra fields
    outcome: dict = {"status": args.status}
    if args.duration is not None:
        outcome["duration"] = args.duration
    if args.test_results:
        outcome["test_results"] = args.test_results
    if args.agent:
        outcome["agent"] = args.agent

    result: dict = {}

    def apply(records: list[dict]) -> list[dict]:
        # runs under the domain lock (store.mutate) — resolve against the
        # current on-disk state so concurrent appends can't be dropped
        index, record = resolve_id(records, args.record_id, domain=args.domain)
        updated = dict(record)
        updated["outcomes"] = [*(record.get("outcomes") or []), outcome]

        errors = schema.validate_record(updated)
        if errors:
            raise SlateError(
                "; ".join(errors),
                hint="the confirm would make the record invalid; nothing was written",
            )

        records[index] = updated
        result["record"] = updated
        return records

    store.mutate(args.domain, apply)
    updated = result["record"]
    emit(
        {"domain": args.domain, "record": updated},
        json_mode=args.json,
        command="confirm",
        text=(
            f"Confirmed {updated.get('id')} in {args.domain} "
            f"({args.status}; {len(updated['outcomes'])} outcome(s))"
        ),
    )
    return 0
