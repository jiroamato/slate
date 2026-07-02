"""slate doctor — store health checks.

Exit 1 only on hard failures (unreadable lines, invalid records, duplicates,
hard-limit breaches); notices like unknown types or forced writes warn but
don't fail, since the tolerant reader treats them as first-class data.
"""

from __future__ import annotations

import json

from slate import schema
from slate.commands._common import base_parser
from slate.output import emit
from slate.store import require_store


def _check(name: str, level: str, message: str, details: list[str] | None = None) -> dict:
    return {"name": name, "level": level, "message": message, "details": details or []}


def run(argv: list[str]) -> int:
    parser = base_parser("doctor", "Run store health checks.")
    args = parser.parse_args(argv)

    store = require_store()
    checks: list[dict] = []

    # config parses
    try:
        from slate import config as config_mod

        cfg = config_mod.load(store)
        checks.append(_check("config", "ok", "config parses"))
    except Exception as err:  # noqa: BLE001 — doctor reports, never crashes
        cfg = None
        checks.append(_check("config", "fail", str(err)))

    all_records: dict[str, list[dict]] = {}
    integrity: list[str] = []
    for domain in store.domains():
        records, warnings = store.read(domain)
        all_records[domain] = records
        integrity.extend(warnings)
    if integrity:
        checks.append(
            _check("jsonl-integrity", "fail", f"{len(integrity)} unreadable line(s)", integrity)
        )
    else:
        checks.append(_check("jsonl-integrity", "ok", "all lines parse"))

    invalid: list[str] = []
    unknown_types: dict[str, int] = {}
    duplicates: list[str] = []
    for domain, records in all_records.items():
        seen_keys: dict[tuple[str, str], str] = {}
        for record in records:
            rtype = record.get("type", "?")
            type_def = schema.TYPES.get(rtype)
            if type_def is None:
                unknown_types[rtype] = unknown_types.get(rtype, 0) + 1
                continue
            for error in schema.validate_record(record):
                invalid.append(f"{domain}/{record.get('id', '?')}: {error}")
            key = (rtype, str(record.get(type_def.id_key, "")))
            if key in seen_keys:
                duplicates.append(
                    f"{domain}: {record.get('id', '?')} duplicates {seen_keys[key]} "
                    f"(same {type_def.id_key})"
                )
            else:
                seen_keys[key] = record.get("id", "?")

    checks.append(
        _check("schema-validation", "fail", f"{len(invalid)} invalid record(s)", invalid)
        if invalid
        else _check("schema-validation", "ok", "all builtin-type records valid")
    )
    if unknown_types:
        summary = ", ".join(f"{t} ×{n}" for t, n in sorted(unknown_types.items()))
        checks.append(
            _check(
                "unknown-types",
                "warn",
                f"unknown record type(s) preserved by the tolerant reader: {summary}",
            )
        )
    else:
        checks.append(_check("unknown-types", "ok", "no unknown types"))
    # a crash between prune's archive-append and live-rewrite leaves a record
    # in both files — flag it so the operator can delete the live copy
    for domain, records in all_records.items():
        archived, _ = store.read_archive(domain)
        archived_ids = {r.get("id") for r in archived} - {None}
        for record in records:
            if record.get("id") in archived_ids:
                duplicates.append(
                    f"{domain}: {record.get('id')} exists in both the live domain and its archive"
                )

    checks.append(
        _check("duplicates", "fail", f"{len(duplicates)} duplicate identity key(s)", duplicates)
        if duplicates
        else _check("duplicates", "ok", "no duplicate identity keys")
    )

    if cfg is not None:
        shelf_life = cfg["classification_defaults"]["shelf_life"]
        governance = cfg["governance"]
        now = schema.parse_iso(schema.now_iso())
        stale_total = sum(
            1
            for records in all_records.values()
            for r in records
            if schema.is_stale(r, now, shelf_life)
        )
        checks.append(
            _check("stale-records", "warn", f"{stale_total} stale record(s) — run slate prune")
            if stale_total
            else _check("stale-records", "ok", "no stale records")
        )
        over_hard = [
            f"{domain}: {len(records)} > hard limit {governance['hard_limit']}"
            for domain, records in all_records.items()
            if len(records) > governance["hard_limit"]
        ]
        over_soft = [
            domain
            for domain, records in all_records.items()
            if governance["max_entries"] < len(records) <= governance["hard_limit"]
        ]
        if over_hard:
            checks.append(_check("governance", "fail", "domain over hard limit", over_hard))
        elif over_soft:
            checks.append(
                _check("governance", "warn", f"domain(s) over soft limit: {', '.join(over_soft)}")
            )
        else:
            checks.append(_check("governance", "ok", "all domains within limits"))

    force_log = store.cache_dir / "force-log.jsonl"
    if force_log.exists():
        entries: list[dict] = []
        malformed = 0
        for line in force_log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                malformed += 1  # local telemetry corruption warns, never crashes
        if entries or malformed:
            message = f"{len(entries)} forced write(s) bypassed the dedup gate"
            if entries:
                message += f" (latest {entries[-1].get('ts')})"
            if malformed:
                message += f"; {malformed} malformed force-log line(s) ignored"
            checks.append(_check("dedup-gate", "warn", message))
    if not any(c["name"] == "dedup-gate" for c in checks):
        checks.append(_check("dedup-gate", "ok", "no forced writes logged"))

    failed = any(c["level"] == "fail" for c in checks)

    if args.json:
        emit({"healthy": not failed, "checks": checks}, json_mode=True, command="doctor")
    else:
        for check in checks:
            print(f"{check['level']}: {check['name']} — {check['message']}")
            for detail in check["details"][:10]:
                print(f"    {detail}")
    return 1 if failed else 0
