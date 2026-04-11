"""Tests for PersonalContextStore."""

from __future__ import annotations

import time

import pytest
import yaml

from onlime.personal_context.store import Fact, PersonalContextStore


def _write_yaml(path, facts=None, aliases=None):
    data = {"version": 1, "facts": facts or [], "aliases": aliases or {}}
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Load valid YAML
# ---------------------------------------------------------------------------

def test_load_valid_yaml(tmp_path):
    f = tmp_path / "ctx.yaml"
    _write_yaml(f, facts=[
        {"key": "a", "value": "alpha", "category": "preference"},
        {"key": "b", "value": "beta", "category": "project"},
        {"key": "c", "value": "gamma", "category": "ontology"},
    ])
    store = PersonalContextStore(f)
    store.load()
    assert len(store.list_facts()) == 3


# ---------------------------------------------------------------------------
# 2. Load missing file
# ---------------------------------------------------------------------------

def test_load_missing_file(tmp_path):
    store = PersonalContextStore(tmp_path / "nonexistent.yaml")
    store.load()  # must not raise
    assert store.list_facts() == []


# ---------------------------------------------------------------------------
# 3. Malformed YAML falls back to previous state
# ---------------------------------------------------------------------------

def test_load_malformed_yaml_falls_back(tmp_path):
    f = tmp_path / "ctx.yaml"
    _write_yaml(f, facts=[{"key": "x", "value": "val", "category": "preference"}])
    store = PersonalContextStore(f)
    store.load()
    assert len(store.list_facts()) == 1

    # Corrupt the file
    f.write_text(": invalid: [yaml: {{{{", encoding="utf-8")
    store.load()
    # Previous state retained
    assert len(store.list_facts()) == 1
    assert store.list_facts()[0].key == "x"


# ---------------------------------------------------------------------------
# 4. mtime-based reload
# ---------------------------------------------------------------------------

def test_mtime_reload(tmp_path):
    f = tmp_path / "ctx.yaml"
    _write_yaml(f, facts=[{"key": "old", "value": "v1", "category": "preference"}])
    store = PersonalContextStore(f)
    store.load()
    assert len(store.list_facts()) == 1

    # Wait briefly then write new content so mtime advances
    time.sleep(0.05)
    _write_yaml(f, facts=[
        {"key": "old", "value": "v1", "category": "preference"},
        {"key": "new", "value": "v2", "category": "project"},
    ])

    reloaded = store.reload_if_changed()
    assert reloaded is True
    assert len(store.list_facts()) == 2


# ---------------------------------------------------------------------------
# 5. add_fact persists to disk
# ---------------------------------------------------------------------------

def test_add_fact_persists(tmp_path):
    f = tmp_path / "ctx.yaml"
    _write_yaml(f)
    store = PersonalContextStore(f)
    store.load()

    store.add_fact(Fact(key="p1", value="hello", category="preference"))

    store2 = PersonalContextStore(f)
    store2.load()
    keys = [fa.key for fa in store2.list_facts()]
    assert "p1" in keys


# ---------------------------------------------------------------------------
# 6. remove_fact
# ---------------------------------------------------------------------------

def test_remove_fact(tmp_path):
    f = tmp_path / "ctx.yaml"
    _write_yaml(f, facts=[{"key": "r1", "value": "v", "category": "project"}])
    store = PersonalContextStore(f)
    store.load()

    assert store.remove_fact("r1") is True
    assert store.remove_fact("r1") is False  # already gone
    assert store.list_facts() == []


# ---------------------------------------------------------------------------
# 7. list_facts category filter
# ---------------------------------------------------------------------------

def test_list_facts_category_filter(tmp_path):
    f = tmp_path / "ctx.yaml"
    _write_yaml(f, facts=[
        {"key": "a", "value": "1", "category": "preference"},
        {"key": "b", "value": "2", "category": "project"},
        {"key": "c", "value": "3", "category": "preference"},
    ])
    store = PersonalContextStore(f)
    store.load()

    prefs = store.list_facts(category="preference")
    assert len(prefs) == 2
    projects = store.list_facts(category="project")
    assert len(projects) == 1


# ---------------------------------------------------------------------------
# 8. list_facts excludes internal when include_internal=False
# ---------------------------------------------------------------------------

def test_list_facts_excludes_internal(tmp_path):
    f = tmp_path / "ctx.yaml"
    _write_yaml(f, facts=[
        {"key": "pub1", "value": "v1", "category": "preference", "visibility": "public"},
        {"key": "pub2", "value": "v2", "category": "project", "visibility": "public"},
        {"key": "priv", "value": "v3", "category": "relationship", "visibility": "internal"},
    ])
    store = PersonalContextStore(f)
    store.load()

    public_only = store.list_facts(include_internal=False)
    assert len(public_only) == 2
    all_facts = store.list_facts(include_internal=True)
    assert len(all_facts) == 3


# ---------------------------------------------------------------------------
# 9. resolve_alias hit and miss
# ---------------------------------------------------------------------------

def test_resolve_alias_hit_and_miss(tmp_path):
    f = tmp_path / "ctx.yaml"
    _write_yaml(f, aliases={"혀나": "송현아", "동인": "최동인"})
    store = PersonalContextStore(f)
    store.load()

    assert store.resolve_alias("혀나") == "송현아"
    assert store.resolve_alias("동인") == "최동인"
    assert store.resolve_alias("unknown") == "unknown"


# ---------------------------------------------------------------------------
# 10. build_system_suffix priority ordering
# ---------------------------------------------------------------------------

def test_build_system_suffix_priority_ordering(tmp_path):
    f = tmp_path / "ctx.yaml"
    _write_yaml(f, facts=[
        {"key": "low", "value": "low-val", "category": "preference", "priority": 10},
        {"key": "high", "value": "high-val", "category": "preference", "priority": 100},
        {"key": "mid", "value": "mid-val", "category": "preference", "priority": 50},
    ])
    store = PersonalContextStore(f)
    store.load()

    suffix = store.build_system_suffix(max_tokens=500)
    assert suffix != ""
    high_pos = suffix.index("high-val")
    mid_pos = suffix.index("mid-val")
    low_pos = suffix.index("low-val")
    assert high_pos < mid_pos < low_pos


# ---------------------------------------------------------------------------
# 11. build_system_suffix token budget drops low-priority
# ---------------------------------------------------------------------------

def test_build_system_suffix_token_budget_drops_low_priority(tmp_path):
    f = tmp_path / "ctx.yaml"
    # 5 facts; each value is ~10 chars. Budget of 5 tokens = 15 chars.
    # Header is ~14 chars ("\n\n[개인 맥락]\n"). Only highest priority fits.
    facts = [
        {"key": f"k{i}", "value": f"value-item-{i:02d}", "category": "preference", "priority": i * 10}
        for i in range(1, 6)
    ]
    _write_yaml(f, facts=facts)
    store = PersonalContextStore(f)
    store.load()

    # Very tight budget: only room for 1-2 lines
    suffix = store.build_system_suffix(max_tokens=10)
    # Should contain highest-priority (priority=50) but not lowest (priority=10)
    assert "value-item-05" in suffix  # highest priority (50)
    assert "value-item-01" not in suffix  # lowest priority (10)


# ---------------------------------------------------------------------------
# 12. build_system_suffix empty returns empty string
# ---------------------------------------------------------------------------

def test_build_system_suffix_empty_returns_empty_string(tmp_path):
    store = PersonalContextStore(tmp_path / "nonexistent.yaml")
    store.load()
    assert store.build_system_suffix(max_tokens=200) == ""


# ---------------------------------------------------------------------------
# 13. atomic persist — no tmp file lingers
# ---------------------------------------------------------------------------

def test_atomic_persist_no_partial_write(tmp_path):
    f = tmp_path / "ctx.yaml"
    _write_yaml(f)
    store = PersonalContextStore(f)
    store.load()

    store.add_fact(Fact(key="at1", value="atomic-val", category="preference"))

    # tmp file must not exist after persist
    tmp_file = f.with_suffix(".yaml.tmp")
    assert not tmp_file.exists()

    # Final file is valid YAML containing the fact
    raw = f.read_text(encoding="utf-8")
    loaded = yaml.safe_load(raw)
    keys = [item["key"] for item in loaded.get("facts", [])]
    assert "at1" in keys
