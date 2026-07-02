import pytest

from slate import config as config_mod
from slate.output import SlateError
from slate.store import Store


def make_store(tmp_path):
    root = tmp_path / ".slate"
    (root / "expertise").mkdir(parents=True)
    return Store(root, "slate")


def test_defaults_when_no_config_file(tmp_path):
    cfg = config_mod.load(make_store(tmp_path))
    assert cfg["governance"] == {"max_entries": 100, "warn_entries": 150, "hard_limit": 200}
    assert cfg["classification_defaults"]["shelf_life"] == {"tactical": 14, "observational": 30}
    assert cfg["search"]["boost_factor"] == 0.1
    assert cfg["prime"]["budget"] == 4000
    assert cfg["prime"]["tier_weights"] == {
        "star": 100,
        "foundational": 50,
        "tactical": 20,
        "observational": 10,
    }
    assert isinstance(cfg["dedup"]["threshold"], float)
    assert cfg["enforcement"]["stop_gate"] == {"min_files": 3, "min_lines": 40}


def test_partial_user_config_deep_merges_over_defaults(tmp_path):
    store = make_store(tmp_path)
    (store.root / "slate.config.yaml").write_text(
        "governance:\n  max_entries: 50\nclassification_defaults:\n  shelf_life:\n    tactical: 7\n",
        encoding="utf-8",
    )
    cfg = config_mod.load(store)
    assert cfg["governance"]["max_entries"] == 50
    assert cfg["governance"]["hard_limit"] == 200  # default preserved
    assert cfg["classification_defaults"]["shelf_life"]["tactical"] == 7
    assert cfg["classification_defaults"]["shelf_life"]["observational"] == 30


def test_mulch_config_accepted(tmp_path):
    store = make_store(tmp_path)
    (store.root / "mulch.config.yaml").write_text("governance:\n  max_entries: 42\n", encoding="utf-8")
    assert config_mod.load(store)["governance"]["max_entries"] == 42


def test_malformed_yaml_fails_loudly_exit_2(tmp_path):
    store = make_store(tmp_path)
    (store.root / "slate.config.yaml").write_text("governance: [unclosed\n", encoding="utf-8")
    with pytest.raises(SlateError) as exc:
        config_mod.load(store)
    assert exc.value.exit_code == 2
    assert exc.value.code == "config_invalid"


def test_non_mapping_yaml_rejected(tmp_path):
    store = make_store(tmp_path)
    (store.root / "slate.config.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(SlateError):
        config_mod.load(store)
