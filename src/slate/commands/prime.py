"""slate prime — emit AI context: compact index by default, --full for
mulch-style markdown. Output is delimiter-wrapped (except --format plain)."""

from __future__ import annotations

from slate import priming
from slate.anchors import file_lives_under_dir
from slate.commands._common import base_parser
from slate.output import SlateError, emit
from slate.store import require_store, to_posix


def _matches_files(record: dict, files: list[str]) -> bool:
    record_files = [to_posix(f) for f in record.get("files") or []]
    anchors = record.get("dir_anchors") or []
    for wanted in files:
        w = to_posix(wanted).lower()
        if any(w in f.lower() or f.lower() in w for f in record_files):
            return True
        if any(file_lives_under_dir(to_posix(wanted), a) for a in anchors):
            return True
    return False


def run(argv: list[str]) -> int:
    parser = base_parser("prime", "Emit expertise context for an agent session.")
    parser.add_argument("domains", nargs="*")
    parser.add_argument("--files", nargs="+", default=None)
    parser.add_argument("--budget", type=int, default=None)
    parser.add_argument(
        "--format", choices=("index", "markdown", "compact", "plain"), default="index"
    )
    parser.add_argument("--full", action="store_true", help="alias for --format markdown")
    args = parser.parse_args(argv)

    store = require_store()

    from slate import config as config_mod

    cfg = config_mod.load(store)
    budget = args.budget if args.budget is not None else int(cfg["prime"]["budget"])
    tier_weights = cfg["prime"]["tier_weights"]
    fmt = "markdown" if args.full else args.format

    available = store.domains()
    unknown = [d for d in args.domains if d not in available]
    if unknown:
        raise SlateError(
            f"unknown domain(s): {', '.join(unknown)}",
            hint=f"available domains: {', '.join(available) or '(none)'}",
            retry="slate prime",
        )
    domains = args.domains or available

    domain_records: dict[str, list[dict]] = {}
    for domain in domains:
        records, _ = store.read(domain)
        if args.files:
            records = [r for r in records if _matches_files(r, args.files)]
        if records:
            domain_records[domain] = records

    all_records = [r for records in domain_records.values() for r in records]

    if fmt == "markdown":
        body = priming.render_full(domain_records)
    elif fmt == "compact":
        lines: list[str] = []
        for domain in sorted(domain_records):
            lines.append(f"## {domain}")
            lines.extend(
                f"- [{r.get('type', '?')}] {priming.index_line(r)}"
                for r in priming.rank(domain_records[domain], tier_weights)
            )
            lines.append("")
        body = "\n".join(lines).strip() + "\n"
    else:  # index | plain
        body = priming.render_index(domain_records, budget=budget, tier_weights=tier_weights)

    text = body if fmt == "plain" else priming.wrap_delimited(body)

    if args.json:
        emit(
            {
                "format": fmt,
                "budget": budget,
                "tokens": priming.estimate_tokens(body),
                "ids": [r.get("id") for r in all_records],
                "body": text,
            },
            json_mode=True,
            command="prime",
        )
        return 0

    print(text, end="")
    return 0
