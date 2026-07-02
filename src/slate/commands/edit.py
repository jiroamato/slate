"""slate edit — merge field updates into a record (locked whole-file rewrite)."""

from __future__ import annotations

from slate import schema
from slate.anchors import assert_writable_dir_anchor, normalize_dir_anchor
from slate.commands._common import base_parser, csv_list
from slate.commands.record import EVIDENCE_FLAGS
from slate.output import SlateError, emit
from slate.store import require_store, resolve_id

_FIELD_FLAGS = ("content", "name", "description", "resolution", "title", "rationale", "date")


def run(argv: list[str]) -> int:
    parser = base_parser("edit", "Update fields on an existing record.")
    parser.add_argument("domain")
    parser.add_argument("record_id", metavar="id")
    parser.add_argument("--classification", choices=schema.CLASSIFICATIONS)
    for flag in _FIELD_FLAGS:
        parser.add_argument(f"--{flag}")
    parser.add_argument("--files")
    parser.add_argument("--tags")
    parser.add_argument("--relates-to", dest="relates_to")
    parser.add_argument("--supersedes")
    parser.add_argument("--dir-anchor", dest="dir_anchors", action="append", default=None)
    for key in EVIDENCE_FLAGS:
        parser.add_argument(f"--evidence-{key}", dest=f"evidence_{key}")
    args = parser.parse_args(argv)

    store = require_store()
    records = store.read_for_rewrite(args.domain)
    index, record = resolve_id(records, args.record_id, domain=args.domain)
    updated = dict(record)

    for flag in _FIELD_FLAGS:
        value = getattr(args, flag)
        if value is not None:
            updated[flag] = value
    if args.classification:
        updated["classification"] = args.classification
    for key, raw in (("files", args.files), ("tags", args.tags),
                     ("relates_to", args.relates_to), ("supersedes", args.supersedes)):
        if raw is not None:
            updated[key] = csv_list(raw) or []
            if not updated[key]:
                updated.pop(key)
    if args.dir_anchors is not None:
        anchors = []
        for raw in args.dir_anchors:
            assert_writable_dir_anchor(raw)
            normalized = normalize_dir_anchor(raw)
            if normalized:
                anchors.append(normalized)
        updated["dir_anchors"] = anchors
    evidence_updates = {
        key: getattr(args, f"evidence_{key}")
        for key in EVIDENCE_FLAGS
        if getattr(args, f"evidence_{key}") is not None
    }
    if evidence_updates:
        updated["evidence"] = {**(record.get("evidence") or {}), **evidence_updates}

    errors = schema.validate_record(updated)
    if errors:
        raise SlateError(
            "; ".join(errors),
            hint="the edit would make the record invalid; nothing was written",
        )

    records[index] = updated
    store.rewrite(args.domain, records)
    emit(
        {"domain": args.domain, "record": updated},
        json_mode=args.json,
        command="edit",
        text=f"Updated {updated.get('id')} in {args.domain}",
    )
    return 0
