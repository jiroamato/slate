import json

from slate.cli import main


def test_init_creates_store_layout(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "Initialized" in out
    assert (tmp_path / ".slate" / "expertise").is_dir()
    assert (tmp_path / ".slate" / "cache").is_dir()
    assert (tmp_path / ".slate" / ".gitignore").read_text(encoding="utf-8") == "cache/\n"
    config_text = (tmp_path / ".slate" / "slate.config.yaml").read_text(encoding="utf-8")
    assert "schema_version: 1" in config_text
    assert "max_entries: 100" in config_text
    attrs = (tmp_path / ".gitattributes").read_text(encoding="utf-8")
    assert ".slate/expertise/*.jsonl merge=union" in attrs


def test_init_from_subdirectory_targets_git_root(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "src" / "nested"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert main(["init"]) == 0
    assert (tmp_path / ".slate").is_dir()
    assert not (sub / ".slate").exists()


def test_init_is_idempotent(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    main(["init"])
    capsys.readouterr()
    assert main(["init", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["created"] is False
    attrs = (tmp_path / ".gitattributes").read_text(encoding="utf-8")
    assert attrs.count("merge=union") == 1


def test_init_preserves_existing_config(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    main(["init"])
    cfg = tmp_path / ".slate" / "slate.config.yaml"
    cfg.write_text("version: '1'\ncustom: true\n", encoding="utf-8")
    main(["init"])
    assert "custom: true" in cfg.read_text(encoding="utf-8")


def test_unknown_command_exits_2_and_lists_commands(capsys):
    assert main(["frobnicate"]) == 2
    err = capsys.readouterr().err
    assert "frobnicate" in err
    assert "init" in err


def test_unknown_command_json_envelope(capsys):
    assert main(["frobnicate", "--json"]) == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "usage"
