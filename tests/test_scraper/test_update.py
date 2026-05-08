import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from king_context.scraper import update
from king_context.scraper.chunk import Chunk
from king_context.scraper.config import ScraperConfig
from king_context.scraper.enrich import EnrichedChunk


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _section(content: str, **overrides) -> dict:
    base = {
        "title": "T",
        "path": "/p",
        "url": "https://docs.example.com/page",
        "keywords": ["k1", "k2", "k3", "k4", "k5"],
        "use_cases": ["Use when X", "Configure when Y"],
        "tags": ["api"],
        "priority": 8,
        "content": content,
        "_meta": {"content_hash": _hash(content)},
    }
    base.update(overrides)
    return base


def _make_corpus(tmp_path: Path, sections=None, source_url=None) -> Path:
    corpus = {
        "name": "demo",
        "display_name": "Demo",
        "version": "v1",
        "base_url": "https://docs.example.com",
        "sections": sections if sections is not None else [
            _section("aaa", title="A"),
            _section("bbb", title="B"),
        ],
        "_meta": {"source_url": source_url or "https://docs.example.com"},
    }
    path = tmp_path / "demo.json"
    path.write_text(json.dumps(corpus))
    return path


def _chunk(content: str, **overrides) -> Chunk:
    base = dict(
        title="T",
        breadcrumb="T",
        content=content,
        source_url="https://docs.example.com/page",
        path="/page/t",
        token_count=10,
    )
    base.update(overrides)
    return Chunk(**base)


# --- pure unit logic ------------------------------------------------------


def test_section_hash_uses_meta_when_present():
    assert update._section_hash(_section("foo")) == _hash("foo")


def test_section_hash_falls_back_to_content_when_meta_missing():
    legacy = {"content": "legacy", "keywords": [], "use_cases": [], "tags": [], "priority": 1}
    assert update._section_hash(legacy) == _hash("legacy")


def test_resolve_source_url_prefers_meta():
    corpus = {
        "base_url": "https://docs.example.com",
        "_meta": {"source_url": "https://docs.example.com/v2"},
    }
    assert update._resolve_source_url(corpus) == "https://docs.example.com/v2"


def test_resolve_source_url_falls_back_to_base_url():
    corpus = {"base_url": "https://docs.example.com"}
    assert update._resolve_source_url(corpus) == "https://docs.example.com"


def test_build_reuse_index():
    corpus = {"sections": [_section("aaa"), _section("bbb")]}
    index = update._build_reuse_index(corpus)
    assert _hash("aaa") in index
    assert _hash("bbb") in index
    assert index[_hash("aaa")]["keywords"] == ["k1", "k2", "k3", "k4", "k5"]


def test_plan_update_classifies_chunks():
    corpus = {"sections": [_section("aaa"), _section("bbb")]}
    reuse = update._build_reuse_index(corpus)
    fresh = [_chunk("aaa"), _chunk("ccc")]  # one reused, one new
    plan = update._plan_update(
        fresh,
        ["https://docs.example.com/page"],
        reuse,
        corpus,
    )
    assert [c.content for c in plan.reused_chunks] == ["aaa"]
    assert [c.content for c in plan.new_chunks] == ["ccc"]


def test_plan_added_and_removed_urls():
    corpus = {
        "sections": [
            _section("a", url="https://x/old"),
            _section("b", url="https://x/keep"),
        ],
    }
    fresh_urls = ["https://x/keep", "https://x/new"]
    plan = update._plan_update([], fresh_urls, {}, corpus)
    assert plan.added_urls == ["https://x/new"]
    assert plan.removed_urls == ["https://x/old"]


def test_materialise_reused_carries_enrichment_but_takes_fresh_identity():
    """Reused chunks adopt fresh title/path/url, keep enrichment values."""
    corpus = {"sections": [_section("aaa", title="OLD", path="/old/path")]}
    reuse = update._build_reuse_index(corpus)
    fresh = [_chunk("aaa", title="NEW", path="/new/path",
                    source_url="https://docs.example.com/new")]
    materialised = update._materialise_reused(fresh, reuse)
    assert len(materialised) == 1
    e = materialised[0]
    assert e.title == "NEW"  # fresh identity
    assert e.path == "/new/path"
    assert e.url == "https://docs.example.com/new"
    assert e.keywords == ["k1", "k2", "k3", "k4", "k5"]  # carried forward
    assert e.priority == 8


def test_interleave_in_chunk_order_preserves_fresh_order():
    fresh = [_chunk("aaa"), _chunk("bbb"), _chunk("ccc")]
    reused = [
        EnrichedChunk(
            title="A", path="/a", url="u", content="aaa",
            keywords=["k"] * 5, use_cases=["uc1", "uc2"],
            tags=["t"], priority=5, content_hash=_hash("aaa"),
        ),
        EnrichedChunk(
            title="C", path="/c", url="u", content="ccc",
            keywords=["k"] * 5, use_cases=["uc1", "uc2"],
            tags=["t"], priority=5, content_hash=_hash("ccc"),
        ),
    ]
    enriched = [
        EnrichedChunk(
            title="B", path="/b", url="u", content="bbb",
            keywords=["k"] * 5, use_cases=["uc1", "uc2"],
            tags=["t"], priority=5, content_hash=_hash("bbb"),
        ),
    ]
    final = update._interleave_in_chunk_order(fresh, reused, enriched)
    assert [e.content for e in final] == ["aaa", "bbb", "ccc"]


# --- find_corpus + load_corpus -------------------------------------------


def test_find_corpus_raises_when_missing():
    with pytest.raises(FileNotFoundError):
        update.find_corpus("does-not-exist-anywhere")


def test_load_corpus_raises_on_bad_json(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid")
    with pytest.raises(ValueError, match="not valid JSON"):
        update._load_corpus(bad)


# --- update_corpus end to end (with mocked pipeline) ---------------------


def _patch_pipeline(monkeypatch, *, fresh_chunks, fresh_urls, enriched_new):
    """Replace every network or LLM call in update_corpus with stubs."""

    async def fake_discover(base_url, config, provider):
        from king_context.scraper.discover import DiscoveryResult
        return DiscoveryResult(
            base_url=base_url,
            discovered_at="2026-05-08T00:00:00+00:00",
            total_urls=len(fresh_urls),
            urls=list(fresh_urls),
        )

    def fake_filter(urls, base_url, config):
        from king_context.scraper.filter import FilterResult
        return FilterResult(
            accepted=list(urls),
            rejected=[],
            maybe=[],
            filter_method="heuristic",
            llm_fallback_used=False,
        )

    async def fake_fetch(urls, work_dir, config, provider, *, force_refresh=False):
        from king_context.scraper.fetch import FetchResult
        return FetchResult(total=len(urls), completed=len(urls), failed=0, results=[])

    def fake_chunk(pages_dir, work_dir, config):
        return list(fresh_chunks)

    async def fake_enrich(chunks, config, work_dir):
        return list(enriched_new)

    monkeypatch.setattr(update, "discover_urls", fake_discover)
    monkeypatch.setattr(update, "filter_urls", fake_filter)
    monkeypatch.setattr(update, "fetch_pages", fake_fetch)
    monkeypatch.setattr(update, "chunk_pages", fake_chunk)
    monkeypatch.setattr(update, "enrich_chunks", fake_enrich)
    # Skip provider resolution entirely.
    monkeypatch.setattr(update, "get_discovery_provider", lambda *a, **k: object())
    monkeypatch.setattr(update, "get_fetch_provider", lambda *a, **k: object())
    monkeypatch.setattr(update, "resolve_provider_name", lambda *a, **k: "firecrawl")


def test_update_corpus_reuses_unchanged_and_enriches_new(tmp_path: Path, monkeypatch):
    corpus_path = _make_corpus(
        tmp_path,
        sections=[
            _section("aaa", title="A"),
            _section("bbb", title="B"),
        ],
    )
    fresh_chunks = [_chunk("aaa"), _chunk("ccc")]  # bbb removed, ccc new
    enriched_new = [
        EnrichedChunk(
            title="C", path="/c", url="u", content="ccc",
            keywords=["k"] * 5, use_cases=["uc1", "uc2"],
            tags=["t"], priority=5, content_hash=_hash("ccc"),
        ),
    ]
    _patch_pipeline(
        monkeypatch,
        fresh_chunks=fresh_chunks,
        fresh_urls=["https://docs.example.com/page"],
        enriched_new=enriched_new,
    )

    config = ScraperConfig(openrouter_api_key="test")
    report = asyncio.run(update.update_corpus(
        name="demo",
        corpus_path=corpus_path,
        config=config,
        yes=True,
    ))

    assert report.reused == 1
    assert report.enriched == 1
    assert report.total_sections == 2

    rewritten = json.loads(corpus_path.read_text())
    contents = [s["content"] for s in rewritten["sections"]]
    assert contents == ["aaa", "ccc"]


def test_update_corpus_errors_when_no_source_url(tmp_path: Path):
    corpus = {
        "name": "demo",
        "version": "v1",
        "base_url": "",
        "sections": [],
    }
    path = tmp_path / "demo.json"
    path.write_text(json.dumps(corpus))

    with pytest.raises(ValueError, match="source_url"):
        asyncio.run(update.update_corpus(
            name="demo",
            corpus_path=path,
            config=ScraperConfig(openrouter_api_key="x"),
            yes=True,
        ))


def test_update_main_returns_1_when_corpus_missing(capsys):
    rc = update.update_main(["does-not-exist", "--yes"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err.lower()


def test_update_main_exit_code_on_user_abort(tmp_path: Path, monkeypatch):
    corpus_path = _make_corpus(tmp_path)
    monkeypatch.setattr("builtins.input", lambda *_: "n")

    fresh_chunks = [_chunk("zzz")]  # forces an enrichment prompt
    _patch_pipeline(
        monkeypatch,
        fresh_chunks=fresh_chunks,
        fresh_urls=["https://docs.example.com/page"],
        enriched_new=[],
    )
    monkeypatch.setattr(update, "find_corpus", lambda name: corpus_path)
    monkeypatch.setattr(update, "load_config", lambda **_: ScraperConfig(openrouter_api_key="x"))

    rc = update.update_main(["demo"])
    assert rc == 1
