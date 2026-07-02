import json

import pytest

from slate.cli import main


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLATE_NOW", "2026-07-01T12:00:00.000Z")
    main(["init"])
    return tmp_path


def read_domain(repo, domain):
    path = repo / ".slate" / "expertise" / f"{domain}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_convention_happy_path(repo, capsys):
    code = main(
        ["record", "api", "--type", "convention", "--content", "use uv for dependency management",
         "--classification", "foundational", "--tags", "tooling,python"]
    )
    assert code == 0
    records = read_domain(repo, "api")
    assert len(records) == 1
    rec = records[0]
    assert rec["type"] == "convention"
    assert rec["content"] == "use uv for dependency management"
    assert rec["classification"] == "foundational"
    assert rec["recorded_at"] == "2026-07-01T12:00:00.000Z"
    assert rec["tags"] == ["tooling", "python"]
    assert rec["id"].startswith("mx-")
    assert "Recorded convention" in capsys.readouterr().out


def test_record_positional_content_for_convention(repo):
    assert main(["record", "api", "here is some content", "--type", "convention"]) == 0
    assert read_domain(repo, "api")[0]["content"] == "here is some content"


def test_missing_required_field_exit_2_names_flag(repo, capsys):
    code = main(["record", "api", "--type", "pattern", "--name", "atomic writes"])
    assert code == 2
    err = capsys.readouterr().err
    assert "--description" in err
    assert "retry:" in err


def test_invalid_domain_name_rejected(repo, capsys):
    assert main(["record", "bad domain!", "--type", "convention", "--content", "x"]) == 2


def test_dedup_gate_blocks_near_duplicate(repo, capsys):
    main(["record", "api", "--type", "convention", "--content",
          "always run the pytest suite before committing changes to the repository"])
    main(["record", "api", "--type", "convention", "--content",
          "database migrations live in the migrations folder and use sequential numbering"])
    capsys.readouterr()
    code = main(["record", "api", "--type", "convention", "--content",
                 "always run the pytest suite before you commit changes to the repository"])
    assert code == 3
    err = capsys.readouterr().err
    assert "near-duplicate" in err
    assert "mx-" in err
    assert "--force" in err
    assert "edit" in err
    assert len(read_domain(repo, "api")) == 2


def test_default_threshold_separates_near_dup_from_related(repo, capsys):
    main(["record", "api", "--type", "convention", "--content",
          "always run the pytest suite before committing changes to the repository"])
    capsys.readouterr()
    # related topic, same vocabulary sphere — must pass
    code = main(["record", "api", "--type", "convention", "--content",
                 "integration tests for the http layer live under tests/integration and are slow"])
    assert code == 0
    assert len(read_domain(repo, "api")) == 2


def test_force_bypasses_gate_and_logs(repo, capsys):
    main(["record", "api", "--type", "convention", "--content",
          "always run the pytest suite before committing changes to the repository"])
    capsys.readouterr()
    code = main(["record", "api", "--type", "convention", "--content",
                 "always run the pytest suite before you commit changes to the repository",
                 "--force"])
    assert code == 0
    assert len(read_domain(repo, "api")) == 2
    force_log = repo / ".slate" / "cache" / "force-log.jsonl"
    assert force_log.exists()
    entry = json.loads(force_log.read_text(encoding="utf-8").splitlines()[0])
    assert entry["domain"] == "api"
    assert entry["similar_id"].startswith("mx-")


def test_dedup_blocked_json_envelope(repo, capsys):
    main(["record", "api", "--type", "convention", "--content",
          "always run the pytest suite before committing changes to the repository"])
    capsys.readouterr()
    code = main(["record", "api", "--json", "--type", "convention", "--content",
                 "always run the pytest suite before committing changes to the repository"])
    assert code == 3
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"]["code"] == "dedup_blocked"
    assert "--force" in payload["error"]["retry"]


def test_dry_run_writes_nothing(repo, capsys):
    code = main(["record", "api", "--dry-run", "--type", "decision",
                 "--title", "pick argparse", "--rationale", "stdlib only"])
    assert code == 0
    assert read_domain(repo, "api") == []


def test_absolute_dir_anchor_rejected(repo):
    code = main(["record", "api", "--type", "convention", "--content", "x",
                 "--dir-anchor", "C:\\abs\\path"])
    assert code == 2


def test_evidence_flags_and_json_output(repo, capsys):
    code = main(["record", "api", "--json", "--type", "reference", "--name", "mulch upstream",
                 "--description", "the project slate forked from",
                 "--evidence-gh", "jayminwest/mulch", "--files", "docs/a.md,docs/b.md"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["record"]["evidence"]["gh"] == "jayminwest/mulch"
    assert payload["record"]["files"] == ["docs/a.md", "docs/b.md"]
