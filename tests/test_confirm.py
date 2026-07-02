import json

import pytest

from slate import priming
from slate.cli import main


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLATE_NOW", "2026-07-01T12:00:00.000Z")
    main(["init"])
    main(["record", "api", "--type", "pattern", "--name", "atomic writes",
          "--description", "temp file plus replace"])
    main(["record", "api", "--type", "convention", "--content", "keep deps minimal"])
    return tmp_path


def records(tmp_path, domain):
    path = tmp_path / ".slate" / "expertise" / f"{domain}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rid(tmp_path, domain, index=0):
    return records(tmp_path, domain)[index]["id"]


def test_confirm_appends_success_outcome_by_default(seeded, capsys):
    target = rid(seeded, "api", 0)
    assert main(["confirm", "api", target]) == 0
    rec = records(seeded, "api")[0]
    assert rec["outcomes"] == [{"status": "success"}]
    assert rec["id"] == target  # id is stable across confirmation
    assert priming.stars(rec) == 1


def test_confirm_boosts_ranking(seeded, capsys):
    # both records are tactical and tie on score, so record 0 ranks first;
    # confirming record 1 must lift it to the top
    target = rid(seeded, "api", 1)
    assert priming.rank(records(seeded, "api"))[0]["id"] == rid(seeded, "api", 0)
    assert main(["confirm", "api", target]) == 0
    assert priming.rank(records(seeded, "api"))[0]["id"] == target


def test_confirm_appends_to_existing_outcomes(seeded, capsys):
    main(["record", "api", "--type", "failure", "--description", "lock contention on CI",
          "--resolution", "retry with backoff", "--outcome-status", "success"])
    capsys.readouterr()
    target = rid(seeded, "api", 2)
    assert main(["confirm", "api", target, "--status", "failure"]) == 0
    rec = records(seeded, "api")[2]
    assert rec["outcomes"] == [{"status": "success"}, {"status": "failure"}]
    assert priming.stars(rec) == 1  # failures don't add stars


def test_confirm_records_optional_outcome_fields(seeded, capsys):
    target = rid(seeded, "api", 1)
    assert main(["confirm", "api", target, "--agent", "claude",
                 "--test-results", "12 passed", "--duration", "90"]) == 0
    rec = records(seeded, "api")[1]
    assert rec["outcomes"] == [
        {"status": "success", "duration": 90, "test_results": "12 passed", "agent": "claude"}
    ]


def test_confirm_drops_empty_optional_string_fields(seeded, capsys):
    # parity with `slate record --outcome-*`: an optional string outcome field
    # is either present with content or absent — never an empty string
    target = rid(seeded, "api", 0)
    assert main(["confirm", "api", target, "--test-results", "", "--agent", ""]) == 0
    assert records(seeded, "api")[0]["outcomes"] == [{"status": "success"}]


def test_record_and_confirm_build_identical_outcomes(seeded, capsys):
    main(["record", "api", "--type", "guide", "--name", "release steps",
          "--description", "tag then publish", "--outcome-status", "success",
          "--outcome-duration", "90", "--outcome-test-results", "12 passed",
          "--outcome-agent", "claude"])
    capsys.readouterr()
    target = rid(seeded, "api", 1)
    assert main(["confirm", "api", target, "--duration", "90",
                 "--test-results", "12 passed", "--agent", "claude"]) == 0
    recorded = records(seeded, "api")[2]["outcomes"][0]
    confirmed = records(seeded, "api")[1]["outcomes"][0]
    assert recorded == confirmed  # one outcome shape, one builder


def test_confirm_validates_status(seeded, capsys):
    target = rid(seeded, "api", 0)
    with pytest.raises(SystemExit) as exc:  # argparse rejects the bad choice
        main(["confirm", "api", target, "--status", "meh"])
    assert exc.value.code == 2
    assert "outcomes" not in records(seeded, "api")[0]


def test_confirm_unknown_id_exits_2_with_query_hint(seeded, capsys):
    assert main(["confirm", "api", "mx-ffffff", "--json"]) == 2
    err = json.loads(capsys.readouterr().err)
    assert err["ok"] is False
    assert err["error"]["code"] == "not_found"
    assert err["error"]["retry"] == "slate query api"


def test_confirm_unknown_domain_exits_2_with_hint(seeded, capsys):
    assert main(["confirm", "nonexistent", "mx-ffffff", "--json"]) == 2
    err = json.loads(capsys.readouterr().err)
    assert err["ok"] is False
    assert "nonexistent" in err["error"]["message"]
    assert "api" in err["error"]["hint"]  # names the domains that do exist
    # a failed confirm must not create the domain file
    assert not (seeded / ".slate" / "expertise" / "nonexistent.jsonl").exists()


def test_confirm_without_store_exits_5(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    assert main(["confirm", "api", "mx-ffffff"]) == 5


def test_confirm_json_envelope(seeded, capsys):
    target = rid(seeded, "api", 0)
    capsys.readouterr()
    assert main(["confirm", "api", target, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["command"] == "confirm"
    assert payload["domain"] == "api"
    assert payload["record"]["id"] == target
    assert payload["record"]["outcomes"] == [{"status": "success"}]
