"""slate hook <event> — internal, called only by installed Claude Code hooks.

Fail-open rule: every path catches every exception, exits 0 with no output,
and logs to <tempdir>/slate/hook-errors.log. A memory tool must never take
the agent's session down. The pre-tool fast path never imports PyYAML.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from slate import priming, sessions
from slate.anchors import file_lives_under_dir
from slate.store import find_store, to_posix

STOP_DEFAULTS = {"min_files": 3, "min_lines": 40}


def run(argv: list[str]) -> int:
    try:
        return _dispatch(argv)
    except BaseException:  # noqa: BLE001 — fail-open, always
        try:
            sessions.log_hook_error()
        except Exception:  # noqa: BLE001
            pass
        return 0


def _dispatch(argv: list[str]) -> int:
    event = argv[0] if argv else ""
    payload: dict = {}
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            payload = json.loads(raw)
    if event == "session-start":
        return _session_start(payload)
    if event == "pre-tool":
        return _pre_tool(payload)
    if event == "stop":
        return _stop(payload)
    return 0


def _emit(event_name: str, context: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event_name,
                    "additionalContext": context,
                }
            }
        )
    )


def _session_start(payload: dict) -> int:
    session_id = str(payload.get("session_id") or "unknown")
    source = payload.get("source")
    prior = sessions.load_state(session_id) if source in ("resume", "compact") else None

    if source == "resume" and prior is not None:
        # conversation context is intact: keep the state untouched (a wipe
        # would re-inject every anchored record) and emit nothing (the index
        # is already in context)
        return 0

    if source == "compact" and prior is not None:
        # context was summarized away: clear exactly the injection-tracking
        # lists so records re-inject, but keep started_at (and every other
        # field, known or not) — the stop gate compares store mtimes against
        # started_at, and a compact is mid-logical-session, not a new one
        prior["seen_files"] = []
        prior["injected_ids"] = []
        sessions.save_state(prior)
    else:
        # startup / clear / unknown source, or no prior state to preserve
        sessions.save_state(sessions.new_state(session_id))

    store = find_store()
    if store is None:
        return 0
    domain_records: dict[str, list[dict]] = {}
    for domain in store.domains():
        records, _ = store.read(domain)
        if records:
            domain_records[domain] = records
    if not domain_records:
        return 0

    budget = priming.DEFAULT_BUDGET
    tier_weights = None
    try:
        from slate import config as config_mod

        cfg = config_mod.load(store)
        budget = int(cfg["prime"]["budget"])
        tier_weights = cfg["prime"]["tier_weights"]
    except Exception:  # noqa: BLE001 — config trouble never blocks injection
        pass

    body = priming.render_index(domain_records, budget=budget, tier_weights=tier_weights)
    _emit("SessionStart", priming.wrap_delimited(body))
    return 0


def _relative_to_repo(file_path: str, repo_root: Path) -> str:
    normalized = to_posix(file_path)
    try:
        return to_posix(str(Path(normalized).resolve().relative_to(repo_root.resolve())))
    except (ValueError, OSError):
        return normalized


def _matches(record: dict, rel_path: str) -> bool:
    # case-insensitive on both axes: CI targets macOS/Windows, whose
    # filesystems don't distinguish Src/Utils from src/utils
    rel = rel_path.lower()
    for record_file in record.get("files") or []:
        f = to_posix(record_file).lower()
        if rel == f or rel.endswith("/" + f) or f.endswith("/" + rel):
            return True
    for anchor in record.get("dir_anchors") or []:
        if file_lives_under_dir(rel, anchor.lower()):
            return True
    return False


def _pre_tool(payload: dict) -> int:
    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path:
        return 0
    store = find_store()
    if store is None:
        return 0

    session_id = str(payload.get("session_id") or "unknown")
    state = sessions.load_state(session_id) or sessions.new_state(session_id)

    rel = _relative_to_repo(str(file_path), store.root.parent)
    if rel in state["seen_files"]:
        return 0
    state["seen_files"].append(rel)

    matched: dict[str, list[dict]] = {}
    for domain in store.domains():
        records, _ = store.read(domain)
        hits = [
            r
            for r in records
            # id-less records dedup per-file via seen_files only — tracking
            # them as None here would suppress every later id-less record
            if (r.get("id") is None or r["id"] not in state["injected_ids"])
            and _matches(r, rel)
        ]
        if hits:
            matched[domain] = hits

    if matched:
        for records in matched.values():
            state["injected_ids"].extend(r["id"] for r in records if r.get("id"))
        body = priming.render_full(matched)
        header = f"Records anchored to {rel}:\n\n"
        _emit("PreToolUse", priming.wrap_delimited(header + body))
    sessions.save_state(state)
    return 0


def _stop(payload: dict) -> int:
    if payload.get("stop_hook_active"):
        return 0
    store = find_store()
    if store is None:
        return 0
    session_id = str(payload.get("session_id") or "unknown")
    state = sessions.load_state(session_id)
    if state is None or not state.get("started_at"):
        return 0  # no session-start marker — nothing to compare against
    if state.get("stop_blocked"):
        return 0  # block at most once per session

    thresholds = dict(STOP_DEFAULTS)
    try:
        from slate import config as config_mod

        thresholds.update(config_mod.load(store)["enforcement"]["stop_gate"])
    except Exception:  # noqa: BLE001 — fail-open on config trouble
        pass

    from slate import gitctx

    files, lines = gitctx.diff_stats(store.root.parent)
    if files < thresholds["min_files"] and lines < thresholds["min_lines"]:
        return 0

    started_at = float(state["started_at"])
    latest = store.latest_mtime()
    if latest is not None and latest >= started_at:
        return 0  # a lesson (or any store write) landed this session

    ack = sessions.read_ack(store.root)
    if ack and float(ack.get("ts", 0)) >= started_at:
        return 0

    state["stop_blocked"] = True
    sessions.save_state(state)
    reason = (
        f"This session changed {files} file(s) / {lines} line(s) but recorded no lesson. "
        "Two ways to finish: record one — "
        "slate record <domain> --type <convention|pattern|failure|decision|reference|guide> ... "
        '— or acknowledge there was nothing to learn: slate ack --no-lessons "<reason>".'
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0
