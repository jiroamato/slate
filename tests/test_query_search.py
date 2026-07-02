import json

import pytest

from slate.cli import main


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLATE_NOW", "2026-07-01T12:00:00.000Z")
    main(["init"])
    main(["record", "api", "--type", "convention", "--content", "use uv for python dependency management", "--tags", "tooling"])
    main(["record", "api", "--type", "pattern", "--name", "atomic writes", "--description",
          "write to a temp file then os.replace", "--files", "src/store.py"])
    main(["record", "cli", "--type", "decision", "--title", "argparse over click",
          "--rationale", "keep runtime deps to pyyaml only", "--classification", "foundational"])
    return tmp_path


def get_id(tmp_path, domain, index=0):
    path = tmp_path / ".slate" / "expertise" / f"{domain}.jsonl"
    return json.loads(path.read_text(encoding="utf-8").splitlines()[index])["id"]


# --- query ---


def test_query_domain_lists_records(seeded, capsys):
    assert main(["query", "api"]) == 0
    out = capsys.readouterr().out
    assert "atomic writes" in out
    assert "use uv" in out
    assert "argparse" not in out


def test_query_all_spans_domains(seeded, capsys):
    assert main(["query", "--all"]) == 0
    out = capsys.readouterr().out
    assert "argparse over click" in out
    assert "atomic writes" in out


def test_query_type_filter(seeded, capsys):
    assert main(["query", "api", "--type", "pattern"]) == 0
    out = capsys.readouterr().out
    assert "atomic writes" in out
    assert "use uv" not in out


def test_query_by_id_returns_full_record(seeded, capsys):
    rid = get_id(seeded, "api", 1)
    assert main(["query", "api", "--id", rid]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "atomic writes"
    assert payload["description"] == "write to a temp file then os.replace"


def test_query_by_id_prefix(seeded, capsys):
    rid = get_id(seeded, "api", 0)
    assert main(["query", "api", "--id", rid[3:6]]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == rid


def test_query_unknown_id_not_found(seeded, capsys):
    assert main(["query", "api", "--id", "mx-ffffff"]) == 2
    err = capsys.readouterr().err
    assert "not found" in err
    assert "slate query api" in err


def test_query_json_envelope(seeded, capsys):
    assert main(["query", "api", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["total"] == 2


def test_query_without_domain_or_all_is_usage_error(seeded, capsys):
    assert main(["query"]) == 2


def test_query_missing_store_exit_5(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    assert main(["query", "api"]) == 5


# --- search ---


def test_search_ranks_and_prints_matches(seeded, capsys):
    assert main(["search", "atomic temp file"]) == 0
    out = capsys.readouterr().out
    assert "atomic writes" in out
    assert "argparse" not in out


def test_search_domain_filter(seeded, capsys):
    assert main(["search", "uv dependency", "--domain", "cli"]) == 0
    out = capsys.readouterr().out
    assert "use uv" not in out


def test_search_tag_filter(seeded, capsys):
    assert main(["search", "uv python", "--tag", "tooling"]) == 0
    assert "use uv" in capsys.readouterr().out


def test_search_json_returns_scores(seeded, capsys):
    assert main(["search", "atomic writes temp", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["results"][0]["record"]["name"] == "atomic writes"
    assert payload["results"][0]["score"] > 0
    assert payload["results"][0]["domain"] == "api"
