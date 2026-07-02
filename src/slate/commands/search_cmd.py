"""slate search — BM25 across domains with confirmation boost."""

from __future__ import annotations

from slate import priming
from slate.commands._common import base_parser
from slate.output import emit
from slate.search import search_records
from slate.store import require_store


def run(argv: list[str]) -> int:
    parser = base_parser("search", "Search records across domains (BM25).")
    parser.add_argument("query")
    parser.add_argument("--domain")
    parser.add_argument("--type", dest="rtype")
    parser.add_argument("--tag")
    parser.add_argument("--classification")
    parser.add_argument("--no-boost", action="store_true", dest="no_boost")
    parser.add_argument("--archived", action="store_true")
    args = parser.parse_args(argv)

    store = require_store()

    from slate import config as config_mod

    boost = 0.0 if args.no_boost else float(config_mod.load(store)["search"]["boost_factor"])

    domains = [args.domain] if args.domain else store.domains()
    pool: list[dict] = []
    origin: dict[int, str] = {}
    for domain in domains:
        records, _ = store.read(domain)
        if args.archived:
            archived, _ = store.read_archive(domain)
            records = [*records, *archived]
        for record in records:
            if args.rtype and record.get("type") != args.rtype:
                continue
            if args.classification and record.get("classification") != args.classification:
                continue
            if args.tag and args.tag.lower() not in [t.lower() for t in record.get("tags") or []]:
                continue
            origin[id(record)] = domain
            pool.append(record)

    ranked = search_records(pool, args.query, boost_factor=boost)

    if args.json:
        emit(
            {
                "query": args.query,
                "results": [
                    {"domain": origin[id(r)], "score": round(s, 4), "record": r}
                    for r, s in ranked
                ],
            },
            json_mode=True,
            command="search",
        )
        return 0

    if not ranked:
        print("no matches")
        return 0
    for record, score in ranked:
        print(f"{priming.index_line(record)}  ({origin[id(record)]}, score {score:.2f})")
    return 0
