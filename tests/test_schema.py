import hashlib
import re

import pytest

from slate import schema


def _rec(**kw):
    base = {"classification": "tactical", "recorded_at": "2026-07-01T00:00:00.000Z"}
    base.update(kw)
    return base


# --- id generation ---


def test_generate_id_is_sha256_of_type_and_idkey():
    rec = _rec(type="convention", content="Use uv for everything")
    digest = hashlib.sha256(b"convention:Use uv for everything").hexdigest()[:6]
    assert schema.generate_id(rec) == f"mx-{digest}"


def test_generate_id_uses_per_type_id_key():
    pattern = _rec(type="pattern", name="repo layout", description="d")
    decision = _rec(type="decision", title="repo layout", rationale="r")
    assert schema.generate_id(pattern) == "mx-" + hashlib.sha256(b"pattern:repo layout").hexdigest()[:6]
    assert schema.generate_id(decision) != schema.generate_id(pattern)
    assert re.fullmatch(r"mx-[0-9a-f]{6}", schema.generate_id(pattern))


# --- validation: required fields per type ---


@pytest.mark.parametrize(
    ("rtype", "fields", "missing"),
    [
        ("convention", {}, "content"),
        ("pattern", {"name": "n"}, "description"),
        ("failure", {"description": "d"}, "resolution"),
        ("decision", {"rationale": "r"}, "title"),
        ("reference", {"description": "d"}, "name"),
        ("guide", {"name": "n"}, "description"),
    ],
)
def test_missing_required_fields_named_in_error(rtype, fields, missing):
    errors = schema.validate_record(_rec(type=rtype, **fields))
    assert any(missing in e and rtype in e for e in errors)


def test_valid_records_of_all_six_types_pass():
    valid = [
        _rec(type="convention", content="c"),
        _rec(type="pattern", name="n", description="d", files=["src/a.py"]),
        _rec(type="failure", description="d", resolution="r"),
        _rec(type="decision", title="t", rationale="r", date="2026-07-01"),
        _rec(type="reference", name="n", description="d"),
        _rec(type="guide", name="n", description="d"),
    ]
    for rec in valid:
        assert schema.validate_record(rec) == [], rec["type"]


def test_classification_enum_enforced():
    errors = schema.validate_record({"type": "convention", "content": "c", "classification": "wrong", "recorded_at": "x"})
    assert any("classification" in e and "foundational" in e for e in errors)


def test_recorded_at_required():
    errors = schema.validate_record({"type": "convention", "content": "c", "classification": "tactical"})
    assert any("recorded_at" in e for e in errors)


def test_unknown_fields_rejected_on_builtin_types():
    errors = schema.validate_record(_rec(type="convention", content="c", bogus=1))
    assert any("bogus" in e for e in errors)


def test_link_pattern_enforced():
    bad = schema.validate_record(_rec(type="convention", content="c", relates_to=["nope"]))
    good = schema.validate_record(_rec(type="convention", content="c", relates_to=["mx-ab12cd", "other-domain:mx-ab12"]))
    assert any("relates_to" in e for e in bad)
    assert good == []


def test_evidence_keys_restricted():
    bad = schema.validate_record(_rec(type="convention", content="c", evidence={"url": "x"}))
    good = schema.validate_record(_rec(type="convention", content="c", evidence={"commit": "abc", "gh": "#1"}))
    assert any("evidence" in e for e in bad)
    assert good == []


def test_outcome_requires_valid_status():
    bad = schema.validate_record(_rec(type="convention", content="c", outcomes=[{"duration": 5}]))
    good = schema.validate_record(_rec(type="convention", content="c", outcomes=[{"status": "success", "duration": 5}]))
    assert any("status" in e for e in bad)
    assert good == []


# --- tolerant unknown types ---


def test_unknown_type_tolerated_by_default():
    assert schema.validate_record(_rec(type="ritual", incantation="x")) == []


def test_unknown_type_flagged_when_strict():
    errors = schema.validate_record(_rec(type="ritual"), strict_unknown=True)
    assert any("ritual" in e for e in errors)


# --- now_iso ---


def test_now_iso_is_utc_millis_z(monkeypatch):
    monkeypatch.delenv("SLATE_NOW", raising=False)
    value = schema.now_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value)


def test_now_iso_honors_slate_now_env(monkeypatch):
    monkeypatch.setenv("SLATE_NOW", "2026-07-01T12:00:00.000Z")
    assert schema.now_iso() == "2026-07-01T12:00:00.000Z"


# --- summaries ---


def test_summary_per_type():
    assert schema.summary(_rec(type="pattern", name="repo layout", description="long " * 50)) == "repo layout"
    assert schema.summary(_rec(type="decision", title="pick uv", rationale="r")) == "pick uv"
    long_content = "word " * 30
    assert schema.summary(_rec(type="convention", content=long_content)).endswith("...")


def test_truncate_prefers_sentence_boundary():
    text = "Short first sentence. Then a much longer trailing explanation that runs on and on and on."
    assert schema.truncate(text, 60) == "Short first sentence."
    assert schema.truncate("no boundary " * 20, 30) == ("no boundary " * 20)[:30] + "..."
    assert schema.truncate("tiny", 60) == "tiny"
