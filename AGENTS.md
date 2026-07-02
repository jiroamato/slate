# AGENTS.md

Guidance for AI coding agents working in this repository.

Slate is a git-native memory system for AI coding agents: a Python true-fork
of [mulch](https://github.com/jayminwest/mulch) with hook enforcement. The
approved design spec is
[docs/superpowers/specs/2026-07-01-slate-design.md](docs/superpowers/specs/2026-07-01-slate-design.md)
— **read it before making design claims; it supersedes anything inferred from
code.** The implementation plan (with mulch-parity constants) is
[docs/superpowers/plans/2026-07-01-slate-v0.1.md](docs/superpowers/plans/2026-07-01-slate-v0.1.md).

## Commands

```bash
uv sync                                  # install (creates .venv)
uv run pytest -q                         # full test suite
uv run pytest tests/test_store.py -q     # one file
uv run pytest tests/test_hooks.py::test_stop_blocks_when_diff_large_and_no_lesson -q   # one test
uv run ruff check                        # lint (CI-enforced)
uv run slate <command>                   # run the CLI from source
bash scripts/byte_identity.sh            # cross-OS byte-identity digest (must be stable)
uv run python scripts/hook_perf.py       # hook hot-path perf gate (<500ms)
```

## Architecture

**Library-first.** Every module under `src/slate/commands/` is a thin argparse
wrapper over library functions in `src/slate/` — the planned v0.2 MCP server
reuses those functions unchanged. `cli.py` dispatches by importing exactly one
command module per invocation (lazy `importlib`), so the hook hot path never
pays for parsers it doesn't use.

**`store.py` is the only module that opens store files.** It hardcodes the
portability contract: UTF-8, `\n` newlines, POSIX path separators, compact
JSON (`separators=(",", ":")`, `ensure_ascii=False`) — identical bytes on
every OS. CI enforces this: `scripts/byte_identity.sh` runs the same
store-mutating script on ubuntu/windows/macos and the digests must match.

**Whole-file rewrites go through `Store.mutate(domain, fn)`** — a locked
read-modify-write. Never build a rewrite from records read *before* taking the
lock; that reintroduces the TOCTOU race where a concurrent `store.append` is
silently dropped. `fn` returns the new record list, or `None` to skip writing.

**Never-lose orderings.** When an operation spans two files, the copy is
created before the original is removed (`move`: append-to-target before
source rewrite; `prune`: archive-append before live rewrite, both inside the
domain lock). A crash duplicates a record — visible, recoverable, flagged by
`doctor` — it never deletes one.

**Tolerant reader, guarded writer.** Reads never throw on bad data: malformed
JSONL lines are skipped with a `file:line` warning, unknown-type records are
preserved/primed/searched (validated only when the type is one of the six
builtins). But `Store.mutate` **refuses** domains with unreadable lines — a
rewrite would silently drop the skipped bytes.

**Hooks are fail-open, always.** Every `slate hook *` path catches
`BaseException`, exits 0 with no output, and logs to
`<tempdir>/slate/hook-errors.log`. The pre-tool fast path must not import
PyYAML (there's a test asserting this via `sys.modules`). Session state and
ack markers live in `<tempdir>/slate/` and are written atomically.

**Agent-legible errors.** All errors flow through `output.SlateError(message,
code, exit_code, hint, retry)`. Exit codes are contractual: `0` ok ·
`1` unexpected · `2` validation/usage · `3` dedup-blocked · `4` lock timeout ·
`5` no store. `--json` envelopes: `{ok, command, ...}` /
`{ok: false, error: {code, message, hint, retry}}`.

## Mulch parity

Parity constants (record schema, `mx-` id hashing, BM25 k1/b + ASCII
tokenizer, lock timings 50ms/5s/30s, truncation rules, archive banner, config
defaults) were transcribed from mulch 0.10.7 source into the implementation
plan — **do not re-derive or "improve" them**; existing `.mulch/` stores must
keep working unmodified. Slate-only deltas (exit codes, `{ok,...}` envelope,
normalized dedup threshold, index-default prime) are listed in the plan's
"Slate deltas" section.

## Testing conventions

- TDD: failing test first, then the fix. Every review finding gets a
  regression test (see `tests/test_review_fixes.py` for the patterns,
  including the sneaky-lock trick for simulating concurrent writers).
- Snapshot tests (`tests/test_golden.py`) run commands against the vendored
  mulch store in `tests/fixtures/golden/.mulch/` and compare stdout to
  `tests/snapshots/*.txt`. Snapshots self-create when missing — delete a
  snapshot file to intentionally regenerate it. Output that feeds snapshots
  must be machine-independent (repo-relative paths, no timestamps that aren't
  pinned).
- `SLATE_NOW` (ISO-8601) overrides `schema.now_iso()` for determinism; tests
  and the byte-identity script depend on it.
- Hook tests isolate temp state by monkeypatching `tempfile.gettempdir` to a
  per-test directory.

## Repo conventions

- Runtime dependency: **PyYAML only.** New runtime deps are a spec change,
  not a code change. (`slate[semantic]` / `slate[mcp]` extras are reserved
  empty stubs for v0.2.)
- Semantic commits (`feat:` / `fix:` / `test:` / `docs:` / `ci:` / `chore:`),
  small and green — the full suite and `ruff check` pass at every commit.
- Work on feature branches; PRs into `main`.
