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


def test_dedup_gate_blocks_realistic_paraphrase(repo, capsys):
    # measured at similarity ~0.54 — the shipped 0.5 threshold must catch it
    main(["record", "storage", "--type", "pattern", "--name", "atomic writes",
          "--description", "same-directory temp file then os.replace"])
    main(["record", "storage", "--type", "failure",
          "--description", "windows os.replace hit PermissionError under antivirus scans",
          "--resolution", "bounded retry with backoff around os.replace"])
    capsys.readouterr()
    code = main(["record", "storage", "--type", "failure",
                 "--description", "windows os.replace hits PermissionError when antivirus scans the file",
                 "--resolution", "retry os.replace with backoff"])
    assert code == 3


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


def test_prune_archives_stale_idless_record_even_when_archive_has_idless_entry(repo, capsys):
    # neither record carries an id: the archived_ids skip-set must not treat
    # None == None as "already archived" and silently drop the live record
    (repo / ".slate" / "archive").mkdir(exist_ok=True)
    (repo / ".slate" / "archive" / "api.jsonl").write_text(
        "# ARCHIVED\n"
        '{"type":"convention","content":"previously archived","classification":"observational",'
        '"recorded_at":"2025-01-01T00:00:00.000Z","status":"archived"}\n',
        encoding="utf-8",
    )
    (repo / ".slate" / "expertise" / "api.jsonl").write_text(
        '{"type":"convention","content":"stale and id-less","classification":"observational",'
        '"recorded_at":"2026-01-01T00:00:00.000Z"}\n',
        encoding="utf-8",
    )
    assert main(["prune"]) == 0
    archive_text = (repo / ".slate" / "archive" / "api.jsonl").read_text(encoding="utf-8")
    assert "stale and id-less" in archive_text  # archived, not silently dropped
    assert (repo / ".slate" / "expertise" / "api.jsonl").read_text(encoding="utf-8") == ""


def test_pre_tool_injects_multiple_idless_records(repo, monkeypatch, capsys):
    # two id-less records anchored to different files: injecting the first must
    # not poison injected_ids with None and suppress the second
    import io
    import sys as _sys

    monkeypatch.setattr("tempfile.gettempdir", lambda: str(repo / "tmp"))
    (repo / ".slate" / "expertise" / "api.jsonl").write_text(
        '{"type":"convention","content":"first anchored lesson","classification":"tactical",'
        '"recorded_at":"2026-06-01T00:00:00.000Z","dir_anchors":["src/a"]}\n'
        '{"type":"convention","content":"second anchored lesson","classification":"tactical",'
        '"recorded_at":"2026-06-01T00:00:00.000Z","dir_anchors":["src/b"]}\n',
        encoding="utf-8",
    )
    session = "idless-session"
    for anchor, expected in (("src/a/x.py", "first anchored lesson"), ("src/b/y.py", "second anchored lesson")):
        payload = {"session_id": session, "tool_input": {"file_path": str(repo / anchor)}}
        monkeypatch.setattr(_sys, "stdin", io.StringIO(json.dumps(payload)))
        assert main(["hook", "pre-tool"]) == 0
        out = capsys.readouterr().out
        assert expected in out, f"record anchored at {anchor} was not injected"


def test_rewrite_assigns_distinct_ids_to_idless_unknown_records(tmp_path):
    from slate.store import Store

    root = tmp_path / ".slate"
    (root / "expertise").mkdir(parents=True)
    store = Store(root, "slate")
    records = [
        {"type": "benchmark", "metric": "reads", "value": 100},
        {"type": "benchmark", "metric": "writes", "value": 7},
    ]
    store.mutate("perf", lambda _: records)
    ids = [r["id"] for r in records]
    assert len(set(ids)) == 2, f"distinct unknown-type records collided on id: {ids}"
    assert all(i.startswith("mx-") for i in ids)


def test_unknown_type_id_generation_is_deterministic():
    from slate import schema

    record = {"type": "benchmark", "metric": "reads", "value": 100}
    same = {"value": 100, "metric": "reads", "type": "benchmark"}  # key order differs
    assert schema.generate_id(record) == schema.generate_id(same)


def test_prune_dry_run_hard_says_delete(repo, monkeypatch, capsys):
    main(["record", "api", "--type", "convention", "--content", "old note",
          "--classification", "observational"])
    monkeypatch.setenv("SLATE_NOW", "2026-09-01T12:00:00.000Z")
    capsys.readouterr()
    assert main(["prune", "--dry-run", "--hard"]) == 0
    assert "would delete" in capsys.readouterr().out


def test_move_crash_between_operations_never_loses_the_record(repo, monkeypatch, capsys):
    # move = target append + source rewrite; if the source rewrite dies after
    # the append, the record must exist *somewhere* (duplicated, never deleted)
    from slate import store as store_mod

    main(["record", "api", "--type", "convention", "--content", "precious lesson"])
    capsys.readouterr()

    def exploding_atomic_write(path, content):
        raise RuntimeError("simulated crash mid-move")

    monkeypatch.setattr(store_mod, "atomic_write", exploding_atomic_write)
    assert main(["move", "api", "mx-", "archive-domain"]) == 1  # unexpected error
    source = (repo / ".slate" / "expertise" / "api.jsonl").read_text(encoding="utf-8")
    target = (repo / ".slate" / "expertise" / "archive-domain.jsonl").read_text(encoding="utf-8")
    assert "precious lesson" in source or "precious lesson" in target
    assert "precious lesson" in target  # append-to-target must happen first


def test_setup_writes_settings_atomically(repo, monkeypatch):
    # a crashing write must leave the previous settings.json intact
    from slate import store as store_mod

    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    original = '{"model": "opus"}'
    (claude_dir / "settings.json").write_text(original, encoding="utf-8")

    real_replace = store_mod.os.replace

    def exploding_replace(src, dst):
        raise KeyboardInterrupt("simulated interrupt mid-write")

    monkeypatch.setattr(store_mod.os, "replace", exploding_replace)
    with pytest.raises(KeyboardInterrupt):
        main(["setup", "claude"])
    monkeypatch.setattr(store_mod.os, "replace", real_replace)
    assert (claude_dir / "settings.json").read_text(encoding="utf-8") == original


def test_doctor_governance_uses_warn_entries_band(repo, capsys):
    (repo / ".slate" / "slate.config.yaml").write_text(
        "governance:\n  max_entries: 2\n  warn_entries: 4\n  hard_limit: 6\n",
        encoding="utf-8",
    )
    line = (
        '{"type":"convention","content":"note %d","classification":"foundational",'
        '"recorded_at":"2026-06-01T00:00:00.000Z","id":"mx-%06d"}\n'
    )
    path = repo / ".slate" / "expertise" / "api.jsonl"

    path.write_text("".join(line % (i, i) for i in range(3)), encoding="utf-8")  # > soft (2)
    assert main(["doctor"]) == 0
    assert "soft limit" in capsys.readouterr().out

    path.write_text("".join(line % (i, i) for i in range(5)), encoding="utf-8")  # > warn (4)
    assert main(["doctor"]) == 0
    assert "approaching the hard limit" in capsys.readouterr().out

    path.write_text("".join(line % (i, i) for i in range(7)), encoding="utf-8")  # > hard (6)
    assert main(["doctor"]) == 1
    assert "hard limit" in capsys.readouterr().out


def test_edit_does_not_drop_concurrently_appended_records(repo, monkeypatch, capsys):
    # simulate another process appending between edit's read and its lock:
    # the sneaky lock wrapper appends a record the moment the lock is taken,
    # i.e. the last instant a competing writer could have won the race
    import contextlib

    from slate import store as store_mod

    main(["record", "api", "--type", "convention", "--content", "record to edit"])
    capsys.readouterr()
    target_id = json.loads(
        (repo / ".slate" / "expertise" / "api.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )["id"]
    real_lock = store_mod.file_lock
    concurrent = (
        '{"type":"convention","content":"appended by a parallel subagent",'
        '"classification":"tactical","recorded_at":"2026-07-01T12:30:00.000Z","id":"mx-race00"}\n'
    )
    state = {"injected": False}

    @contextlib.contextmanager
    def sneaky_lock(target):
        if not state["injected"] and target.name == "api.jsonl":
            state["injected"] = True
            with open(target, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(concurrent)
        with real_lock(target):
            yield

    monkeypatch.setattr(store_mod, "file_lock", sneaky_lock)
    assert main(["edit", "api", target_id, "--content", "edited content"]) == 0
    text = (repo / ".slate" / "expertise" / "api.jsonl").read_text(encoding="utf-8")
    assert "appended by a parallel subagent" in text  # concurrent write survived
    assert "edited content" in text


def test_save_state_is_atomic(tmp_path, monkeypatch):
    from slate import sessions
    from slate import store as store_mod

    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    original = sessions.new_state("atomic-session")
    sessions.save_state(original)
    before = sessions.state_path("atomic-session").read_text(encoding="utf-8")

    def exploding_replace(src, dst):
        raise KeyboardInterrupt("simulated interrupt mid-write")

    monkeypatch.setattr(store_mod.os, "replace", exploding_replace)
    with pytest.raises(KeyboardInterrupt):
        sessions.save_state({**original, "seen_files": ["x.py"]})
    assert sessions.state_path("atomic-session").read_text(encoding="utf-8") == before


def test_force_write_succeeds_even_if_force_log_fails(repo, monkeypatch, capsys):
    from slate.commands import record as record_cmd

    main(["record", "api", "--type", "convention", "--content",
          "always run the pytest suite before committing changes"])
    capsys.readouterr()

    def exploding_log(*a, **kw):
        raise OSError("cache dir unwritable")

    monkeypatch.setattr(record_cmd, "_log_force", exploding_log)
    code = main(["record", "api", "--type", "convention", "--content",
                 "always run the pytest suite before you commit changes", "--force"])
    assert code == 0  # telemetry failure must not block the write
    text = (repo / ".slate" / "expertise" / "api.jsonl").read_text(encoding="utf-8")
    assert "before you commit changes" in text


def test_pre_tool_dir_anchor_matching_is_case_insensitive(repo, monkeypatch, capsys):
    # files matching lowercases both sides; anchors must too, or a mixed-case
    # anchor never fires on the case-insensitive filesystems CI targets
    import io
    import sys as _sys

    monkeypatch.setattr("tempfile.gettempdir", lambda: str(repo / "tmp"))
    (repo / ".slate" / "expertise" / "api.jsonl").write_text(
        '{"type":"convention","content":"mixed case anchor lesson","classification":"tactical",'
        '"recorded_at":"2026-06-01T00:00:00.000Z","dir_anchors":["Src/Utils"],"id":"mx-case01"}\n',
        encoding="utf-8",
    )
    payload = {"session_id": "case-session", "tool_input": {"file_path": str(repo / "src" / "utils" / "db.py")}}
    monkeypatch.setattr(_sys, "stdin", io.StringIO(json.dumps(payload)))
    assert main(["hook", "pre-tool"]) == 0
    out = capsys.readouterr().out
    assert "mixed case anchor lesson" in out


def test_move_transfers_the_current_record_not_a_stale_snapshot(repo, monkeypatch, capsys):
    # a concurrent edit landing just before move's lock must be what arrives
    # in the target domain — not move's pre-lock snapshot
    import contextlib

    from slate import store as store_mod

    main(["record", "api", "--type", "convention", "--content", "original wording"])
    capsys.readouterr()
    source_path = repo / ".slate" / "expertise" / "api.jsonl"
    rid = json.loads(source_path.read_text(encoding="utf-8").splitlines()[0])["id"]

    real_lock = store_mod.file_lock
    state = {"edited": False}

    @contextlib.contextmanager
    def sneaky_lock(target):
        if not state["edited"] and target.name == "api.jsonl":
            state["edited"] = True
            record = json.loads(source_path.read_text(encoding="utf-8").splitlines()[0])
            record["content"] = "edited concurrently"
            source_path.write_text(json.dumps(record, separators=(",", ":")) + "\n", encoding="utf-8")
        with real_lock(target):
            yield

    monkeypatch.setattr(store_mod, "file_lock", sneaky_lock)
    assert main(["move", "api", rid, "storage"]) == 0
    target_text = (repo / ".slate" / "expertise" / "storage.jsonl").read_text(encoding="utf-8")
    assert "edited concurrently" in target_text
    assert "original wording" not in target_text


def test_move_rejects_same_source_and_target(repo, capsys):
    main(["record", "api", "--type", "convention", "--content", "some record"])
    capsys.readouterr()
    assert main(["move", "api", "mx-", "api"]) == 2


def test_doctor_flags_record_in_both_live_and_archive(repo, capsys):
    line = '{"type":"convention","content":"dup","classification":"observational","recorded_at":"2026-01-01T00:00:00.000Z","id":"mx-dupdup"}\n'
    (repo / ".slate" / "expertise" / "api.jsonl").write_text(line, encoding="utf-8")
    (repo / ".slate" / "archive").mkdir(exist_ok=True)
    (repo / ".slate" / "archive" / "api.jsonl").write_text("# ARCHIVED\n" + line, encoding="utf-8")
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "mx-dupdup" in out
    assert "archive" in out
