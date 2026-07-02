import json

import pytest

from slate.cli import main


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    main(["init"])
    return tmp_path


def settings(repo):
    return json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))


def hook_commands(cfg, event):
    return [
        h["command"]
        for entry in cfg.get("hooks", {}).get(event, [])
        for h in entry.get("hooks", [])
    ]


def test_setup_claude_installs_hooks_and_permissions(repo, capsys):
    assert main(["setup", "claude"]) == 0
    cfg = settings(repo)
    assert "slate hook session-start" in hook_commands(cfg, "SessionStart")
    assert "slate hook pre-tool" in hook_commands(cfg, "PreToolUse")
    assert "slate hook stop" in hook_commands(cfg, "Stop")
    assert "slate hook prompt" in hook_commands(cfg, "UserPromptSubmit")
    pre_entry = cfg["hooks"]["PreToolUse"][0]
    assert pre_entry["matcher"] == "Edit|Write"
    deny = cfg["permissions"]["deny"]
    assert "Edit(.slate/expertise/**)" in deny
    assert "Write(.slate/expertise/**)" in deny
    out = capsys.readouterr().out
    assert "slate ack --no-lessons" in out  # CLAUDE.md snippet emitted


def test_setup_preserves_user_settings_and_is_idempotent(repo):
    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "model": "opus",
                "permissions": {"deny": ["Read(secrets/**)"]},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "my-own-hook"}]}]},
            }
        ),
        encoding="utf-8",
    )
    main(["setup", "claude"])
    main(["setup", "claude"])  # idempotent re-run
    cfg = settings(repo)
    assert cfg["model"] == "opus"
    assert "Read(secrets/**)" in cfg["permissions"]["deny"]
    stop_commands = hook_commands(cfg, "Stop")
    assert stop_commands.count("slate hook stop") == 1
    assert "my-own-hook" in stop_commands
    assert hook_commands(cfg, "UserPromptSubmit").count("slate hook prompt") == 1
    assert cfg["permissions"]["deny"].count("Edit(.slate/expertise/**)") == 1


def test_setup_remove_is_surgical(repo):
    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "model": "opus",
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "my-own-hook"}]}]},
                "permissions": {"deny": ["Read(secrets/**)"]},
            }
        ),
        encoding="utf-8",
    )
    main(["setup", "claude"])
    assert main(["setup", "claude", "--remove"]) == 0
    cfg = settings(repo)
    assert cfg["model"] == "opus"
    assert hook_commands(cfg, "Stop") == ["my-own-hook"]
    assert "SessionStart" not in cfg.get("hooks", {})
    assert "UserPromptSubmit" not in cfg.get("hooks", {})
    assert cfg["permissions"]["deny"] == ["Read(secrets/**)"]
