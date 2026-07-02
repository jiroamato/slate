import json

import pytest

from slate.cli import main


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLATE_NOW", "2026-07-01T12:00:00.000Z")
    main(["init"])
    main(["record", "api", "--type", "pattern", "--name", "atomic writes",
          "--description", "temp file plus replace", "--tags", "io"])
    main(["record", "api", "--type", "convention", "--content", "keep deps minimal"])
    return tmp_path


def records(tmp_path, domain):
    path = tmp_path / ".slate" / "expertise" / f"{domain}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rid(tmp_path, domain, index=0):
    return records(tmp_path, domain)[index]["id"]


def test_edit_updates_fields_and_preserves_others(seeded, capsys):
    target = rid(seeded, "api", 0)
    assert main(["edit", "api", target, "--description", "temp file then os.replace",
                 "--classification", "foundational"]) == 0
    rec = records(seeded, "api")[0]
    assert rec["description"] == "temp file then os.replace"
    assert rec["classification"] == "foundational"
    assert rec["name"] == "atomic writes"
    assert rec["tags"] == ["io"]
    assert rec["id"] == target


def test_edit_revalidates(seeded, capsys):
    target = rid(seeded, "api", 0)
    assert main(["edit", "api", target, "--description", ""]) == 2
    assert records(seeded, "api")[0]["description"] == "temp file plus replace"


def test_edit_unknown_id_fails(seeded):
    assert main(["edit", "api", "mx-ffffff", "--description", "x"]) == 2


def test_delete_removes_record(seeded, capsys):
    target = rid(seeded, "api", 1)
    assert main(["delete", "api", target]) == 0
    remaining = records(seeded, "api")
    assert len(remaining) == 1
    assert remaining[0]["id"] != target


def test_delete_dry_run_keeps_record(seeded):
    target = rid(seeded, "api", 1)
    assert main(["delete", "api", target, "--dry-run"]) == 0
    assert len(records(seeded, "api")) == 2


def test_move_preserves_id_and_warns_on_incoming_refs(seeded, capsys):
    target = rid(seeded, "api", 0)
    main(["record", "cli", "--type", "convention", "--content", "related note",
          "--relates-to", f"api:{target}"])
    capsys.readouterr()
    assert main(["move", "api", target, "storage"]) == 0
    out = capsys.readouterr().out
    assert len(records(seeded, "api")) == 1
    moved = records(seeded, "storage")[0]
    assert moved["id"] == target
    assert moved["name"] == "atomic writes"
    assert "reference" in out.lower()  # incoming-ref warning surfaced


def test_move_json_envelope(seeded, capsys):
    target = rid(seeded, "api", 1)
    assert main(["move", "api", target, "misc", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["source"] == "api"
    assert payload["target"] == "misc"
