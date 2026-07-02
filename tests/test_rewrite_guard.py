"""A domain with unreadable lines must never be rewritten — a whole-file
rewrite would silently drop the bytes the tolerant reader skipped."""

import pytest

from slate.cli import main

GOOD = '{"type":"convention","content":"fine","classification":"tactical","recorded_at":"2026-01-01T00:00:00.000Z","id":"mx-00fine"}\n'
BROKEN = '{"type":"convention","content":"broken\n'


@pytest.fixture
def corrupt_repo(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLATE_NOW", "2026-07-01T12:00:00.000Z")
    main(["init"])
    path = tmp_path / ".slate" / "expertise" / "api.jsonl"
    path.write_text(GOOD + BROKEN, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "argv",
    [
        ["edit", "api", "mx-00fine", "--content", "changed"],
        ["delete", "api", "mx-00fine"],
        ["move", "api", "mx-00fine", "elsewhere"],
    ],
)
def test_rewrite_commands_refuse_corrupt_domain(corrupt_repo, argv, capsys):
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert "unreadable" in err
    assert "doctor" in err
    content = (corrupt_repo / ".slate" / "expertise" / "api.jsonl").read_text(encoding="utf-8")
    assert content == GOOD + BROKEN  # bytes untouched


def test_prune_skips_corrupt_domain(corrupt_repo, capsys):
    # the good record is stale (tactical, ~6 months old) but the domain is corrupt
    assert main(["prune"]) == 0
    out = capsys.readouterr().out
    assert "api" in out
    assert "skipped" in out
    content = (corrupt_repo / ".slate" / "expertise" / "api.jsonl").read_text(encoding="utf-8")
    assert content == GOOD + BROKEN
