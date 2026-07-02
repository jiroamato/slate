"""Regression tests for greptile review findings on PR #1."""

import json

import pytest

from slate.cli import main
from slate.search import search_records


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLATE_NOW", "2026-07-01T12:00:00.000Z")
    main(["init"])
    return tmp_path


# 1. BM25 must not divide by zero when no record yields tokens


def test_search_all_empty_corpus_returns_no_matches():
    records = [
        {"type": "mystery", "payload": 42},          # unknown type, no string fields
        {"type": "mystery", "flag": True},
    ]
    assert search_records(records, "anything") == []


def test_search_cli_survives_tokenless_records(repo, capsys):
    path = repo / ".slate" / "expertise" / "odd.jsonl"
    path.write_text('{"type":"mystery","payload":42,"id":"mx-aaaaaa"}\n', encoding="utf-8")
    assert main(["search", "anything"]) == 0
    assert "no matches" in capsys.readouterr().out


# 2. doctor reports (not crashes on) a malformed force-log line


def test_doctor_reports_malformed_force_log(repo, capsys):
    cache = repo / ".slate" / "cache"
    cache.mkdir(exist_ok=True)
    (cache / "force-log.jsonl").write_text(
        '{"ts":"2026-07-01T00:00:00.000Z","domain":"api","id":"mx-aaaaaa","similar_id":"mx-bbbbbb","score":0.9}\n'
        '{"ts":"2026-07-01T00:00:01.000Z","domain":"api","truncated-mid-wri\n',
        encoding="utf-8",
    )
    code = main(["doctor"])
    out = capsys.readouterr().out
    assert code == 0  # corruption in local telemetry warns, never crashes doctor
    assert "force-log" in out
    assert "malformed" in out


# 3. dedup retry command must not use POSIX-only quoting


def test_dedup_retry_command_is_windows_safe(repo, capsys):
    main(["record", "api", "--type", "convention", "--content",
          "always run the pytest suite before committing changes to the repository"])
    capsys.readouterr()
    code = main(["record", "api", "--json", "--type", "convention", "--content",
                 "always run the pytest suite before committing changes to the repository"])
    assert code == 3
    retry = json.loads(capsys.readouterr().err)["error"]["retry"]
    assert "'" not in retry  # single quotes break cmd.exe and PowerShell
    assert '--content "always run' in retry
    assert retry.startswith("slate record api")


# 4. prune re-runs must not duplicate records into the archive


def test_prune_rerun_does_not_duplicate_archived_records(repo, monkeypatch, capsys):
    main(["record", "api", "--type", "convention", "--content", "an old note",
          "--classification", "observational"])
    monkeypatch.setenv("SLATE_NOW", "2026-09-01T12:00:00.000Z")
    main(["prune"])
    # simulate the crash window: the archived record is still in the live file too
    archived_line = (repo / ".slate" / "archive" / "api.jsonl").read_text(encoding="utf-8").splitlines()[1]
    live = repo / ".slate" / "expertise" / "api.jsonl"
    stale_again = json.loads(archived_line)
    for key in ("status", "archived_at", "archive_reason"):
        stale_again.pop(key, None)
    live.write_text(json.dumps(stale_again, separators=(",", ":")) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["prune"]) == 0
    archive_lines = [
        line
        for line in (repo / ".slate" / "archive" / "api.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert len(archive_lines) == 1  # re-pruning the same record must not duplicate it
    assert live.read_text(encoding="utf-8") == ""


def test_doctor_flags_record_in_both_live_and_archive(repo, capsys):
    line = '{"type":"convention","content":"dup","classification":"observational","recorded_at":"2026-01-01T00:00:00.000Z","id":"mx-dupdup"}\n'
    (repo / ".slate" / "expertise" / "api.jsonl").write_text(line, encoding="utf-8")
    (repo / ".slate" / "archive").mkdir(exist_ok=True)
    (repo / ".slate" / "archive" / "api.jsonl").write_text("# ARCHIVED\n" + line, encoding="utf-8")
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "mx-dupdup" in out
    assert "archive" in out
