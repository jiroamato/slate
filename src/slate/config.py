"""Config loading: slate.config.yaml preferred, mulch.config.yaml accepted.

Defaults are mulch 0.10.7 parity plus slate's dedup/enforcement knobs.
Config errors fail loudly with exit 2 — no silent defaults (except in hook
context, where the fail-open wrapper wins). PyYAML import stays inside
load() so the hook fast path never pays for it.
"""

from __future__ import annotations

import copy
from typing import Any

from slate.output import EXIT_USAGE, SlateError
from slate.store import Store

# dedup.threshold is a normalized similarity in [0, 1]: the top BM25 score of
# any existing record divided by the candidate's own self-score, which keeps
# the gate stable across corpus sizes (raw BM25 collapses on tiny domains).
# Shipped default tuned against the golden-store fixture
# (tests/test_record.py::test_default_threshold_separates_near_dup_from_related).
DEFAULT_DEDUP_THRESHOLD = 0.6

DEFAULTS: dict[str, Any] = {
    "version": "1",
    "schema_version": 1,
    "domains": {},
    "governance": {"max_entries": 100, "warn_entries": 150, "hard_limit": 200},
    "classification_defaults": {"shelf_life": {"tactical": 14, "observational": 30}},
    "prime": {
        "budget": 4000,
        "tier_weights": {"star": 100, "foundational": 50, "tactical": 20, "observational": 10},
    },
    "search": {"boost_factor": 0.1},
    "dedup": {"threshold": DEFAULT_DEDUP_THRESHOLD},
    "enforcement": {"stop_gate": {"min_files": 3, "min_lines": 40}},
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load(store: Store) -> dict:
    """Load the store's config with defaults deep-merged underneath."""
    defaults = copy.deepcopy(DEFAULTS)
    path = store.config_path()
    if path is None:
        return defaults

    import yaml  # deferred: hook fast path must not import PyYAML

    try:
        with open(path, encoding="utf-8") as fh:
            user = yaml.safe_load(fh)
    except yaml.YAMLError as err:
        raise SlateError(
            f"invalid YAML in {path.name}: {err}",
            code="config_invalid",
            exit_code=EXIT_USAGE,
            hint="fix the syntax error or delete the file to fall back to defaults",
        ) from err

    if user is None:
        return defaults
    if not isinstance(user, dict):
        raise SlateError(
            f"{path.name} must be a YAML mapping, got {type(user).__name__}",
            code="config_invalid",
            exit_code=EXIT_USAGE,
        )
    return _deep_merge(defaults, user)
