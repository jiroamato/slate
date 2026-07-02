"""slate record — append a typed record, guarded by the BM25 dedup gate."""

from __future__ import annotations

import json
import shlex

from slate import gitctx, schema
from slate.anchors import assert_writable_dir_anchor, infer_dir_anchors, normalize_dir_anchor
from slate.commands._common import base_parser, csv_list
from slate.output import EXIT_DEDUP, SlateError, emit
from slate.search import extract_text, search_records
from slate.store import Store, dumps_record, require_store

EVIDENCE_FLAGS = ("commit", "date", "issue", "file", "bead", "seeds", "gh", "linear")


def _parser():
    parser = base_parser("record", "Append a typed expertise record to a domain.")
    parser.add_argument("domain")
    parser.add_argument("positional_content", nargs="?", default=None, metavar="content")
    parser.add_argument("--type", required=True, choices=sorted(schema.TYPES), dest="rtype")
    parser.add_argument("--classification", default="tactical", choices=schema.CLASSIFICATIONS)
    parser.add_argument("--content")
    parser.add_argument("--name")
    parser.add_argument("--description")
    parser.add_argument("--resolution")
    parser.add_argument("--title")
    parser.add_argument("--rationale")
    parser.add_argument("--date")
    parser.add_argument("--files")
    parser.add_argument("--tags")
    parser.add_argument("--relates-to", dest="relates_to")
    parser.add_argument("--supersedes")
    parser.add_argument("--dir-anchor", dest="dir_anchors", action="append", default=[])
    for key in EVIDENCE_FLAGS:
        parser.add_argument(f"--evidence-{key}", dest=f"evidence_{key}")
    parser.add_argument("--outcome-status", choices=schema.OUTCOME_STATUSES)
    parser.add_argument("--outcome-duration", type=int)
    parser.add_argument("--outcome-test-results", dest="outcome_test_results")
    parser.add_argument("--outcome-agent", dest="outcome_agent")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    return parser


def build_record(args) -> dict:
    type_def = schema.TYPES[args.rtype]
    record: dict = {"type": args.rtype}

    field_values = {
        "content": args.content if args.content is not None else args.positional_content,
        "name": args.name,
        "description": args.description,
        "resolution": args.resolution,
        "title": args.title,
        "rationale": args.rationale,
        "date": args.date,
    }
    for key in (*type_def.required, *type_def.optional):
        if key == "files":
            continue
        if field_values.get(key) is not None:
            record[key] = field_values[key]

    files = csv_list(args.files)
    if type_def.extracts_files:
        if files is None:
            files = gitctx.changed_files() or None
        if files:
            record["files"] = files

    record["classification"] = args.classification
    record["recorded_at"] = schema.now_iso()

    evidence = {
        key: getattr(args, f"evidence_{key}")
        for key in EVIDENCE_FLAGS
        if getattr(args, f"evidence_{key}") is not None
    }
    if "commit" not in evidence:
        head = gitctx.head_commit()
        if head:
            evidence["commit"] = head
    if evidence:
        record["evidence"] = evidence

    if csv_list(args.tags):
        record["tags"] = csv_list(args.tags)
    if csv_list(args.relates_to):
        record["relates_to"] = csv_list(args.relates_to)
    if csv_list(args.supersedes):
        record["supersedes"] = csv_list(args.supersedes)

    if args.outcome_status:
        outcome = {"status": args.outcome_status}
        if args.outcome_duration is not None:
            outcome["duration"] = args.outcome_duration
        if args.outcome_test_results:
            outcome["test_results"] = args.outcome_test_results
        if args.outcome_agent:
            outcome["agent"] = args.outcome_agent
        record["outcomes"] = [outcome]

    anchors = []
    for raw in args.dir_anchors:
        assert_writable_dir_anchor(raw)
        normalized = normalize_dir_anchor(raw)
        if normalized:
            anchors.append(normalized)
    if not anchors and record.get("files"):
        anchors = infer_dir_anchors(record["files"])
    if anchors:
        record["dir_anchors"] = anchors

    return record


def _validate(record: dict, args, argv: list[str]) -> None:
    if not schema.DOMAIN_RE.match(args.domain):
        raise SlateError(
            f"invalid domain name '{args.domain}'",
            hint="domain names are alphanumeric plus '-' and '_', starting alphanumeric",
        )
    errors = schema.validate_record(record)
    if errors:
        type_def = schema.TYPES[args.rtype]
        missing = [f for f in type_def.required if not record.get(f)]
        flags = " ".join(f'{type_def.flags[f]} "<{f}>"' for f in missing if f in type_def.flags)
        raise SlateError(
            "; ".join(errors),
            hint=f"{args.rtype} records require: {', '.join(type_def.required)}",
            retry=f"slate record {args.domain} --type {args.rtype} {flags}".strip(),
        )


def similarity(existing: list[dict], candidate: dict) -> tuple[dict | None, float]:
    """Top normalized similarity of candidate vs existing records.

    Scores a corpus of existing + candidate against the candidate's own text
    and divides the best existing score by the candidate's self-score, so the
    threshold holds regardless of corpus size.
    """
    if not existing:
        return None, 0.0
    type_def = schema.TYPES.get(candidate.get("type", ""))
    if type_def:  # exact identity-key collision is always a duplicate
        key_value = candidate.get(type_def.id_key)
        for record in existing:
            if record.get("type") == candidate.get("type") and record.get(type_def.id_key) == key_value:
                return record, 1.0
    corpus = [*existing, candidate]
    results = search_records(corpus, extract_text(candidate))
    self_score = next((s for r, s in results if r is candidate), 0.0)
    if self_score <= 0:
        return None, 0.0
    top = next(((r, s) for r, s in results if r is not candidate), None)
    if top is None:
        return None, 0.0
    return top[0], top[1] / self_score


def _log_force(store: Store, domain: str, record: dict, similar: dict | None, score: float) -> None:
    store.cache_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": schema.now_iso(),
        "domain": domain,
        "id": record.get("id"),
        "similar_id": (similar or {}).get("id"),
        "score": round(score, 4),
    }
    with open(store.cache_dir / "force-log.jsonl", "a", encoding="utf-8", newline="\n") as fh:
        fh.write(dumps_record(entry) + "\n")


def run(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    store = require_store()
    record = build_record(args)
    _validate(record, args, argv)
    record["id"] = schema.generate_id(record)

    from slate import config as config_mod

    threshold = float(config_mod.load(store)["dedup"]["threshold"])
    existing, _ = store.read(args.domain)
    similar, score = similarity(existing, record)

    if similar is not None and score >= threshold and not args.force:
        quoted = " ".join(shlex.quote(a) for a in argv)
        retry = f"slate record {quoted} --force --supersedes {similar.get('id')}"
        message = (
            f"near-duplicate of {similar.get('id')} (similarity {score:.2f}, "
            f"threshold {threshold}) in domain '{args.domain}':\n"
            + json.dumps(similar, indent=2, ensure_ascii=False)
            + "\nthree ways forward:\n"
            f"  1. update the existing record: slate edit {args.domain} {similar.get('id')} ...\n"
            f"  2. supersede it: re-run with --force --supersedes {similar.get('id')}\n"
            "  3. rephrase with genuinely new content and re-run"
        )
        raise SlateError(
            message,
            code="dedup_blocked",
            exit_code=EXIT_DEDUP,
            hint="the dedup gate blocks writes too similar to an existing record",
            retry=retry,
        )

    if args.dry_run:
        emit(
            {"action": "dry-run", "domain": args.domain, "record": record},
            json_mode=args.json,
            command="record",
            text=f"dry-run: would record {args.rtype} {record['id']} in {args.domain}",
        )
        return 0

    if args.force:
        _log_force(store, args.domain, record, similar, score)
    store.append(args.domain, record)
    emit(
        {"action": "created", "domain": args.domain, "record": record},
        json_mode=args.json,
        command="record",
        text=f"Recorded {args.rtype} {record['id']} in {args.domain}",
    )
    return 0
