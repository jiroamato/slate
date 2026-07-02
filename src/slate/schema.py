"""Record types and validation (hand-rolled — no jsonschema dependency).

The six builtin types and every constant here are mulch 0.10.7 parity:
id = "mx-" + sha256("<type>:<idKey value>")[:6], per-type required fields,
sentence-aware truncation for summaries.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

CLASSIFICATIONS = ("foundational", "tactical", "observational")
LIVE_STATUSES = ("draft", "active", "deprecated")
OUTCOME_STATUSES = ("success", "failure", "partial")
EVIDENCE_KEYS = ("commit", "date", "issue", "file", "bead", "seeds", "gh", "linear")
LINK_RE = re.compile(r"^([a-z0-9-]+:)?mx-[0-9a-f]{4,8}$")
DOMAIN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

# Fields every builtin record may carry, on top of its type-specific fields.
BASE_FIELDS = frozenset(
    {
        "id",
        "type",
        "classification",
        "recorded_at",
        "evidence",
        "tags",
        "relates_to",
        "supersedes",
        "outcomes",
        "dir_anchors",
        "supersession_demoted_at",
        "anchor_decay_demoted_at",
        "owner",
        "status",
    }
)


@dataclass(frozen=True)
class TypeDef:
    name: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    id_key: str = ""  # also the dedup key for all six builtins
    summary_truncate: int | None = None  # None = verbatim id_key value
    section_title: str = ""
    extracts_files: bool = False
    flags: dict[str, str] = field(default_factory=dict)  # field -> CLI flag


TYPES: dict[str, TypeDef] = {
    t.name: t
    for t in (
        TypeDef(
            "convention",
            required=("content",),
            id_key="content",
            summary_truncate=60,
            section_title="Conventions",
            flags={"content": "--content"},
        ),
        TypeDef(
            "pattern",
            required=("name", "description"),
            optional=("files",),
            id_key="name",
            section_title="Patterns",
            extracts_files=True,
            flags={"name": "--name", "description": "--description"},
        ),
        TypeDef(
            "failure",
            required=("description", "resolution"),
            id_key="description",
            summary_truncate=60,
            section_title="Known Failures",
            flags={"description": "--description", "resolution": "--resolution"},
        ),
        TypeDef(
            "decision",
            required=("title", "rationale"),
            optional=("date",),
            id_key="title",
            section_title="Decisions",
            flags={"title": "--title", "rationale": "--rationale"},
        ),
        TypeDef(
            "reference",
            required=("name", "description"),
            optional=("files",),
            id_key="name",
            section_title="References",
            extracts_files=True,
            flags={"name": "--name", "description": "--description"},
        ),
        TypeDef(
            "guide",
            required=("name", "description"),
            id_key="name",
            section_title="Guides",
            flags={"name": "--name", "description": "--description"},
        ),
    )
}


def now_iso() -> str:
    """UTC ISO-8601 with milliseconds and Z suffix. SLATE_NOW overrides (tests/CI)."""
    fixed = os.environ.get("SLATE_NOW")
    if fixed:
        return fixed
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def generate_id(record: dict) -> str:
    type_def = TYPES.get(record.get("type", ""))
    id_value = record.get(type_def.id_key, "") if type_def else ""
    key = f"{record.get('type', '')}:{id_value}"
    return "mx-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:6]


def truncate(text: str, max_len: int = 100) -> str:
    """Sentence-aware truncation (mulch parity): cut at the first sentence end
    if one occurs before max_len, else hard-cut with an ellipsis."""
    if len(text) <= max_len:
        return text
    match = re.search(r"[.!?]\s", text)
    if match and 0 < match.start() < max_len:
        return text[: match.start() + 1]
    return text[:max_len] + "..."


def summary(record: dict) -> str:
    type_def = TYPES.get(record.get("type", ""))
    if type_def is None:
        # Unknown type: best effort from common identity-ish fields.
        for key in ("name", "title", "description", "content"):
            if isinstance(record.get(key), str):
                return truncate(record[key], 60)
        return f"({record.get('type', 'unknown')} record)"
    value = record.get(type_def.id_key, "")
    if not isinstance(value, str):
        value = str(value)
    if type_def.summary_truncate is not None:
        return truncate(value, type_def.summary_truncate)
    return value


def _check_str(record: dict, key: str, errors: list[str], rtype: str) -> None:
    if key in record and not isinstance(record[key], str):
        errors.append(f"{rtype} field '{key}' must be a string")


def _check_str_list(record: dict, key: str, errors: list[str], rtype: str) -> None:
    value = record.get(key)
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        errors.append(f"{rtype} field '{key}' must be a list of strings")


def validate_record(record: dict, *, strict_unknown: bool = False) -> list[str]:
    """Return a list of human-readable validation errors (empty = valid).

    Records of unknown type are tolerated by default (preserved, primed,
    searched — never dropped); pass strict_unknown=True to flag them.
    """
    errors: list[str] = []
    rtype = record.get("type")
    if not isinstance(rtype, str) or not rtype:
        return ["record is missing a 'type' field"]

    type_def = TYPES.get(rtype)
    if type_def is None:
        if strict_unknown:
            valid = ", ".join(sorted(TYPES))
            errors.append(f"unknown record type '{rtype}' (builtin types: {valid})")
        return errors

    missing = [f for f in type_def.required if not record.get(f)]
    if missing:
        errors.append(f"{rtype} records are missing required field(s): {', '.join(missing)}")

    classification = record.get("classification")
    if classification not in CLASSIFICATIONS:
        errors.append(
            "classification must be one of: "
            f"{', '.join(CLASSIFICATIONS)} (got {classification!r})"
        )

    if not isinstance(record.get("recorded_at"), str) or not record.get("recorded_at"):
        errors.append(f"{rtype} records require a 'recorded_at' timestamp")

    allowed = BASE_FIELDS | set(type_def.required) | set(type_def.optional)
    unknown = sorted(set(record) - allowed)
    if unknown:
        errors.append(f"unknown field(s) on {rtype} record: {', '.join(unknown)}")

    for key in type_def.required:
        _check_str(record, key, errors, rtype)
    _check_str(record, "date", errors, rtype)
    _check_str(record, "owner", errors, rtype)
    for key in ("tags", "files", "dir_anchors"):
        _check_str_list(record, key, errors, rtype)

    for key in ("relates_to", "supersedes"):
        links = record.get(key)
        if links is None:
            continue
        if not isinstance(links, list) or not all(isinstance(v, str) for v in links):
            errors.append(f"{rtype} field '{key}' must be a list of record ids")
            continue
        bad = [v for v in links if not LINK_RE.match(v)]
        if bad:
            errors.append(
                f"{key} contains invalid record id(s): {', '.join(bad)} "
                "(expected mx-<hex> or <domain>:mx-<hex>)"
            )

    evidence = record.get("evidence")
    if evidence is not None:
        if not isinstance(evidence, dict):
            errors.append("evidence must be an object")
        else:
            bad_keys = sorted(set(evidence) - set(EVIDENCE_KEYS))
            if bad_keys:
                errors.append(
                    f"evidence contains unknown key(s): {', '.join(bad_keys)} "
                    f"(valid keys: {', '.join(EVIDENCE_KEYS)})"
                )

    outcomes = record.get("outcomes")
    if outcomes is not None:
        if not isinstance(outcomes, list):
            errors.append("outcomes must be a list")
        else:
            for outcome in outcomes:
                if not isinstance(outcome, dict) or outcome.get("status") not in OUTCOME_STATUSES:
                    errors.append(
                        "each outcome requires a status of: " + ", ".join(OUTCOME_STATUSES)
                    )
                    break

    status = record.get("status")
    if status is not None and status not in LIVE_STATUSES:
        errors.append(
            f"status must be one of: {', '.join(LIVE_STATUSES)} (got {status!r}); "
            "'archived' is reserved for archive files"
        )

    return errors
