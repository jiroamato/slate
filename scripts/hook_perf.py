"""CI perf gate: the no-op `slate hook pre-tool` path must stay fast.

Local budget is ~150ms; the CI ceiling is 500ms to absorb runner variance
while still catching import-time regressions (e.g. PyYAML sneaking onto the
hot path). Reports the best of five runs to filter out cold-start noise.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CEILING_MS = 500
RUNS = 5


def main() -> int:
    work = Path(tempfile.mkdtemp())
    (work / ".git").mkdir()
    subprocess.run(
        [sys.executable, "-m", "slate.cli", "init"], cwd=work, check=True, capture_output=True
    )
    payload = json.dumps(
        {"session_id": "perf", "tool_input": {"file_path": str(work / "docs" / "unmatched.md")}}
    )

    best = None
    for _ in range(RUNS):
        started = time.perf_counter()
        result = subprocess.run(
            [sys.executable, "-m", "slate.cli", "hook", "pre-tool"],
            cwd=work,
            input=payload,
            text=True,
            capture_output=True,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if result.returncode != 0:
            print(f"hook exited {result.returncode}: {result.stderr}")
            return 1
        best = elapsed_ms if best is None else min(best, elapsed_ms)

    print(f"no-op pre-tool best of {RUNS}: {best:.1f}ms (ceiling {CEILING_MS}ms)")
    return 0 if best < CEILING_MS else 1


if __name__ == "__main__":
    sys.exit(main())
