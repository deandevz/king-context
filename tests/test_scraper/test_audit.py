import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from king_context.scraper import audit


def _make_corpus(tmp_path: Path, sections: list[dict] | None = None) -> Path:
    corpus = {
        "name": "demo",
        "display_name": "Demo",
        "version": "v1",
        "base_url": "https://docs.example.com",
        "sections": sections
        if sections is not None
        else [
            {"title": "First", "url": "https://docs.example.com/a"},
            {"title": "Second", "url": "https://docs.example.com/b"},
            {"title": "Third", "url": "https://docs.example.com/c"},
        ],
    }
    path = tmp_path / "demo.json"
    path.write_text(json.dumps(corpus))
    return path


def _make_handler(by_url: dict[str, httpx.Response]):
    def handler(request: httpx.Request) -> httpx.Response:
        response = by_url.get(str(request.url))
        if response is None:
            return httpx.Response(500)
        return response
    return handler


def test_unique_section_urls_dedupes_preserving_order():
    corpus = {
        "sections": [
            {"url": "https://x/a", "title": "A"},
            {"url": "https://x/b", "title": "B"},
            {"url": "https://x/a", "title": "A again"},  # duplicate
            {"title": "no-url"},  # skipped
        ]
    }
    out = audit._unique_section_urls(corpus)
    assert out == [("https://x/a", "A"), ("https://x/b", "B")]


def test_unique_section_urls_dedupes_fragments_and_slashes():
    corpus = {
        "sections": [
            {"url": "https://docs.example.com/page", "title": "Page"},
            {"url": "https://docs.example.com/page/", "title": "Trailing slash"},
            {"url": "https://docs.example.com/page#install", "title": "Fragment"},
            {"url": "https://DOCS.EXAMPLE.COM/page", "title": "Caps"},
            {"url": "https://docs.example.com/other", "title": "Other"},
        ]
    }
    out = audit._unique_section_urls(corpus)
    urls = [u for u, _ in out]
    assert urls == ["https://docs.example.com/page", "https://docs.example.com/other"]


def test_canonicalize_strips_fragment_and_normalises_path():
    assert audit._canonicalize("https://x/A?q=1#frag") == "https://x/A?q=1"
    assert audit._canonicalize("https://x/a/") == "https://x/a"
    assert audit._canonicalize("HTTPS://X.COM/A") == "https://x.com/A"
    assert audit._canonicalize("https://x.com/") == "https://x.com/"


def test_diff_urls():
    new, orphan = audit._diff_urls(
        ["https://x/a", "https://x/b", "https://x/c"],
        ["https://x/b", "https://x/c", "https://x/d"],
    )
    assert new == ["https://x/d"]
    assert orphan == ["https://x/a"]


def test_diff_urls_canonicalizes_before_comparing():
    new, orphan = audit._diff_urls(
        ["https://x/a", "https://x/b/"],
        ["https://x/b#anchor", "https://x/c"],
    )
    # /b/ in corpus matches /b#anchor in fresh -> not new, not orphan
    # /a only in corpus -> orphan; /c only in fresh -> new
    assert new == ["https://x/c"]
    assert orphan == ["https://x/a"]


def test_audit_corpus_marks_status_per_url(tmp_path: Path):
    corpus_path = _make_corpus(tmp_path)
    by_url = {
        "https://docs.example.com/a": httpx.Response(200),
        "https://docs.example.com/b": httpx.Response(
            301, headers={"location": "https://docs.example.com/b2"}
        ),
        "https://docs.example.com/c": httpx.Response(404),
    }
    transport = httpx.MockTransport(_make_handler(by_url))

    async def fake_check(section_urls, *, concurrency=10):
        async with httpx.AsyncClient(transport=transport) as client:
            sem = asyncio.Semaphore(10)
            return list(await asyncio.gather(*[
                audit._check_url(client, sem, url, title)
                for url, title in section_urls
            ]))

    with patch.object(audit, "_check_section_urls", side_effect=fake_check):
        result = asyncio.run(audit.audit_corpus(corpus_path, do_discover=False))

    assert result.discovery_skipped is True
    by_status = {s.url: s.status for s in result.sections}
    assert by_status["https://docs.example.com/a"] == "fresh"
    assert by_status["https://docs.example.com/b"] == "moved"
    assert by_status["https://docs.example.com/c"] == "broken"

    moved = next(s for s in result.sections if s.status == "moved")
    assert moved.final_url == "https://docs.example.com/b2"


def test_audit_corpus_falls_back_to_get_when_head_unsupported(tmp_path: Path):
    corpus_path = _make_corpus(
        tmp_path, sections=[{"title": "A", "url": "https://docs.example.com/a"}]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    async def fake_check(section_urls, *, concurrency=10):
        async with httpx.AsyncClient(transport=transport) as client:
            sem = asyncio.Semaphore(10)
            return list(await asyncio.gather(*[
                audit._check_url(client, sem, url, title)
                for url, title in section_urls
            ]))

    with patch.object(audit, "_check_section_urls", side_effect=fake_check):
        result = asyncio.run(audit.audit_corpus(corpus_path, do_discover=False))

    assert result.sections[0].status == "fresh"
    assert result.sections[0].status_code == 200


def test_audit_corpus_runs_discovery_diff(tmp_path: Path):
    corpus_path = _make_corpus(tmp_path)

    async def fake_check(section_urls, *, concurrency=10):
        return [
            audit.SectionAudit(url=url, title=title, status="fresh", status_code=200)
            for url, title in section_urls
        ]

    async def fake_discover(base_url):
        return [
            "https://docs.example.com/a",  # in corpus
            "https://docs.example.com/b",  # in corpus
            # /c missing → orphan
            "https://docs.example.com/d",  # new upstream URL
        ]

    with patch.object(audit, "_check_section_urls", side_effect=fake_check), \
         patch.object(audit, "_discover_fresh_urls", side_effect=fake_discover):
        result = asyncio.run(audit.audit_corpus(corpus_path, do_discover=True))

    assert result.discovery_skipped is False
    assert result.new_urls == ["https://docs.example.com/d"]
    assert result.orphan_urls == ["https://docs.example.com/c"]


def test_audit_corpus_records_discovery_failure(tmp_path: Path):
    corpus_path = _make_corpus(tmp_path)

    async def fake_check(section_urls, *, concurrency=10):
        return [
            audit.SectionAudit(url=url, title=title, status="fresh")
            for url, title in section_urls
        ]

    async def fake_discover(base_url):
        raise RuntimeError("provider unavailable")

    with patch.object(audit, "_check_section_urls", side_effect=fake_check), \
         patch.object(audit, "_discover_fresh_urls", side_effect=fake_discover):
        result = asyncio.run(audit.audit_corpus(corpus_path, do_discover=True))

    assert result.discovery_skipped is True
    assert "provider unavailable" in (result.discovery_error or "")


def test_render_report_contains_summary_and_breakdowns():
    a = audit.CorpusAudit(
        name="demo",
        base_url="https://docs.example.com",
        audited_at="2026-05-07T12:00:00+00:00",
        corpus_path="/data/demo.json",
        sections=[
            audit.SectionAudit(url="https://x/a", title="A", status="fresh", status_code=200),
            audit.SectionAudit(url="https://x/b", title="B", status="broken", status_code=404),
            audit.SectionAudit(
                url="https://x/c",
                title="C",
                status="moved",
                status_code=301,
                final_url="https://x/c2",
            ),
        ],
        new_urls=["https://x/d"],
        orphan_urls=[],
    )
    report = audit.render_report(a)

    assert "# Audit -- demo" in report
    assert "fresh: 1" in report
    assert "broken: 1" in report
    assert "moved: 1" in report
    assert "https://x/b" in report
    assert "https://x/c2" in report
    assert "https://x/d" in report


def test_audit_main_returns_2_when_broken_urls_present(tmp_path: Path):
    corpus_path = _make_corpus(tmp_path)
    audit_dir = tmp_path / "audit-out"

    async def fake_check(section_urls, *, concurrency=10):
        return [
            audit.SectionAudit(url=url, title=title, status="broken", status_code=404)
            for url, title in section_urls
        ]

    with patch.object(audit, "find_corpus", return_value=corpus_path), \
         patch.object(audit, "_check_section_urls", side_effect=fake_check):
        rc = audit.audit_main(["demo", "--no-discover", "--report-dir", str(audit_dir)])

    assert rc == 2
    reports = list(audit_dir.glob("demo-*.md"))
    assert len(reports) == 1


def test_audit_main_returns_0_when_clean(tmp_path: Path):
    corpus_path = _make_corpus(tmp_path)
    audit_dir = tmp_path / "audit-out"

    async def fake_check(section_urls, *, concurrency=10):
        return [
            audit.SectionAudit(url=url, title=title, status="fresh", status_code=200)
            for url, title in section_urls
        ]

    with patch.object(audit, "find_corpus", return_value=corpus_path), \
         patch.object(audit, "_check_section_urls", side_effect=fake_check):
        rc = audit.audit_main(["demo", "--no-discover", "--report-dir", str(audit_dir)])

    assert rc == 0


def test_audit_main_returns_1_when_corpus_missing(tmp_path: Path, capsys):
    rc = audit.audit_main(["does-not-exist", "--no-discover"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err.lower()


def test_audit_main_returns_1_on_malformed_json(tmp_path: Path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid")
    audit_dir = tmp_path / "out"

    with patch.object(audit, "find_corpus", return_value=bad):
        rc = audit.audit_main(["bad", "--no-discover", "--report-dir", str(audit_dir)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "not valid json" in err.lower()


def test_classify_maps_auth_and_throttle_codes():
    assert audit._classify(httpx.Response(401))[0] == "auth_required"
    assert audit._classify(httpx.Response(403))[0] == "auth_required"
    assert audit._classify(httpx.Response(429))[0] == "throttled"
    assert audit._classify(httpx.Response(404))[0] == "broken"
    assert audit._classify(httpx.Response(410))[0] == "broken"
    assert audit._classify(httpx.Response(500))[0] == "unreachable"


def test_classify_marks_followed_redirects_as_moved():
    final = httpx.Response(200, request=httpx.Request("HEAD", "https://x/final"))
    final.history = [httpx.Response(301)]
    status, final_url = audit._classify(final)
    assert status == "moved"
    assert final_url == "https://x/final"


def test_check_url_retries_on_429_then_resolves(tmp_path: Path):
    corpus_path = _make_corpus(
        tmp_path, sections=[{"title": "A", "url": "https://docs.example.com/a"}]
    )

    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    async def fake_check(section_urls, *, concurrency=10):
        async with httpx.AsyncClient(transport=transport) as client:
            sem = asyncio.Semaphore(concurrency)
            return list(await asyncio.gather(*[
                audit._check_url(client, sem, url, title)
                for url, title in section_urls
            ]))

    with patch.object(audit, "_check_section_urls", side_effect=fake_check):
        result = asyncio.run(audit.audit_corpus(corpus_path, do_discover=False))

    assert state["calls"] == 2
    assert result.sections[0].status == "fresh"


def test_render_report_has_no_emoji():
    result = audit.CorpusAudit(
        name="demo",
        base_url="https://x",
        audited_at="2026-05-07T12:00:00+00:00",
        corpus_path="/data/demo.json",
        sections=[audit.SectionAudit(url="https://x/a", title="A", status="fresh")],
    )
    report = audit.render_report(result)
    # Quick sanity: each character in the report is in the ASCII range.
    assert all(ord(ch) < 128 for ch in report), "report should be ASCII-only"


def test_audit_corpus_propagates_unexpected_errors(tmp_path: Path):
    """Bug class exceptions should NOT be swallowed as 'discovery skipped'."""
    corpus_path = _make_corpus(tmp_path)

    async def fake_check(section_urls, *, concurrency=10):
        return [
            audit.SectionAudit(url=url, title=title, status="fresh")
            for url, title in section_urls
        ]

    async def fake_discover(base_url):
        raise TypeError("genuine bug, do not swallow")

    with patch.object(audit, "_check_section_urls", side_effect=fake_check), \
         patch.object(audit, "_discover_fresh_urls", side_effect=fake_discover):
        with pytest.raises(TypeError):
            asyncio.run(audit.audit_corpus(corpus_path, do_discover=True))


def test_sanitize_filename_component_strips_unsafe_chars():
    assert audit._sanitize_filename_component("ok-name_1.0") == "ok-name_1.0"
    assert audit._sanitize_filename_component("a/b\\c:d") == "a-b-c-d"
    assert audit._sanitize_filename_component("///") == "audit"
