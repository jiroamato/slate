# slate

Git-native memory for AI coding agents — typed lessons that live in your repo,
retrieved when they matter, **enforced by hooks**.

Slate is a true fork of [mulch](https://github.com/jayminwest/mulch) rewritten
in Python. It keeps mulch's on-disk format (existing `.mulch/` stores work
as-is) and differentiates on two fronts:

- **Enforcement** — `slate setup claude` installs hooks that make agents
  actually read and write memory: an index injected at session start,
  file-scoped lessons injected when an anchored file is first touched, and a
  stop gate that asks (once) for a lesson when a session ends with significant
  changes and nothing recorded.
- **Agent ergonomics** — index-then-fetch priming that respects a token
  budget, errors that name the problem, the valid options, and the exact retry
  command, and a write-time dedup gate that blocks near-duplicate lessons with
  three explicit ways forward.

## Install

```bash
uv tool install slate-memory   # or: pipx install slate-memory / uvx slate-memory
```

Python ≥ 3.11. Runtime dependency: PyYAML only.

## Quickstart

```bash
cd your-repo
slate init                      # creates .slate/ (config, expertise/, gitignored cache/)
slate setup claude              # installs hooks + permission rules into .claude/settings.json

# record lessons as you learn them
slate record api --type convention --content "http handlers return typed envelopes"
slate record storage --type pattern --name "atomic writes" \
  --description "same-directory temp file then os.replace" --files "src/store.py"

slate prime                     # compact ranked index (what agents see at session start)
slate query storage --id mx-ab12cd   # fetch one full record
slate search "atomic writes"    # BM25 across domains
slate sync                      # validate, then commit store paths only
```

### Record types

`convention` · `pattern` · `failure` · `decision` · `reference` · `guide` —
mulch's six built-ins, with classification (`foundational` / `tactical` /
`observational`), tags, evidence, `relates_to` / `supersedes` links, file and
directory anchors. Records of unknown types are preserved, primed, and
searched — never dropped.

### Enforcement model

| Hook | What it does |
|---|---|
| SessionStart | Injects a budget-capped index of all lessons (delimited, marked as background reference) |
| PreToolUse (Edit\|Write) | First touch of a file matching a record's `files`/`dir_anchors` injects those full records — once per file per session |
| Stop | If the session changed ≥3 files or ≥40 lines and no lesson was recorded (and no ack), blocks turn-end **once** with instructions |
| Permissions | Denies direct Edit/Write on `.slate/expertise/*.jsonl` so the CLI (validation + dedup gate) is the only write path |

Escape valve: `slate ack --no-lessons "pure refactor, nothing learned"`.

All hooks are **fail-open**: any internal error exits 0 silently (logged to
`<tempdir>/slate/hook-errors.log`). A memory tool must never take a session
down.

### Dedup gate

`slate record` BM25-scores the new lesson against the target domain. Above the
similarity threshold (`dedup.threshold`, default 0.6) the write is blocked
(exit 3) and the response shows the existing record plus three paths: edit it,
`--force --supersedes <id>`, or rephrase. Forced writes are logged so
`slate doctor` can report whether the gate is helping or being bypassed.

## Exit codes & JSON

Every command takes `--json` and uses stable exit codes:
`0` ok · `1` unexpected · `2` validation/usage · `3` dedup-blocked ·
`4` lock timeout · `5` no store.

Errors follow one contract, in text and JSON:
`{ok: false, error: {code, message, hint, retry}}`.

## Mulch compatibility

- Reads existing `.mulch/` stores in place (`.slate/` wins if both exist);
  `mulch.config.yaml` is accepted wherever `slate.config.yaml` is.
- Same JSONL record format, ids (`mx-` + sha256 prefix), BM25 parameters,
  lock protocol (50ms retry / 5s timeout / 30s stale cleanup), `merge=union`
  gitattributes, and archive banner format.
- v0.1 scope cuts (deliberate): prune archives stale records but doesn't run
  mulch's tier-demotion/anchor-decay ladder; prime formats are
  index/markdown/compact/plain (no xml); the custom-type registry is v0.2 —
  unknown types get the tolerant reader instead.

## Portability

One canonical on-disk format on every OS: UTF-8, `\n` newlines, POSIX path
separators, compact JSON. CI runs the same store-mutating script on ubuntu,
windows and macos and asserts the resulting bytes are identical, and gates the
hook hot path under 500ms.

## Roadmap (v0.2+)

MCP server (`slate serve`), semantic/hybrid search (`slate[semantic]`),
custom-type registry, retrieval→outcome feedback, layered stores, setup
recipes for more harnesses. See
[docs/superpowers/specs](docs/superpowers/specs/2026-07-01-slate-design.md).

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check
```

MIT © Jiro Amato
