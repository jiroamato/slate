"""Golden-store parity harness: every read command runs against a vendored
.mulch/ store with snapshot-asserted output. Snapshots self-create on first
run; delete a snapshot file to intentionally regenerate it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from slate.cli import main

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / ".mulch"
SNAPSHOTS = Path(__file__).parent / "snapshots"


@pytest.fixture
def golden(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    shutil.copytree(GOLDEN, tmp_path / ".mulch")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLATE_NOW", "2026-07-01T12:00:00.000Z")
    return tmp_path


def assert_snapshot(name: str, actual: str) -> None:
    SNAPSHOTS.mkdir(exist_ok=True)
    path = SNAPSHOTS / f"{name}.txt"
    if not path.exists():
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(actual)
        pytest.skip(f"snapshot {name} created — rerun to assert")
    expected = path.read_text(encoding="utf-8")
    assert actual == expected, f"snapshot mismatch: {path}"


@pytest.mark.parametrize(
    ("name", "argv", "expected_exit"),
    [
        ("prime_index", ["prime"], 0),
        ("prime_full", ["prime", "--full"], 0),
        ("prime_files_scoped", ["prime", "--files", "src/store.py"], 0),
        ("query_all", ["query", "--all"], 0),
        ("query_full", ["query", "api", "--format", "full"], 0),
        ("search_atomic", ["search", "atomic temp file replace"], 0),
        ("status", ["status"], 0),
        ("doctor", ["doctor"], 1),  # corrupt.jsonl line 2 must fail the store
        ("prune_dry_run", ["prune", "--dry-run"], 0),
    ],
)
def test_golden_snapshots(golden, capsys, name, argv, expected_exit):
    code = main(argv)
    out = capsys.readouterr().out
    assert code == expected_exit, f"{argv} exited {code}, expected {expected_exit}\n{out}"
    assert_snapshot(name, out)


def test_golden_store_reads_without_mutation(golden):
    before = {
        p.name: p.read_bytes() for p in (golden / ".mulch" / "expertise").glob("*.jsonl")
    }
    main(["prime"])
    main(["query", "--all"])
    main(["search", "atomic"])
    main(["status"])
    main(["doctor"])
    after = {
        p.name: p.read_bytes() for p in (golden / ".mulch" / "expertise").glob("*.jsonl")
    }
    assert before == after  # read commands never touch a mulch store


def test_golden_unknown_type_is_primed_and_searchable(golden, capsys):
    main(["prime"])
    out = capsys.readouterr().out
    assert "mx-9a1b2c" in out  # the benchmark record survives the index
    main(["search", "jsonl read throughput"])
    assert "mx-9a1b2c" in capsys.readouterr().out


def test_golden_stale_reference_is_pruned(golden, capsys):
    assert main(["prune"]) == 0
    out = capsys.readouterr().out
    assert "api: archived 1 stale record(s)" in out
    archive = (golden / ".mulch" / "archive" / "api.jsonl").read_text(encoding="utf-8")
    assert archive.splitlines()[0].startswith("# ARCHIVED")
    assert "mulch upstream" in archive
