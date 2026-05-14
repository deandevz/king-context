import asyncio
import hashlib
import json
import os
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


def test_interleave_dedupes_repeated_content_hash():
    """Boilerplate sections that repeat across pages produce duplicate
    chunks. Interleave must emit each content_hash at most once."""
    fresh = [_chunk("aaa"), _chunk("aaa"), _chunk("bbb")]
    reused = [
        EnrichedChunk(
            title="A", path="/a", url="u", content="aaa",
            keywords=["k"] * 5, use_cases=["uc1", "uc2"],
            tags=["t"], priority=5, content_hash=_hash("aaa"),
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
    assert [e.content for e in final] == ["aaa", "bbb"]


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
    assert report.lost == 0
    assert report.total_sections == 2

    rewritten = json.loads(corpus_path.read_text())
    contents = [s["content"] for s in rewritten["sections"]]
    assert contents == ["aaa", "ccc"]


def test_update_corpus_errors_when_no_source_url(tmp_path: Path):
    # _meta present (passes legacy guard) but neither source_url nor base_url.
    corpus = {
        "name": "demo",
        "version": "v1",
        "base_url": "",
        "sections": [],
        "_meta": {},
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


def test_update_corpus_refuses_to_wipe_to_empty(tmp_path: Path, monkeypatch):
    """A discover/filter blip producing 0 URLs must not overwrite the corpus."""
    corpus_path = _make_corpus(
        tmp_path,
        sections=[_section("aaa", title="A"), _section("bbb", title="B")],
    )
    original = corpus_path.read_text()

    _patch_pipeline(
        monkeypatch,
        fresh_chunks=[],  # discover/filter produced nothing
        fresh_urls=[],
        enriched_new=[],
    )

    with pytest.raises(ValueError, match="empty corpus"):
        asyncio.run(update.update_corpus(
            name="demo",
            corpus_path=corpus_path,
            config=ScraperConfig(openrouter_api_key="x"),
            yes=True,
        ))

    # Corpus on disk untouched.
    assert corpus_path.read_text() == original


def test_update_corpus_short_circuits_when_all_chunks_reused(tmp_path: Path, monkeypatch):
    """If every fresh chunk hashes to an existing section, skip enrich entirely."""
    corpus_path = _make_corpus(
        tmp_path,
        sections=[_section("aaa", title="A"), _section("bbb", title="B")],
    )
    fresh_chunks = [_chunk("aaa"), _chunk("bbb")]

    enrich_calls = {"count": 0}

    async def fake_enrich(chunks, config, work_dir):
        enrich_calls["count"] += 1
        return []

    _patch_pipeline(
        monkeypatch,
        fresh_chunks=fresh_chunks,
        fresh_urls=["https://docs.example.com/page"],
        enriched_new=[],
    )
    monkeypatch.setattr(update, "enrich_chunks", fake_enrich)

    report = asyncio.run(update.update_corpus(
        name="demo",
        corpus_path=corpus_path,
        config=ScraperConfig(openrouter_api_key="x"),
        yes=True,
    ))

    assert enrich_calls["count"] == 0
    assert report.reused == 2
    assert report.enriched == 0


def test_update_corpus_reports_lost_chunks(tmp_path: Path, monkeypatch):
    corpus_path = _make_corpus(
        tmp_path, sections=[_section("aaa", title="A")]
    )
    fresh_chunks = [_chunk("aaa"), _chunk("xxx"), _chunk("yyy")]
    # enrich returns only one of two new chunks: simulates a validation failure.
    enriched_new = [
        EnrichedChunk(
            title="X", path="/x", url="u", content="xxx",
            keywords=["k"] * 5, use_cases=["uc1", "uc2"],
            tags=["t"], priority=5, content_hash=_hash("xxx"),
        ),
    ]
    _patch_pipeline(
        monkeypatch,
        fresh_chunks=fresh_chunks,
        fresh_urls=["https://docs.example.com/page"],
        enriched_new=enriched_new,
    )

    report = asyncio.run(update.update_corpus(
        name="demo",
        corpus_path=corpus_path,
        config=ScraperConfig(openrouter_api_key="x"),
        yes=True,
    ))

    assert report.reused == 1
    assert report.enriched == 1
    assert report.lost == 1
    assert report.total_sections == 2  # aaa + xxx; yyy lost


def test_reset_work_dir_removes_stale_state(tmp_path: Path):
    work = tmp_path / "work"
    (work / "pages").mkdir(parents=True)
    (work / "pages" / "old.md").write_text("stale")
    (work / "chunks").mkdir(parents=True)
    (work / "chunks" / "old.json").write_text("[]")
    (work / "enriched").mkdir(parents=True)
    (work / "enriched" / "batch_0001.json").write_text("[]")
    (work / "manifest.json").write_text("{}")

    update._reset_work_dir(work)

    assert not (work / "pages").exists()
    assert not (work / "chunks").exists()
    assert not (work / "enriched").exists()
    assert not (work / "manifest.json").exists()


def test_reset_work_dir_is_safe_on_clean_dir(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    update._reset_work_dir(work)  # must not raise


def test_atomic_write_json_writes_complete_file(tmp_path: Path):
    target = tmp_path / "corpus.json"
    update._atomic_write_json(target, {"hello": "world"})
    assert json.loads(target.read_text()) == {"hello": "world"}
    # No leftover tempfile.
    assert not list(tmp_path.glob(".*.tmp"))
    assert not list(tmp_path.glob("*.tmp"))


def test_update_main_corpus_path_flag_bypasses_lookup(tmp_path: Path, monkeypatch):
    corpus_path = _make_corpus(tmp_path)
    fresh_chunks = [_chunk(s["content"]) for s in [_section("aaa"), _section("bbb")]]
    _patch_pipeline(
        monkeypatch,
        fresh_chunks=fresh_chunks,
        fresh_urls=["https://docs.example.com/page"],
        enriched_new=[],
    )
    monkeypatch.setattr(update, "load_config", lambda **_: ScraperConfig(openrouter_api_key="x"))
    # find_corpus must NOT be called when --corpus-path is provided.
    monkeypatch.setattr(update, "find_corpus", lambda name: (_ for _ in ()).throw(
        AssertionError("find_corpus should not be called when --corpus-path is set")
    ))

    rc = update.update_main([
        "demo", "--yes",
        "--corpus-path", str(corpus_path),
    ])
    assert rc == 0


def test_update_main_corpus_path_flag_errors_when_missing(tmp_path: Path, capsys):
    rc = update.update_main([
        "demo", "--yes",
        "--corpus-path", str(tmp_path / "nope.json"),
    ])
    assert rc == 1
    assert "does not exist" in capsys.readouterr().err


def test_update_main_provider_flag_overrides_env_and_restores(tmp_path: Path, monkeypatch):
    """Unlike cli.main's `setdefault`, --provider on `update` should WIN over
    a pre-set env DURING the run, but the prior env is restored on exit so
    a test or embedding host doesn't see the override leak across calls."""
    monkeypatch.setenv("SCRAPE_PROVIDER", "firecrawl")
    corpus_path = _make_corpus(tmp_path)

    seen = {"during": None}

    async def fake_run(*a, **k):
        seen["during"] = os.environ.get("SCRAPE_PROVIDER")
        return update.UpdateReport(
            name="demo", reused=0, enriched=0, lost=0,
            fetch_failed=0, removed_urls=[], added_urls=[],
            total_sections=0,
        )

    monkeypatch.setattr(update, "update_corpus", fake_run)
    monkeypatch.setattr(update, "find_corpus", lambda name: corpus_path)
    monkeypatch.setattr(update, "load_config", lambda **_: ScraperConfig(openrouter_api_key="x"))

    rc = update.update_main([
        "demo", "--yes",
        "--provider", "crawl4ai",
    ])
    assert rc == 0
    # During the run the flag wins over the pre-set env.
    assert seen["during"] == "crawl4ai"
    # After the run the env is restored to the pre-call value.
    assert os.environ["SCRAPE_PROVIDER"] == "firecrawl"


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


# --- safety guards introduced via #55 review ----------------------------


def test_update_corpus_refuses_legacy_corpus_without_meta(tmp_path: Path):
    """A pre-ADR-0012 corpus (no _meta block) must hard refuse instead of
    falling back to base_url and silently wiping the curated section set."""
    legacy_corpus = {
        "name": "demo",
        "version": "v1",
        "base_url": "https://docs.example.com",
        "sections": [_section("aaa", title="A")],
        # NB: no `_meta` key at all (legacy shape)
    }
    path = tmp_path / "demo.json"
    path.write_text(json.dumps(legacy_corpus))

    original = path.read_text()
    with pytest.raises(ValueError, match="legacy pre-ADR-0012"):
        asyncio.run(update.update_corpus(
            name="demo",
            corpus_path=path,
            config=ScraperConfig(openrouter_api_key="x"),
            yes=True,
        ))
    # Corpus on disk untouched.
    assert path.read_text() == original


def test_update_corpus_aborts_when_fetch_failure_ratio_exceeds_threshold(
    tmp_path: Path, monkeypatch
):
    """If more than 10% of accepted URLs fail to fetch, refuse the writeback
    so a partial pipeline run never overwrites a healthy corpus."""
    corpus_path = _make_corpus(
        tmp_path,
        sections=[_section("aaa", title="A"), _section("bbb", title="B")],
    )
    original = corpus_path.read_text()

    _patch_pipeline(
        monkeypatch,
        fresh_chunks=[_chunk("aaa")],
        fresh_urls=[
            "https://docs.example.com/page",
            "https://docs.example.com/p2",
            "https://docs.example.com/p3",
        ],
        enriched_new=[],
    )

    async def failing_fetch(urls, work_dir, config, provider, *, force_refresh=False):
        from king_context.scraper.fetch import FetchResult
        # 3 accepted, 2 failed -> 66% > 10% threshold.
        return FetchResult(total=len(urls), completed=1, failed=2, results=[])

    monkeypatch.setattr(update, "fetch_pages", failing_fetch)

    with pytest.raises(ValueError, match="fetches failed"):
        asyncio.run(update.update_corpus(
            name="demo",
            corpus_path=corpus_path,
            config=ScraperConfig(openrouter_api_key="x"),
            yes=True,
        ))
    assert corpus_path.read_text() == original


def test_update_corpus_aborts_when_discover_loses_more_than_half(
    tmp_path: Path, monkeypatch
):
    """If more than 50% of corpus URLs disappear from fresh discovery, abort
    before fetch. Growth is allowed; only loss is dangerous."""
    sections = [
        _section("a", title="A", url="https://docs.example.com/a"),
        _section("b", title="B", url="https://docs.example.com/b"),
        _section("c", title="C", url="https://docs.example.com/c"),
        _section("d", title="D", url="https://docs.example.com/d"),
    ]
    corpus_path = _make_corpus(tmp_path, sections=sections)
    original = corpus_path.read_text()

    # Only 1 of 4 corpus URLs survives -> 75% loss > 50% threshold.
    _patch_pipeline(
        monkeypatch,
        fresh_chunks=[_chunk("a")],
        fresh_urls=["https://docs.example.com/a"],
        enriched_new=[],
    )

    with pytest.raises(ValueError, match="missing from the fresh discovery"):
        asyncio.run(update.update_corpus(
            name="demo",
            corpus_path=corpus_path,
            config=ScraperConfig(openrouter_api_key="x"),
            yes=True,
        ))
    assert corpus_path.read_text() == original


def test_update_corpus_allows_discover_growth(tmp_path: Path, monkeypatch):
    """Fresh discover returning MORE URLs than the corpus is allowed."""
    sections = [_section("a", title="A", url="https://docs.example.com/a")]
    corpus_path = _make_corpus(tmp_path, sections=sections)

    fresh_urls = [
        "https://docs.example.com/a",
        "https://docs.example.com/b",
        "https://docs.example.com/c",
    ]
    _patch_pipeline(
        monkeypatch,
        fresh_chunks=[_chunk("a")],
        fresh_urls=fresh_urls,
        enriched_new=[],
    )

    # Must not raise.
    report = asyncio.run(update.update_corpus(
        name="demo",
        corpus_path=corpus_path,
        config=ScraperConfig(openrouter_api_key="x"),
        yes=True,
    ))
    assert report.reused == 1


def test_update_corpus_skips_cost_prompt_when_no_new_chunks(
    tmp_path: Path, monkeypatch
):
    """Every fresh chunk reused -> _confirm_cost must not call input() and the
    plan proceeds without a confusing '$0.0000' prompt."""
    corpus_path = _make_corpus(
        tmp_path,
        sections=[_section("aaa", title="A"), _section("bbb", title="B")],
    )

    def boom(*_a, **_k):
        raise AssertionError("input() must not be called when no new chunks")

    monkeypatch.setattr("builtins.input", boom)

    _patch_pipeline(
        monkeypatch,
        fresh_chunks=[_chunk("aaa"), _chunk("bbb")],
        fresh_urls=["https://docs.example.com/page"],
        enriched_new=[],
    )

    # yes=False would normally prompt; here it must be skipped.
    report = asyncio.run(update.update_corpus(
        name="demo",
        corpus_path=corpus_path,
        config=ScraperConfig(openrouter_api_key="x"),
        yes=False,
    ))
    assert report.reused == 2
    assert report.enriched == 0


def test_update_corpus_surfaces_fetch_failed_in_report(
    tmp_path: Path, monkeypatch
):
    """fetch_failed below threshold is recorded on the report (and the CLI
    summary prints it). 1/10 = 10% which is NOT > 10%, so it must NOT abort."""
    corpus_path = _make_corpus(
        tmp_path,
        sections=[_section("aaa", title="A")],
    )
    # Include the corpus section URL so the divergence guard does not fire.
    fresh_urls = ["https://docs.example.com/page"] + [
        f"https://docs.example.com/p{i}" for i in range(9)
    ]
    _patch_pipeline(
        monkeypatch,
        fresh_chunks=[_chunk("aaa")],
        fresh_urls=fresh_urls,
        enriched_new=[],
    )

    async def partial_fetch(urls, work_dir, config, provider, *, force_refresh=False):
        from king_context.scraper.fetch import FetchResult
        return FetchResult(total=len(urls), completed=9, failed=1, results=[])

    monkeypatch.setattr(update, "fetch_pages", partial_fetch)

    report = asyncio.run(update.update_corpus(
        name="demo",
        corpus_path=corpus_path,
        config=ScraperConfig(openrouter_api_key="x"),
        yes=True,
    ))
    assert report.fetch_failed == 1


# --- subcommand --no-fetch-cache plumb ----------------------------------


def test_update_main_no_fetch_cache_sets_env(tmp_path: Path, monkeypatch):
    """--no-fetch-cache on `king-scrape update` must set SCRAPE_CACHE_MODE
    for the duration of the run and restore the prior state on exit."""
    monkeypatch.delenv("SCRAPE_CACHE_MODE", raising=False)
    corpus_path = _make_corpus(tmp_path)

    seen = {"during": None}

    async def fake_run(*a, **k):
        seen["during"] = os.environ.get("SCRAPE_CACHE_MODE")
        return update.UpdateReport(
            name="demo", reused=0, enriched=0, lost=0,
            fetch_failed=0, removed_urls=[], added_urls=[],
            total_sections=0,
        )

    monkeypatch.setattr(update, "update_corpus", fake_run)
    monkeypatch.setattr(update, "find_corpus", lambda name: corpus_path)
    monkeypatch.setattr(update, "load_config", lambda **_: ScraperConfig(openrouter_api_key="x"))

    rc = update.update_main(["demo", "--yes", "--no-fetch-cache"])
    assert rc == 0
    assert seen["during"] == "bypass"
    # Restored after the run.
    assert "SCRAPE_CACHE_MODE" not in os.environ


def test_update_main_no_fetch_cache_respects_prior_env(tmp_path: Path, monkeypatch):
    """An explicit pre-existing env value wins via setdefault semantics, and is
    restored verbatim on exit."""
    monkeypatch.setenv("SCRAPE_CACHE_MODE", "read_only")
    corpus_path = _make_corpus(tmp_path)

    seen = {"during": None}

    async def fake_run(*a, **k):
        seen["during"] = os.environ.get("SCRAPE_CACHE_MODE")
        return update.UpdateReport(
            name="demo", reused=0, enriched=0, lost=0,
            fetch_failed=0, removed_urls=[], added_urls=[],
            total_sections=0,
        )

    monkeypatch.setattr(update, "update_corpus", fake_run)
    monkeypatch.setattr(update, "find_corpus", lambda name: corpus_path)
    monkeypatch.setattr(update, "load_config", lambda **_: ScraperConfig(openrouter_api_key="x"))

    rc = update.update_main(["demo", "--yes", "--no-fetch-cache"])
    assert rc == 0
    # setdefault means the explicit prior wins.
    assert seen["during"] == "read_only"
    assert os.environ["SCRAPE_CACHE_MODE"] == "read_only"


# --- anchored-empty-corpus coverage ------------------------------------


def test_update_corpus_handles_anchored_empty_corpus(tmp_path: Path, monkeypatch):
    """A corpus with _meta (anchored, not legacy) but zero sections must
    refresh against fresh discovery without raising. Every fresh chunk is
    treated as new; corpus_canon_urls is empty so the divergence guard
    skips; the empty-corpus refusal also skips because fresh_chunks > 0."""
    corpus = {
        "name": "demo",
        "display_name": "Demo",
        "version": "v1",
        "base_url": "https://docs.example.com",
        "sections": [],
        "_meta": {"source_url": "https://docs.example.com"},
    }
    corpus_path = tmp_path / "demo.json"
    corpus_path.write_text(json.dumps(corpus))

    fresh_chunks = [_chunk("aaa"), _chunk("bbb")]
    enriched_new = [
        EnrichedChunk(
            title=c, path=f"/{c}", url="u", content=c,
            keywords=["k"] * 5, use_cases=["uc1", "uc2"],
            tags=["t"], priority=5, content_hash=_hash(c),
        )
        for c in ("aaa", "bbb")
    ]
    _patch_pipeline(
        monkeypatch,
        fresh_chunks=fresh_chunks,
        fresh_urls=["https://docs.example.com/a", "https://docs.example.com/b"],
        enriched_new=enriched_new,
    )

    report = asyncio.run(update.update_corpus(
        name="demo",
        corpus_path=corpus_path,
        config=ScraperConfig(openrouter_api_key="x"),
        yes=True,
    ))
    assert report.reused == 0
    assert report.enriched == 2
    assert report.total_sections == 2


# --- _cache_mode helper direct tests -----------------------------------


def test_cache_mode_helpers_set_and_restore_when_env_was_unset(monkeypatch):
    from king_context.scraper import _cache_mode

    monkeypatch.delenv("SCRAPE_CACHE_MODE", raising=False)

    class _Args:
        no_fetch_cache = True

    was_set, prior = _cache_mode.apply_cache_mode_flag(_Args())
    assert was_set is False
    assert prior is None
    assert os.environ["SCRAPE_CACHE_MODE"] == "bypass"

    _cache_mode.restore_cache_mode(was_set, prior)
    assert "SCRAPE_CACHE_MODE" not in os.environ


def test_cache_mode_helpers_preserve_pre_existing_value(monkeypatch):
    from king_context.scraper import _cache_mode

    monkeypatch.setenv("SCRAPE_CACHE_MODE", "read_only")

    class _Args:
        no_fetch_cache = True

    was_set, prior = _cache_mode.apply_cache_mode_flag(_Args())
    assert was_set is True
    assert prior == "read_only"
    # setdefault: explicit prior wins.
    assert os.environ["SCRAPE_CACHE_MODE"] == "read_only"

    _cache_mode.restore_cache_mode(was_set, prior)
    assert os.environ["SCRAPE_CACHE_MODE"] == "read_only"


def test_cache_mode_helpers_no_op_when_flag_not_passed(monkeypatch):
    from king_context.scraper import _cache_mode

    monkeypatch.delenv("SCRAPE_CACHE_MODE", raising=False)

    class _Args:
        no_fetch_cache = False

    was_set, prior = _cache_mode.apply_cache_mode_flag(_Args())
    assert was_set is False
    assert prior is None
    assert "SCRAPE_CACHE_MODE" not in os.environ

    _cache_mode.restore_cache_mode(was_set, prior)
    assert "SCRAPE_CACHE_MODE" not in os.environ


def test_cache_mode_restore_raises_when_invariant_violated():
    """Defensive: prior=None with was_set=True is impossible from
    apply_cache_mode_flag's contract; raise rather than write `None` into
    os.environ (which would TypeError downstream)."""
    from king_context.scraper import _cache_mode

    with pytest.raises(RuntimeError, match="apply_cache_mode_flag"):
        _cache_mode.restore_cache_mode(was_set=True, prior=None)
