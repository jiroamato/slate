#!/usr/bin/env bash
# Byte-identity harness: run an identical command script on every OS and
# print a sha256 digest of the resulting store tree. CI asserts the digest
# matches across ubuntu / windows / macos.
set -euo pipefail

REPO="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
WORK="$(mktemp -d)"
cd "$WORK"

slate() { uv run --project "$REPO" --quiet slate "$@" 1>&2; }
id_of() {
  uv run --project "$REPO" --quiet python -c \
    "import hashlib,sys;print('mx-'+hashlib.sha256((sys.argv[1]+':'+sys.argv[2]).encode()).hexdigest()[:6])" \
    "$1" "$2"
}

export SLATE_NOW=2026-07-01T00:00:00.000Z
slate init

slate record api --type convention \
  --content "use uv for python dependency management" \
  --classification foundational --tags "tooling,python"

SLATE_NOW=2026-07-02T00:00:00.000Z slate record api --type pattern \
  --name "atomic writes" \
  --description "write to a temp file in the same directory then os.replace" \
  --files "src/store.py,src/io.py" --dir-anchor "src"

SLATE_NOW=2026-07-03T00:00:00.000Z slate record cli --type decision \
  --title "argparse over click" \
  --rationale "stdlib keeps runtime dependencies to pyyaml only" \
  --evidence-issue "#12"

SLATE_NOW=2026-07-04T00:00:00.000Z slate record cli --type failure \
  --description "hook imported yaml on the hot path" \
  --resolution "defer the import until config is actually needed"

# stale-by-construction record, pruned below
SLATE_NOW=2026-05-01T00:00:00.000Z slate record cli --type reference \
  --name "old scratch notes" --description "superseded exploration notes" \
  --classification observational

# whole-file rewrites: edit, move, delete
PATTERN_ID="$(id_of pattern "atomic writes")"
DECISION_ID="$(id_of decision "argparse over click")"
FAILURE_ID="$(id_of failure "hook imported yaml on the hot path")"

SLATE_NOW=2026-07-05T00:00:00.000Z slate edit api "$PATTERN_ID" \
  --description "same-directory temp file then os.replace with bounded retry"
SLATE_NOW=2026-07-05T00:00:00.000Z slate move cli "$FAILURE_ID" api
SLATE_NOW=2026-07-05T00:00:00.000Z slate delete cli "$DECISION_ID"

# archive path: prune the stale reference
SLATE_NOW=2026-07-06T00:00:00.000Z slate prune

uv run --project "$REPO" --quiet python - <<'PY'
import hashlib
from pathlib import Path

digest = hashlib.sha256()
root = Path(".slate")
for path in sorted(root.rglob("*")):
    if not path.is_file() or "cache" in path.parts or path.suffix == ".lock":
        continue
    digest.update(path.relative_to(root).as_posix().encode())
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")
print(digest.hexdigest())
PY
