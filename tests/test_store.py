
import pytest

from slate.output import SlateError
from slate.store import Store, find_store, require_store, to_posix


def make_store(root, kind="slate"):
    d = root / f".{kind}"
    (d / "expertise").mkdir(parents=True)
    return Store(d, kind)


# --- discovery ---


def test_find_store_walks_up_to_git_root(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".slate" / "expertise").mkdir(parents=True)
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    found = find_store(nested)
    assert found is not None
    assert found.root == tmp_path / ".slate"
    assert found.kind == "slate"


def test_find_store_prefers_slate_over_mulch(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".slate" / "expertise").mkdir(parents=True)
    (tmp_path / ".mulch" / "expertise").mkdir(parents=True)
    assert find_store(tmp_path).kind == "slate"


def test_find_store_reads_mulch_stores(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".mulch" / "expertise").mkdir(parents=True)
    found = find_store(tmp_path)
    assert found.kind == "mulch"
    assert found.root == tmp_path / ".mulch"


def test_find_store_does_not_walk_past_git_root(tmp_path):
    (tmp_path / ".slate" / "expertise").mkdir(parents=True)  # outside the repo
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert find_store(repo) is None


def test_require_store_raises_exit_5_with_init_hint(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(SlateError) as exc:
        require_store(tmp_path)
    assert exc.value.exit_code == 5
    assert exc.value.code == "no_store"
    assert "slate init" in (exc.value.retry or "")


# --- reading (tolerant) ---


def test_read_skips_blank_comment_and_malformed_lines(tmp_path):
    store = make_store(tmp_path)
    path = store.domain_path("api")
    path.write_text(
        '{"type":"convention","content":"a","classification":"tactical","recorded_at":"t"}\n'
        "\n"
        "# ARCHIVED banner style comment\n"
        "{not json}\n"
        '{"type":"ritual","weird":true}\n',
        encoding="utf-8",
    )
    records, warnings = store.read("api")
    assert [r["type"] for r in records] == ["convention", "ritual"]
    assert len(warnings) == 1
    assert "api.jsonl:4" in warnings[0]


def test_read_missing_domain_returns_empty(tmp_path):
    store = make_store(tmp_path)
    assert store.read("ghost") == ([], [])


# --- appending ---


def test_append_writes_compact_jsonl_and_assigns_id(tmp_path):
    store = make_store(tmp_path)
    rec = {"type": "convention", "content": "café ünïcode", "classification": "tactical", "recorded_at": "t"}
    store.append("api", rec)
    assert rec["id"].startswith("mx-")
    raw = store.domain_path("api").read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    assert '","' in text and '": "' not in text  # compact separators
    assert "café ünïcode" in text  # ensure_ascii=False
    records, _ = store.read("api")
    assert records[0]["content"] == "café ünïcode"


def test_append_preserves_existing_id(tmp_path):
    store = make_store(tmp_path)
    rec = {"id": "mx-aaaaaa", "type": "convention", "content": "x", "classification": "tactical", "recorded_at": "t"}
    store.append("api", rec)
    records, _ = store.read("api")
    assert records[0]["id"] == "mx-aaaaaa"


# --- rewriting ---


def test_mutate_replaces_contents_atomically(tmp_path):
    store = make_store(tmp_path)
    store.append("api", {"type": "convention", "content": "old", "classification": "tactical", "recorded_at": "t"})
    store.mutate("api", lambda _: [{"type": "convention", "content": "new", "classification": "tactical", "recorded_at": "t"}])
    records, _ = store.read("api")
    assert len(records) == 1
    assert records[0]["content"] == "new"
    assert records[0]["id"].startswith("mx-")
    leftovers = [p for p in store.domain_path("api").parent.iterdir() if ".tmp" in p.name or p.suffix == ".lock"]
    assert leftovers == []


def test_mutate_sees_current_records_and_can_empty_the_file(tmp_path):
    store = make_store(tmp_path)
    store.append("api", {"type": "convention", "content": "x", "classification": "tactical", "recorded_at": "t"})
    seen: list[list[dict]] = []

    def clear(records):
        seen.append(list(records))
        return []

    store.mutate("api", clear)
    assert len(seen[0]) == 1  # fn received the on-disk records
    assert store.domain_path("api").read_bytes() == b""


def test_mutate_returning_none_skips_the_write(tmp_path):
    store = make_store(tmp_path)
    store.append("api", {"type": "convention", "content": "x", "classification": "tactical", "recorded_at": "t"})
    before = store.domain_path("api").read_bytes()
    store.mutate("api", lambda records: None)
    assert store.domain_path("api").read_bytes() == before


# --- archive ---


def test_archive_append_writes_banner_once(tmp_path):
    store = make_store(tmp_path)
    rec = {"type": "convention", "content": "x", "classification": "observational", "recorded_at": "t", "id": "mx-ab12cd"}
    store.append_archive("api", [rec])
    store.append_archive("api", [dict(rec, id="mx-ef34ab")])
    lines = store.archive_path("api").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# ARCHIVED")
    assert sum(1 for line in lines if line.startswith("# ARCHIVED")) == 1
    records, _ = store.read_archive("api")
    assert len(records) == 2


# --- misc ---


def test_domains_sorted(tmp_path):
    store = make_store(tmp_path)
    for d in ("zeta", "alpha"):
        store.append(d, {"type": "convention", "content": d, "classification": "tactical", "recorded_at": "t"})
    assert store.domains() == ["alpha", "zeta"]


def test_to_posix_normalizes_backslashes():
    assert to_posix("src\\utils\\db.py") == "src/utils/db.py"
    assert to_posix("src/utils/db.py") == "src/utils/db.py"


def test_config_path_prefers_slate_config(tmp_path):
    store = make_store(tmp_path)
    assert store.config_path() is None
    mulch_cfg = store.root / "mulch.config.yaml"
    mulch_cfg.write_text("version: '1'\n", encoding="utf-8")
    assert store.config_path() == mulch_cfg
    slate_cfg = store.root / "slate.config.yaml"
    slate_cfg.write_text("version: '1'\n", encoding="utf-8")
    assert store.config_path() == slate_cfg
