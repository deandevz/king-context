from unittest.mock import patch

from king_context.scraper.filter import filter_urls, FilterResult
from king_context.scraper.config import ScraperConfig


def _api_urls(n: int = 15) -> list[str]:
    return [f"https://docs.example.com/api/endpoint-{i}" for i in range(n)]


def test_filter_excludes_blog(tmp_path, monkeypatch):
    monkeypatch.setattr("king_context.scraper.discover.TEMP_DOCS_DIR", tmp_path)
    config = ScraperConfig(filter_llm_fallback=False)

    urls = [
        "https://docs.example.com/blog/post-1",
        "https://docs.example.com/blog/post-2",
    ]
    result = filter_urls(urls, "https://docs.example.com", config)

    assert len(result.rejected) == 2
    assert len(result.accepted) == 0


def test_filter_includes_api(tmp_path, monkeypatch):
    monkeypatch.setattr("king_context.scraper.discover.TEMP_DOCS_DIR", tmp_path)
    config = ScraperConfig(filter_llm_fallback=False)

    urls = _api_urls(15)
    result = filter_urls(urls, "https://docs.example.com", config)

    assert len(result.accepted) == 15
    assert result.llm_fallback_used is False


def test_filter_maybe_urls(tmp_path, monkeypatch):
    monkeypatch.setattr("king_context.scraper.discover.TEMP_DOCS_DIR", tmp_path)
    config = ScraperConfig(filter_llm_fallback=False)

    urls = _api_urls(15) + ["https://docs.example.com/misc/other"]
    result = filter_urls(urls, "https://docs.example.com", config)

    assert "https://docs.example.com/misc/other" in result.maybe


def test_filter_llm_fallback_triggered(tmp_path, monkeypatch):
    monkeypatch.setattr("king_context.scraper.discover.TEMP_DOCS_DIR", tmp_path)
    config = ScraperConfig(filter_llm_fallback=True)

    # 3 misc URLs → accepted=0 < 10, LLM is triggered
    urls = [
        "https://docs.example.com/misc/page-1",
        "https://docs.example.com/misc/page-2",
        "https://docs.example.com/misc/page-3",
    ]
    mock_classifications = {url: "doc" for url in urls}

    with patch("king_context.scraper.filter._call_llm", return_value=mock_classifications) as mock_llm:
        result = filter_urls(urls, "https://docs.example.com", config)

    mock_llm.assert_called_once()
    assert result.llm_fallback_used is True


def test_filter_llm_fallback_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("king_context.scraper.discover.TEMP_DOCS_DIR", tmp_path)
    config = ScraperConfig(filter_llm_fallback=False)

    urls = ["https://docs.example.com/misc/page-1"]

    with patch("king_context.scraper.filter._call_llm") as mock_llm:
        result = filter_urls(urls, "https://docs.example.com", config)

    mock_llm.assert_not_called()
    assert result.llm_fallback_used is False


def test_filter_removes_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr("king_context.scraper.discover.TEMP_DOCS_DIR", tmp_path)
    config = ScraperConfig(filter_llm_fallback=False)

    # 15 unique API URLs + 2 duplicates of endpoint-0 with different query params
    urls = _api_urls(15) + [
        "https://docs.example.com/api/endpoint-0?version=2",
        "https://docs.example.com/api/endpoint-0?tab=example",
    ]
    result = filter_urls(urls, "https://docs.example.com", config)

    all_urls = result.accepted + result.rejected + result.maybe
    assert len(all_urls) == 15
