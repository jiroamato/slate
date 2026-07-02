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


def records(tmp_path, domain, kind="expertise"):
    path = tmp_path / ".slate" / kind / f"{domain}.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def seed_stale_and_fresh(monkeypatch, capsys):
    main(["record", "api", "--type", "convention", "--content",
          "an old observational note about the database layer",
          "--classification", "observational"])
    main(["record", "api", "--type", "convention", "--content",
          "a foundational rule that never goes stale",
          "--classification", "foundational"])
    monkeypatch.setenv("SLATE_NOW", "2026-09-01T12:00:00.000Z")  # 62 days later
    main(["record", "api", "--type", "convention", "--content",
          "a fresh tactical note recorded today"])
    capsys.readouterr()


def test_prune_archives_stale_records(repo, monkeypatch, capsys):
    seed_stale_and_fresh(monkeypatch, capsys)
    assert main(["prune"]) == 0
    live = records(repo, "api")
    assert len(live) == 2  # foundational + fresh tactical survive
    archived = records(repo, "api", kind="archive")
    assert len(archived) == 1
    assert archived[0]["status"] == "archived"
    assert archived[0]["archive_reason"] == "stale"
    assert archived[0]["archived_at"] == "2026-09-01T12:00:00.000Z"
    banner = (repo / ".slate" / "archive" / "api.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert banner.startswith("# ARCHIVED")


def test_prune_dry_run_touches_nothing(repo, monkeypatch, capsys):
    seed_stale_and_fresh(monkeypatch, capsys)
    assert main(["prune", "--dry-run"]) == 0
    assert len(records(repo, "api")) == 3
    assert not (repo / ".slate" / "archive").exists()


def test_prune_hard_deletes(repo, monkeypatch, capsys):
    seed_stale_and_fresh(monkeypatch, capsys)
    assert main(["prune", "--hard"]) == 0
    assert len(records(repo, "api")) == 2
    assert not (repo / ".slate" / "archive").exists()


def test_doctor_healthy_store_passes(repo, capsys):
    main(["record", "api", "--type", "convention", "--content", "use uv"])
    capsys.readouterr()
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "ok:" in out
    assert "fail:" not in out


def test_doctor_reports_malformed_lines_and_fails(repo, capsys):
    path = repo / ".slate" / "expertise" / "api.jsonl"
    path.write_text('{"type":"convention","content":"ok","classification":"tactical","recorded_at":"t"}\n{broken\n', encoding="utf-8")
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "api.jsonl:2" in out
    assert "fail:" in out


def test_doctor_notices_unknown_types_without_failing(repo, capsys):
    path = repo / ".slate" / "expertise" / "api.jsonl"
    path.write_text('{"type":"ritual","incantation":"x","id":"mx-ab12cd"}\n', encoding="utf-8")
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "unknown" in out
    assert "ritual" in out


def test_doctor_detects_duplicate_identity_keys(repo, capsys):
    line = '{"type":"convention","content":"same words","classification":"tactical","recorded_at":"t","id":"mx-%s"}\n'
    path = repo / ".slate" / "expertise" / "api.jsonl"
    path.write_text(line % "aaaaaa" + line % "bbbbbb", encoding="utf-8")
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "duplicate" in out


def test_doctor_reports_force_log(repo, capsys):
    main(["record", "api", "--type", "convention", "--content",
          "always run the pytest suite before committing changes"])
    main(["record", "api", "--type", "convention", "--content",
          "always run the pytest suite before you commit changes", "--force"])
    capsys.readouterr()
    main(["doctor"])
    out = capsys.readouterr().out
    assert "force" in out.lower()


def test_doctor_json(repo, capsys):
    main(["record", "api", "--type", "convention", "--content", "x"])
    capsys.readouterr()
    assert main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert any(c["name"] == "jsonl-integrity" for c in payload["checks"])
