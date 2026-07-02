import json
import subprocess

import pytest

from slate.cli import main


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLATE_NOW", "2026-07-01T12:00:00.000Z")
    main(["init"])
    (tmp_path / "unrelated.txt").write_text("user work in progress", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def test_sync_commits_store_paths_only(repo, capsys):
    main(["record", "api", "--type", "convention", "--content", "use uv"])
    (repo / "unrelated.txt").write_text("dirty user edit — must not be committed", encoding="utf-8")
    capsys.readouterr()
    assert main(["sync"]) == 0
    # store change committed…
    log = git(repo, "log", "-1", "--name-only", "--format=%s").stdout
    assert "slate: update expertise" in log
    assert ".slate/expertise/api.jsonl" in log
    assert "unrelated.txt" not in log
    # …and the user's dirty file is still uncommitted
    status = git(repo, "status", "--porcelain").stdout
    assert "unrelated.txt" in status


def test_sync_no_changes_is_noop(repo, capsys):
    assert main(["sync"]) == 0
    assert "No changes" in capsys.readouterr().out


def test_sync_custom_message(repo, capsys):
    main(["record", "api", "--type", "convention", "--content", "x"])
    capsys.readouterr()
    assert main(["sync", "--message", "chore: record api lesson"]) == 0
    assert git(repo, "log", "-1", "--format=%s").stdout.strip() == "chore: record api lesson"


def test_sync_validation_blocks_bad_store(repo, capsys):
    bad = repo / ".slate" / "expertise" / "api.jsonl"
    bad.write_text(
        '{"type":"pattern","name":"broken","classification":"tactical","recorded_at":"t"}\n',
        encoding="utf-8",
    )
    assert main(["sync"]) == 2
    err = capsys.readouterr().err
    assert "description" in err
    assert main(["sync", "--no-validate"]) == 0


def test_status_reports_domains(repo, capsys):
    main(["record", "api", "--type", "convention", "--content", "use uv"])
    main(["record", "api", "--type", "convention", "--content",
          "database naming follows snake case",
          "--classification", "observational"])
    capsys.readouterr()
    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    api = next(d for d in payload["domains"] if d["domain"] == "api")
    assert api["count"] == 2
    assert api["utilization"] == 2  # percent of max_entries=100
    assert payload["governance"]["max_entries"] == 100


def test_status_counts_stale_records(repo, capsys, monkeypatch):
    main(["record", "api", "--type", "convention", "--content", "old observational note",
          "--classification", "observational"])
    capsys.readouterr()
    monkeypatch.setenv("SLATE_NOW", "2026-09-01T12:00:00.000Z")  # 62 days later
    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    api = next(d for d in payload["domains"] if d["domain"] == "api")
    assert api["stale"] == 1
