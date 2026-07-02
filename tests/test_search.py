from slate.search import extract_text, search_records, tokenize


def conv(content, **kw):
    rec = {"type": "convention", "content": content, "classification": "tactical", "recorded_at": "t"}
    rec.update(kw)
    return rec


# --- tokenizer parity with mulch (JS \w is ASCII) ---


def test_tokenize_lowercases_and_strips_punctuation():
    assert tokenize("Hello, World! (v2)") == ["hello", "world", "v2"]


def test_tokenize_keeps_hyphens_inside_words():
    assert tokenize("dir-anchor matching") == ["dir-anchor", "matching"]


def test_tokenize_is_ascii_like_js():
    assert tokenize("café") == ["caf"]


def test_tokenize_underscores_kept():
    assert tokenize("snake_case_name") == ["snake_case_name"]


# --- text extraction ---


def test_extract_text_covers_type_fields_and_tags():
    rec = {
        "type": "pattern",
        "name": "atomic writes",
        "description": "temp file plus replace",
        "files": ["src/store.py"],
        "tags": ["io", "windows"],
    }
    text = extract_text(rec)
    for fragment in ("atomic writes", "temp file plus replace", "src/store.py", "io", "windows"):
        assert fragment in text


def test_extract_text_unknown_type_uses_string_fields():
    text = extract_text({"type": "ritual", "incantation": "abra kadabra", "power": 9})
    assert "abra kadabra" in text


# --- ranking ---


def test_matching_doc_ranks_first_and_zero_scores_excluded():
    records = [
        conv("always run pytest before committing"),
        conv("use uv for dependency management"),
        conv("prefer pathlib over os.path"),
    ]
    results = search_records(records, "pytest committing")
    assert len(results) == 1
    assert results[0][0]["content"] == "always run pytest before committing"
    assert results[0][1] > 0


def test_term_frequency_influences_rank():
    records = [
        conv("locks and more locks: locks everywhere"),
        conv("a single mention of locks in passing here"),
    ]
    results = search_records(records, "locks")
    assert results[0][0]["content"].startswith("locks and more")


def test_empty_query_or_corpus_returns_empty():
    assert search_records([], "query") == []
    assert search_records([conv("x")], "   ") == []


def test_confirmation_boost_reorders():
    twice_confirmed = conv(
        "release process notes",
        outcomes=[{"status": "success"}, {"status": "success"}, {"status": "success"}],
    )
    plain = conv("release process notes and extra words diluting")
    base = search_records([plain, twice_confirmed], "release process", boost_factor=0.0)
    boosted = search_records([plain, twice_confirmed], "release process", boost_factor=5.0)
    assert boosted[0][0] is twice_confirmed
    assert base[0][1] >= base[1][1]
