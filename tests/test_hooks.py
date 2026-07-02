import io
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from slate.cli import main


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLATE_NOW", "2026-07-01T12:00:00.000Z")
    # isolate session/ack/error state under the test tmp dir
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path / "tmp"))
    main(["init"])
    return tmp_path


def hook(monkeypatch, event, payload, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = main(["hook", event])
    return code, capsys.readouterr().out


def sid():
    return f"test-{uuid.uuid4().hex[:8]}"


# --- session-start ---


def test_session_start_injects_index_and_writes_state(repo, monkeypatch, capsys):
    main(["record", "api", "--type", "convention", "--content", "use uv for everything"])
    capsys.readouterr()
    session = sid()
    code, out = hook(monkeypatch, "session-start", {"session_id": session}, capsys)
    assert code == 0
    payload = json.loads(out)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "<slate-memory>" in context
    assert "use uv for everything" in context
    state = json.loads((repo / "tmp" / "slate" / f"{session}.json").read_text(encoding="utf-8"))
    assert state["session_id"] == session
    assert state["started_at"] > 0


def read_state(repo, session):
    return json.loads((repo / "tmp" / "slate" / f"{session}.json").read_text(encoding="utf-8"))


def write_state(repo, state):
    path = repo / "tmp" / "slate" / f"{state['session_id']}.json"
    path.write_text(json.dumps(state), encoding="utf-8")


def test_session_start_resume_preserves_state_and_is_silent(repo, monkeypatch, capsys):
    main(["record", "api", "--type", "convention", "--content", "use uv for everything"])
    capsys.readouterr()
    session = sid()
    hook(monkeypatch, "session-start", {"session_id": session}, capsys)
    state = read_state(repo, session)
    state["seen_files"] = ["src/store.py"]
    state["injected_ids"] = ["mx-abc123"]
    write_state(repo, state)

    code, out = hook(
        monkeypatch, "session-start", {"session_id": session, "source": "resume"}, capsys
    )
    assert code == 0
    assert out == ""  # context is intact — nothing to re-inject
    after = read_state(repo, session)
    assert after == state  # no wipe: seen_files/injected_ids/started_at untouched


def test_session_start_resume_without_state_behaves_like_startup(repo, monkeypatch, capsys):
    main(["record", "api", "--type", "convention", "--content", "use uv for everything"])
    capsys.readouterr()
    session = sid()
    code, out = hook(
        monkeypatch, "session-start", {"session_id": session, "source": "resume"}, capsys
    )
    assert code == 0
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "use uv for everything" in context
    state = read_state(repo, session)
    assert state["started_at"] > 0


def test_session_start_compact_keeps_started_at_clears_lists_and_emits(
    repo, monkeypatch, capsys
):
    main(["record", "api", "--type", "convention", "--content", "use uv for everything"])
    capsys.readouterr()
    session = sid()
    hook(monkeypatch, "session-start", {"session_id": session}, capsys)
    state = read_state(repo, session)
    state["started_at"] = 12345.678  # sentinel: must survive compact
    state["start_head"] = "cafe1234" * 5  # sentinel: the stop gate's diff baseline
    state["seen_files"] = ["src/store.py"]
    state["injected_ids"] = ["mx-abc123"]
    write_state(repo, state)

    code, out = hook(
        monkeypatch, "session-start", {"session_id": session, "source": "compact"}, capsys
    )
    assert code == 0
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "use uv for everything" in context  # context was lost — re-emit index
    after = read_state(repo, session)
    assert after["session_id"] == session
    assert after["started_at"] == 12345.678  # stop gate still spans the logical session
    assert after["start_head"] == "cafe1234" * 5  # compact must not lose the diff baseline
    assert after["seen_files"] == []  # anchored records may re-inject
    assert after["injected_ids"] == []


def test_session_start_compact_leaves_unknown_state_fields_alone(repo, monkeypatch, capsys):
    # greptile PR #3: clearing every list-valued field would silently wipe
    # future non-injection state (audit trails, suppression lists) on compact
    main(["record", "api", "--type", "convention", "--content", "use uv for everything"])
    capsys.readouterr()
    session = sid()
    hook(monkeypatch, "session-start", {"session_id": session}, capsys)
    state = read_state(repo, session)
    state["seen_files"] = ["src/store.py"]
    state["future_audit_trail"] = ["compact@t1"]  # unknown list field: must survive
    write_state(repo, state)

    hook(monkeypatch, "session-start", {"session_id": session, "source": "compact"}, capsys)
    after = read_state(repo, session)
    assert after["future_audit_trail"] == ["compact@t1"]
    assert after["seen_files"] == []  # only the injection-tracking lists clear
    assert after["injected_ids"] == []


def test_session_start_compact_without_state_behaves_like_startup(repo, monkeypatch, capsys):
    main(["record", "api", "--type", "convention", "--content", "use uv for everything"])
    capsys.readouterr()
    session = sid()
    code, out = hook(
        monkeypatch, "session-start", {"session_id": session, "source": "compact"}, capsys
    )
    assert code == 0
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "use uv for everything" in context
    state = read_state(repo, session)
    assert state["started_at"] > 0


def test_session_start_clear_resets_state_and_emits_index(repo, monkeypatch, capsys):
    main(["record", "api", "--type", "convention", "--content", "use uv for everything"])
    capsys.readouterr()
    session = sid()
    hook(monkeypatch, "session-start", {"session_id": session}, capsys)
    state = read_state(repo, session)
    state["started_at"] = 12345.678
    state["seen_files"] = ["src/store.py"]
    write_state(repo, state)

    code, out = hook(
        monkeypatch, "session-start", {"session_id": session, "source": "clear"}, capsys
    )
    assert code == 0
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "use uv for everything" in context
    after = read_state(repo, session)
    assert after["started_at"] != 12345.678  # fresh state, same as startup
    assert after["seen_files"] == []


def test_session_start_without_store_is_silent(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path / "tmp"))
    code, out = hook(monkeypatch, "session-start", {"session_id": sid()}, capsys)
    assert code == 0
    assert out == ""


def test_hook_fail_open_on_garbage_stdin(repo, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("this is not json"))
    assert main(["hook", "session-start"]) == 0
    assert capsys.readouterr().out == ""
    assert (repo / "tmp" / "slate" / "hook-errors.log").exists()


# --- pre-tool ---


def seed_anchored_record(capsys):
    main(["record", "storage", "--type", "pattern", "--name", "atomic writes",
          "--description", "temp file then os.replace", "--files", "src/store.py"])
    capsys.readouterr()


def test_pre_tool_injects_on_first_touch_only(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    session = sid()
    payload = {
        "session_id": session,
        "tool_name": "Edit",
        "tool_input": {"file_path": str(repo / "src" / "store.py")},
    }
    code, out = hook(monkeypatch, "pre-tool", payload, capsys)
    assert code == 0
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "atomic writes" in context
    assert "temp file then os.replace" in context
    # second touch of the same file: silent no-op
    code, out = hook(monkeypatch, "pre-tool", payload, capsys)
    assert code == 0
    assert out == ""


def test_pre_tool_dir_anchor_match(repo, monkeypatch, capsys):
    main(["record", "storage", "--type", "convention",
          "--content", "everything under src/io must use the atomic write helper",
          "--dir-anchor", "src/io"])
    capsys.readouterr()
    payload = {
        "session_id": sid(),
        "tool_input": {"file_path": str(repo / "src" / "io" / "writer.py")},
    }
    code, out = hook(monkeypatch, "pre-tool", payload, capsys)
    assert "atomic write helper" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_pre_tool_unrelated_file_is_silent(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    payload = {"session_id": sid(), "tool_input": {"file_path": str(repo / "docs" / "notes.md")}}
    code, out = hook(monkeypatch, "pre-tool", payload, capsys)
    assert code == 0
    assert out == ""


def test_pre_tool_backslash_paths_match_posix_anchors(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    windows_style = str(repo).replace("/", "\\") + "\\src\\store.py"
    payload = {"session_id": sid(), "tool_input": {"file_path": windows_style}}
    code, out = hook(monkeypatch, "pre-tool", payload, capsys)
    assert "atomic writes" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_pre_tool_fast_path_avoids_yaml_import(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    monkeypatch.delitem(sys.modules, "yaml", raising=False)
    payload = {"session_id": sid(), "tool_input": {"file_path": str(repo / "docs" / "x.md")}}
    hook(monkeypatch, "pre-tool", payload, capsys)
    assert "yaml" not in sys.modules


# --- pre-tool Read (index-only injection) ---


def read_payload(repo, session):
    return {
        "session_id": session,
        "tool_name": "Read",
        "tool_input": {"file_path": str(repo / "src" / "store.py")},
    }


def edit_payload(repo, session):
    return {
        "session_id": session,
        "tool_name": "Edit",
        "tool_input": {"file_path": str(repo / "src" / "store.py")},
    }


def test_read_injects_index_once_and_edit_still_injects_full(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    session = sid()
    code, out = hook(monkeypatch, "pre-tool", read_payload(repo, session), capsys)
    assert code == 0
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "atomic writes" in context  # the index line
    assert "temp file then os.replace" not in context  # not the full record
    assert "slate query" in context
    # second Read of the same file: silent
    code, out = hook(monkeypatch, "pre-tool", read_payload(repo, session), capsys)
    assert code == 0
    assert out == ""
    # a later Edit of the same file still injects the full records
    code, out = hook(monkeypatch, "pre-tool", edit_payload(repo, session), capsys)
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "temp file then os.replace" in context


def test_read_injection_is_capped_for_anchor_heavy_files(repo, monkeypatch, capsys):
    for i in range(15):
        main(["record", f"dom{i}", "--type", "pattern",
              "--name", f"store access pattern number {i}",
              "--description", "some detail", "--files", "src/store.py"])
    capsys.readouterr()
    code, out = hook(monkeypatch, "pre-tool", read_payload(repo, sid()), capsys)
    assert code == 0
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert context.count("[mx-") == 10  # capped, not all 15
    assert "5 more" in context


def test_read_of_unanchored_file_is_silent(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    payload = {
        "session_id": sid(),
        "tool_name": "Read",
        "tool_input": {"file_path": str(repo / "docs" / "notes.md")},
    }
    code, out = hook(monkeypatch, "pre-tool", payload, capsys)
    assert code == 0
    assert out == ""


def test_read_after_full_injection_is_silent(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    session = sid()
    _, out = hook(monkeypatch, "pre-tool", edit_payload(repo, session), capsys)
    assert "temp file then os.replace" in out
    code, out = hook(monkeypatch, "pre-tool", read_payload(repo, session), capsys)
    assert code == 0
    assert out == ""


def test_read_tolerates_old_state_file_without_new_fields(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    session = sid()
    old_state = {
        "session_id": session,
        "started_at": time.time(),
        "seen_files": [],
        "injected_ids": [],
        "stop_blocked": False,
    }
    state_file = repo / "tmp" / "slate" / f"{session}.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(old_state), encoding="utf-8")
    code, out = hook(monkeypatch, "pre-tool", read_payload(repo, session), capsys)
    assert code == 0
    assert "atomic writes" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert not (repo / "tmp" / "slate" / "hook-errors.log").exists()


# --- prompt (UserPromptSubmit retrieval) ---


def test_prompt_injects_matching_index_lines(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    main(["record", "api", "--type", "convention",
          "--content", "responses use problem+json errors"])
    capsys.readouterr()
    code, out = hook(
        monkeypatch,
        "prompt",
        {"session_id": sid(), "prompt": "fix the atomic writes in the store"},
        capsys,
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "<slate-memory>" in context
    assert "atomic writes" in context
    assert "slate query" in context
    assert "problem+json" not in context  # non-matching record is not suggested


def test_prompt_does_not_resuggest_across_prompts(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    session = sid()
    _, first = hook(
        monkeypatch, "prompt", {"session_id": session, "prompt": "atomic writes"}, capsys
    )
    assert "atomic writes" in json.loads(first)["hookSpecificOutput"]["additionalContext"]
    _, second = hook(
        monkeypatch, "prompt", {"session_id": session, "prompt": "atomic writes"}, capsys
    )
    assert second == ""


def test_prompt_skips_ids_already_injected_by_pre_tool(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    session = sid()
    edit = {
        "session_id": session,
        "tool_name": "Edit",
        "tool_input": {"file_path": str(repo / "src" / "store.py")},
    }
    hook(monkeypatch, "pre-tool", edit, capsys)
    code, out = hook(
        monkeypatch, "prompt", {"session_id": session, "prompt": "atomic writes"}, capsys
    )
    assert code == 0
    assert out == ""


def test_prompt_empty_missing_or_unmatched_is_silent(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    for prompt in ("", "   ", "quantum flux capacitor"):
        code, out = hook(monkeypatch, "prompt", {"session_id": sid(), "prompt": prompt}, capsys)
        assert code == 0
        assert out == ""
    code, out = hook(monkeypatch, "prompt", {"session_id": sid()}, capsys)
    assert code == 0
    assert out == ""


def test_prompt_without_store_is_silent(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path / "tmp"))
    code, out = hook(
        monkeypatch, "prompt", {"session_id": sid(), "prompt": "atomic writes"}, capsys
    )
    assert code == 0
    assert out == ""


def test_prompt_caps_suggestions_at_five(repo, monkeypatch, capsys):
    for i in range(7):
        main(["record", f"d{i}", "--type", "convention",
              "--content", f"retry backoff rule number {i}"])
    capsys.readouterr()
    code, out = hook(
        monkeypatch,
        "prompt",
        {"session_id": sid(), "prompt": "retry backoff rule"},
        capsys,
    )
    assert code == 0
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert context.count("[mx-") == 5


def test_prompt_budget_skips_oversize_line_but_keeps_shorter_hits(repo, monkeypatch, capsys):
    from slate.commands import hook as hook_mod

    long_content = ("alpha bravo charlie delta echo foxtrot " * 6).strip()
    main(["record", "d1", "--type", "convention", "--content", long_content])
    main(["record", "d2", "--type", "convention", "--content", "alpha bravo wins"])
    capsys.readouterr()
    # budget leaves room for the short line only; the top-ranked record's line
    # overshoots and must be skipped, not end the loop
    monkeypatch.setattr(hook_mod, "PROMPT_BUDGET", 40)
    code, out = hook(
        monkeypatch,
        "prompt",
        {"session_id": sid(), "prompt": "alpha bravo charlie delta echo foxtrot"},
        capsys,
    )
    assert code == 0
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "alpha bravo wins" in context  # the shorter, lower-ranked hit still lands
    assert "foxtrot" not in context  # the oversize top hit is skipped


def test_prompt_tolerates_old_state_file_without_new_fields(repo, monkeypatch, capsys):
    seed_anchored_record(capsys)
    session = sid()
    old_state = {
        "session_id": session,
        "started_at": time.time(),
        "seen_files": [],
        "injected_ids": [],
        "stop_blocked": False,
    }
    state_file = repo / "tmp" / "slate" / f"{session}.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(old_state), encoding="utf-8")
    code, out = hook(
        monkeypatch, "prompt", {"session_id": session, "prompt": "atomic writes"}, capsys
    )
    assert code == 0
    assert "atomic writes" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert not (repo / "tmp" / "slate" / "hook-errors.log").exists()


# --- stop gate ---


def git_repo(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    for i in range(4):
        (tmp_path / f"file{i}.py").write_text("x = 1\n" * 30, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=tmp_path, check=True)


@pytest.fixture
def stop_repo(tmp_path, monkeypatch, capsys):
    git_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLATE_NOW", "2026-07-01T12:00:00.000Z")
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path / "tmp"))
    main(["init"])
    main(["record", "api", "--type", "convention", "--content", "baseline lesson"])
    capsys.readouterr()
    time.sleep(0.05)  # let store mtimes land clearly before session start
    return tmp_path


def start_session(monkeypatch, capsys):
    session = sid()
    hook(monkeypatch, "session-start", {"session_id": session}, capsys)
    time.sleep(0.02)  # ensure later mtimes are strictly newer than started_at
    return session


def big_diff(repo):
    for i in range(4):
        (repo / f"file{i}.py").write_text("y = 2\n" * 30, encoding="utf-8")


def test_stop_blocks_when_diff_large_and_no_lesson(stop_repo, monkeypatch, capsys):
    session = start_session(monkeypatch, capsys)
    big_diff(stop_repo)
    code, out = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["decision"] == "block"
    assert "slate record" in payload["reason"]
    assert "slate ack --no-lessons" in payload["reason"]


def test_stop_respects_stop_hook_active(stop_repo, monkeypatch, capsys):
    session = start_session(monkeypatch, capsys)
    big_diff(stop_repo)
    code, out = hook(
        monkeypatch, "stop", {"session_id": session, "stop_hook_active": True}, capsys
    )
    assert out == ""


def test_stop_passes_on_small_diff(stop_repo, monkeypatch, capsys):
    session = start_session(monkeypatch, capsys)
    # 1 file (< 3) and 5+5 changed lines (< 40)
    (stop_repo / "file0.py").write_text("x = 1\n" * 25 + "y = 2\n" * 5, encoding="utf-8")
    code, out = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    assert out == ""


def test_stop_passes_after_store_write(stop_repo, monkeypatch, capsys):
    session = start_session(monkeypatch, capsys)
    big_diff(stop_repo)
    main(["record", "api", "--type", "failure", "--description", "forgot the lesson gate",
          "--resolution", "record as you go"])
    capsys.readouterr()
    code, out = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    assert out == ""


def test_stop_passes_after_ack(stop_repo, monkeypatch, capsys):
    session = start_session(monkeypatch, capsys)
    big_diff(stop_repo)
    assert main(["ack", "--no-lessons", "pure refactor, nothing learned"]) == 0
    capsys.readouterr()
    code, out = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    assert out == ""


def test_stop_passes_after_confirm(stop_repo, monkeypatch, capsys):
    session = start_session(monkeypatch, capsys)
    big_diff(stop_repo)
    baseline = json.loads(
        (stop_repo / ".slate" / "expertise" / "api.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert main(["confirm", "api", baseline["id"]]) == 0
    capsys.readouterr()
    code, out = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    assert out == ""  # the confirm advanced the store mtime, satisfying the gate


def test_stop_block_message_offers_confirm_when_records_were_injected(
    stop_repo, monkeypatch, capsys
):
    main(["record", "api", "--type", "pattern", "--name", "anchored pattern",
          "--description", "pattern anchored to file0", "--files", "file0.py"])
    capsys.readouterr()
    injected_id = json.loads(
        (stop_repo / ".slate" / "expertise" / "api.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )["id"]
    time.sleep(0.05)  # let the record's mtime land clearly before session start
    session = start_session(monkeypatch, capsys)
    payload = {
        "session_id": session,
        "tool_input": {"file_path": str(stop_repo / "file0.py")},
    }
    hook(monkeypatch, "pre-tool", payload, capsys)  # injects the anchored record
    big_diff(stop_repo)
    code, out = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    reason = json.loads(out)["reason"]
    assert "slate confirm" in reason
    assert injected_id in reason
    assert "slate record" in reason  # the original two exits survive
    assert "slate ack --no-lessons" in reason


def test_stop_block_message_omits_confirm_without_injected_records(
    stop_repo, monkeypatch, capsys
):
    session = start_session(monkeypatch, capsys)
    big_diff(stop_repo)
    code, out = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    reason = json.loads(out)["reason"]
    assert "slate confirm" not in reason


def test_stop_blocks_at_most_once_per_session(stop_repo, monkeypatch, capsys):
    session = start_session(monkeypatch, capsys)
    big_diff(stop_repo)
    _, first = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    assert json.loads(first)["decision"] == "block"
    _, second = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    assert second == ""


def test_stop_without_session_state_is_silent(stop_repo, monkeypatch, capsys):
    big_diff(stop_repo)
    code, out = hook(monkeypatch, "stop", {"session_id": sid()}, capsys)
    assert code == 0
    assert out == ""


# --- stop gate vs committed work (diff against session-start HEAD) ---


def commit_all(repo, message="wip"):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)


def state_file(repo, session):
    return repo / "tmp" / "slate" / f"{session}.json"


def test_session_start_records_start_head(stop_repo, monkeypatch, capsys):
    session = start_session(monkeypatch, capsys)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=stop_repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    state = json.loads(state_file(stop_repo, session).read_text(encoding="utf-8"))
    assert state["start_head"] == head


def test_session_start_resolves_head_from_store_repo(stop_repo, monkeypatch, capsys):
    # start_head must be resolved from the store's repo root — the same cwd
    # _stop passes to diff_stats — not from the ambient process cwd, so the
    # recorded SHA always belongs to the repo the stop gate later diffs
    from slate import gitctx

    seen = {}
    real = gitctx.head_commit

    def spy(cwd=None):
        seen["cwd"] = cwd
        return real(cwd)

    monkeypatch.setattr(gitctx, "head_commit", spy)
    start_session(monkeypatch, capsys)
    assert seen["cwd"] is not None
    assert Path(seen["cwd"]).resolve() == stop_repo.resolve()


def test_stop_blocks_when_changes_committed_during_session(stop_repo, monkeypatch, capsys):
    session = start_session(monkeypatch, capsys)
    big_diff(stop_repo)
    commit_all(stop_repo)  # clean working tree: HEAD diff alone would miss this
    code, out = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["decision"] == "block"
    assert "slate record" in payload["reason"]


def test_stop_old_state_without_start_head_falls_back_to_head_diff(
    stop_repo, monkeypatch, capsys
):
    session = start_session(monkeypatch, capsys)
    path = state_file(stop_repo, session)
    state = json.loads(path.read_text(encoding="utf-8"))
    state.pop("start_head", None)  # simulate a state file from an older slate
    path.write_text(json.dumps(state), encoding="utf-8")
    big_diff(stop_repo)  # uncommitted — HEAD diff still sees it
    code, out = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    assert code == 0
    assert json.loads(out)["decision"] == "block"


def test_stop_invalid_start_head_falls_back_to_head_diff(stop_repo, monkeypatch, capsys):
    session = start_session(monkeypatch, capsys)
    path = state_file(stop_repo, session)
    state = json.loads(path.read_text(encoding="utf-8"))
    state["start_head"] = "deadbeef" * 5  # commit that no longer exists
    path.write_text(json.dumps(state), encoding="utf-8")
    big_diff(stop_repo)
    code, out = hook(monkeypatch, "stop", {"session_id": session}, capsys)
    assert code == 0
    assert json.loads(out)["decision"] == "block"
