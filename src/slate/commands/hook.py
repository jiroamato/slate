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
    if event == "prompt":
        return _prompt(payload)
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

    store = find_store()
    if source == "compact" and prior is not None:
        # context was summarized away: clear exactly the injection-tracking
        # lists so records re-inject, but keep started_at and start_head (and
        # every other field, known or not) — the stop gate diffs against
        # start_head and compares store mtimes against started_at, and a
        # compact is mid-logical-session, not a new one
        prior["seen_files"] = []
        prior["injected_ids"] = []
        sessions.save_state(prior)
    else:
        # startup / clear / unknown source, or no prior state to preserve
        from slate import gitctx

        # remember HEAD so the stop gate can count work committed mid-session;
        # resolve it from the store's repo root — the same cwd _stop diffs in —
        # so the SHA always belongs to the repo the gate later measures
        start_head = gitctx.head_commit(store.root.parent if store else None)
        sessions.save_state(sessions.new_state(session_id, start_head=start_head))

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
    if str(payload.get("tool_name") or "") == "Read":
        return _pre_tool_read(store, state, rel)
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


READ_BUDGET = 600  # tokens — index hints only; the first edit injects records in full
READ_MAX_HITS = 10


def _pre_tool_read(store, state: dict, rel: str) -> int:
    """Read of an anchored file: inject index lines only, once per file.
    Deliberately does NOT touch seen_files/injected_ids — a later Edit of the
    same file must still inject the full records."""
    # setdefault: state files written before this field existed must still load
    read_seen = state.setdefault("read_seen_files", [])
    if rel in read_seen or rel in state["seen_files"]:
        return 0  # already read-injected, or the full records already went in
    read_seen.append(rel)

    matched: list[tuple[str, dict]] = []
    for domain in store.domains():
        records, _ = store.read(domain)
        matched.extend(
            (domain, r)
            for r in records
            if (r.get("id") is None or r["id"] not in state["injected_ids"])
            and _matches(r, rel)
        )
    if matched:
        # best records first, capped like the prompt hook — an anchor-heavy
        # file must not blow a hole in the context window
        order = {id(r): i for i, r in enumerate(priming.rank([r for _, r in matched]))}
        matched.sort(key=lambda pair: order[id(pair[1])])
        header = (
            f"Recorded lessons anchored to {rel} — index only, full records "
            "inject on first edit (fetch now: slate query <domain> --id <id>):\n\n"
        )
        used = priming.estimate_tokens(header)
        lines: list[str] = []
        omitted = 0
        for domain, record in matched:
            line = f"{domain}: {priming.index_line(record)}"
            cost = priming.estimate_tokens(line)
            if len(lines) >= READ_MAX_HITS or used + cost > READ_BUDGET:
                omitted += 1
                continue
            lines.append(line)
            used += cost
        if omitted:
            lines.append(f"…{omitted} more — the first edit injects the full set")
        _emit("PreToolUse", priming.wrap_delimited(header + "\n".join(lines)))
    sessions.save_state(state)
    return 0


PROMPT_BUDGET = 600  # tokens — deliberately small; these are hints, not priming
PROMPT_MAX_HITS = 5


def _prompt(payload: dict) -> int:
    """UserPromptSubmit: BM25-search the prompt text across all domains and
    suggest the top index lines. Each record id is suggested at most once per
    session, and never after its full record was already injected."""
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return 0
    store = find_store()
    if store is None:
        return 0

    from slate import search  # not needed on the pre-tool fast path

    session_id = str(payload.get("session_id") or "unknown")
    state = sessions.load_state(session_id) or sessions.new_state(session_id)
    # setdefault: state files written before this field existed must still load
    suggested = state.setdefault("prompt_suggested_ids", [])
    already = set(state["injected_ids"]) | set(suggested)

    corpus: list[dict] = []
    domain_of: dict[int, str] = {}
    for domain in store.domains():
        records, _ = store.read(domain)
        for record in records:
            corpus.append(record)
            domain_of[id(record)] = domain

    header = (
        "Possibly relevant recorded lessons for this request "
        "(fetch: slate query <domain> --id <id>):\n\n"
    )
    used = priming.estimate_tokens(header)
    lines: list[str] = []
    picked: list[str] = []
    for record, _score in search.search_records(corpus, prompt):
        rid = record.get("id")
        if not rid or rid in already:
            continue  # id-less records can't be fetched by id — skip them
        line = f"{domain_of[id(record)]}: {priming.index_line(record)}"
        cost = priming.estimate_tokens(line)
        if used + cost > PROMPT_BUDGET:
            continue  # oversize line — a shorter lower-ranked hit may still fit
        already.add(rid)
        picked.append(rid)
        lines.append(line)
        used += cost
        if len(lines) >= PROMPT_MAX_HITS:
            break

    if not lines:
        return 0
    suggested.extend(picked)
    sessions.save_state(state)
    _emit("UserPromptSubmit", priming.wrap_delimited(header + "\n".join(lines)))
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

    # diff against the session-start HEAD so work committed during the session
    # still counts; missing/invalid start_head falls back to HEAD inside
    # diff_stats (old state files, rewritten history)
    files, lines = gitctx.diff_stats(store.root.parent, base=state.get("start_head"))
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
    injected = list(dict.fromkeys(i for i in state.get("injected_ids") or [] if i))[:3]
    ways = "Three" if injected else "Two"
    reason = (
        f"This session changed {files} file(s) / {lines} line(s) but recorded no lesson. "
        f"{ways} ways to finish: record one — "
        "slate record <domain> --type <convention|pattern|failure|decision|reference|guide> ... "
        '— or acknowledge there was nothing to learn: slate ack --no-lessons "<reason>".'
    )
    if injected:
        reason += (
            " Or confirm a record that helped this session: slate confirm <domain> <id> "
            f"(injected this session: {', '.join(injected)})."
        )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0
