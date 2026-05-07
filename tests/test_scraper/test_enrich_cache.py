import json
from pathlib import Path

from king_context.scraper import enrich_cache


SAMPLE_ENRICHMENT = {
    "keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"],
    "use_cases": ["Use when X", "Configure when Y"],
    "tags": ["testing"],
    "priority": 7,
}


def test_make_key_is_deterministic():
    a = enrich_cache.make_key("hello", "model-1", "1")
    b = enrich_cache.make_key("hello", "model-1", "1")
    assert a == b
    assert len(a) == 64


def test_make_key_changes_with_content():
    a = enrich_cache.make_key("hello", "model-1", "1")
    b = enrich_cache.make_key("hello world", "model-1", "1")
    assert a != b


def test_make_key_changes_with_model():
    a = enrich_cache.make_key("same", "model-1", "1")
    b = enrich_cache.make_key("same", "model-2", "1")
    assert a != b


def test_make_key_changes_with_prompt_version():
    a = enrich_cache.make_key("same", "model-1", "1")
    b = enrich_cache.make_key("same", "model-1", "2")
    assert a != b


def test_get_returns_none_on_missing(tmp_path: Path):
    assert enrich_cache.get("deadbeef", cache_dir=tmp_path) is None


def test_get_returns_none_on_corrupt_json(tmp_path: Path):
    (tmp_path / "abc.json").write_text("{not valid json")
    assert enrich_cache.get("abc", cache_dir=tmp_path) is None


def test_put_then_get_roundtrip(tmp_path: Path):
    enrich_cache.put("abc", SAMPLE_ENRICHMENT, cache_dir=tmp_path)
    got = enrich_cache.get("abc", cache_dir=tmp_path)
    assert got == SAMPLE_ENRICHMENT


def test_put_creates_cache_dir(tmp_path: Path):
    cache_dir = tmp_path / "deeply" / "nested" / "cache"
    enrich_cache.put("abc", SAMPLE_ENRICHMENT, cache_dir=cache_dir)
    assert (cache_dir / "abc.json").exists()


def test_put_atomic_no_partial_files(tmp_path: Path):
    enrich_cache.put("abc", SAMPLE_ENRICHMENT, cache_dir=tmp_path)
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))
    final = list(tmp_path.glob("*.json"))
    assert len(final) == 1
    assert final[0].name == "abc.json"


def test_put_does_not_leak_tmp_on_non_serializable(tmp_path: Path):
    bad_value = {"keywords": {1, 2, 3}}
    enrich_cache.put("abc", bad_value, cache_dir=tmp_path)
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))
    assert not list(tmp_path.glob("*.json"))


def test_put_overwrites_existing(tmp_path: Path):
    enrich_cache.put("abc", SAMPLE_ENRICHMENT, cache_dir=tmp_path)
    new_value = {**SAMPLE_ENRICHMENT, "priority": 1}
    enrich_cache.put("abc", new_value, cache_dir=tmp_path)
    assert enrich_cache.get("abc", cache_dir=tmp_path) == new_value


def test_put_does_not_raise_on_io_error(tmp_path: Path):
    target_file = tmp_path / "blocker"
    target_file.write_text("not a directory")
    enrich_cache.put("abc", SAMPLE_ENRICHMENT, cache_dir=target_file)
