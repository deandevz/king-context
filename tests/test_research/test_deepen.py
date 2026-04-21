from unittest.mock import AsyncMock, patch

import pytest

from king_context.research.config import EffortLevel, ResearchConfig
from king_context.research.deepen import run_deepening_loop
from king_context.research.fetch import SourceDoc
from king_context.research.queries import QueryGenerationError
from king_context.scraper.config import ScraperConfig


def make_config(**over) -> ResearchConfig:
    defaults = dict(
        basic_queries=3,
        medium_queries=5,
        medium_iterations=1,
        medium_followups=3,
        high_queries=2,
        high_iterations=2,
        high_followups=2,
    )
    defaults.update(over)
    return ResearchConfig(
        scraper=ScraperConfig(openrouter_api_key="fake", concurrency=3),
        exa_api_key="exa-fake",
        **defaults,
    )


def mk_doc(
    url: str = "https://ex.com/a",
    query: str = "q",
    iteration: int = 0,
    title: str = "T",
) -> SourceDoc:
    return SourceDoc(
        url=url,
        title=title,
        content="c" * 700,
        author=None,
        published_date=None,
        domain="ex.com",
        query=query,
        discovery_iteration=iteration,
        score=0.5,
        fetch_path="exa",
    )


async def test_basic_runs_one_batch_three_queries(tmp_path):
    with patch(
        "king_context.research.deepen.generate_queries_fn",
        new_callable=AsyncMock,
        return_value=["q1", "q2", "q3"],
    ) as gen, patch(
        "king_context.research.deepen.fetch_fn",
        new_callable=AsyncMock,
    ) as fetch:
        fetch.side_effect = lambda q, i, cfg, client: [
            mk_doc(url=f"https://ex.com/{q}", query=q, iteration=i)
        ]
        docs = await run_deepening_loop(
            "topic", EffortLevel.BASIC, make_config(), tmp_path
        )

    assert len(docs) == 3
    assert gen.call_count == 1
    assert fetch.call_count == 3
    assert all(d.discovery_iteration == 0 for d in docs)


async def test_medium_runs_initial_plus_one_iteration(tmp_path):
    queries_iter0 = ["a", "b", "c", "d", "e"]
    queries_iter1 = ["f", "g", "h"]

    with patch(
        "king_context.research.deepen.generate_queries_fn",
        new_callable=AsyncMock,
    ) as gen, patch(
        "king_context.research.deepen.fetch_fn",
        new_callable=AsyncMock,
    ) as fetch:
        gen.side_effect = [queries_iter0, queries_iter1]
        fetch.side_effect = lambda q, i, cfg, client: [
            mk_doc(url=f"https://ex.com/{q}", query=q, iteration=i)
        ]
        docs = await run_deepening_loop(
            "topic",
            EffortLevel.MEDIUM,
            make_config(
                medium_queries=5, medium_iterations=1, medium_followups=3
            ),
            tmp_path,
        )

    assert len(docs) == 8
    assert gen.call_count == 2
    assert fetch.call_count == 8
    iter0 = [d for d in docs if d.discovery_iteration == 0]
    iter1 = [d for d in docs if d.discovery_iteration == 1]
    assert len(iter0) == 5
    assert len(iter1) == 3


async def test_iteration_returns_zero_new_queries_breaks_loop(tmp_path):
    with patch(
        "king_context.research.deepen.generate_queries_fn",
        new_callable=AsyncMock,
    ) as gen, patch(
        "king_context.research.deepen.fetch_fn",
        new_callable=AsyncMock,
    ) as fetch:
        gen.side_effect = [["q1", "q2", "q3"], []]
        fetch.side_effect = lambda q, i, cfg, client: [
            mk_doc(url=f"https://ex.com/{q}", query=q, iteration=i)
        ]
        docs = await run_deepening_loop(
            "topic", EffortLevel.HIGH, make_config(), tmp_path
        )

    assert gen.call_count == 2
    assert len(docs) == 3
    assert all(d.discovery_iteration == 0 for d in docs)


async def test_generate_queries_fails_returns_prior_results(tmp_path):
    with patch(
        "king_context.research.deepen.generate_queries_fn",
        new_callable=AsyncMock,
    ) as gen, patch(
        "king_context.research.deepen.fetch_fn",
        new_callable=AsyncMock,
    ) as fetch:
        gen.side_effect = [
            ["q1", "q2"],
            QueryGenerationError("LLM blew up"),
        ]
        fetch.side_effect = lambda q, i, cfg, client: [
            mk_doc(url=f"https://ex.com/{q}", query=q, iteration=i)
        ]
        docs = await run_deepening_loop(
            "topic", EffortLevel.MEDIUM, make_config(), tmp_path
        )

    assert len(docs) == 2
    assert all(d.discovery_iteration == 0 for d in docs)
    assert gen.call_count == 2


async def test_url_dedup_across_iterations(tmp_path):
    async def fake_fetch(q, i, cfg, client):
        if i == 0:
            return [
                mk_doc(url="https://ex.com/shared", query=q, iteration=0),
                mk_doc(url="https://ex.com/only-iter0", query=q, iteration=0),
            ]
        return [
            mk_doc(url="https://ex.com/shared", query=q, iteration=1),
            mk_doc(url="https://ex.com/only-iter1", query=q, iteration=1),
        ]

    with patch(
        "king_context.research.deepen.generate_queries_fn",
        new_callable=AsyncMock,
    ) as gen, patch(
        "king_context.research.deepen.fetch_fn",
        side_effect=fake_fetch,
    ):
        gen.side_effect = [["q0"], ["q1"]]
        docs = await run_deepening_loop(
            "topic",
            EffortLevel.MEDIUM,
            make_config(
                medium_queries=1, medium_iterations=1, medium_followups=1
            ),
            tmp_path,
        )

    urls = [d.url for d in docs]
    assert len(urls) == len(set(urls))
    assert "https://ex.com/shared" in urls
    assert "https://ex.com/only-iter0" in urls
    assert "https://ex.com/only-iter1" in urls
    shared = next(d for d in docs if d.url == "https://ex.com/shared")
    assert shared.discovery_iteration == 0


async def test_iteration_json_checkpoint_written(tmp_path):
    with patch(
        "king_context.research.deepen.generate_queries_fn",
        new_callable=AsyncMock,
        return_value=["q1", "q2", "q3"],
    ), patch(
        "king_context.research.deepen.fetch_fn",
        new_callable=AsyncMock,
    ) as fetch:
        fetch.side_effect = lambda q, i, cfg, client: [
            mk_doc(url=f"https://ex.com/{q}", query=q, iteration=i)
        ]
        await run_deepening_loop(
            "topic", EffortLevel.BASIC, make_config(), tmp_path
        )

    checkpoint = tmp_path / "iteration_0.json"
    assert checkpoint.exists()
    import json as _json

    data = _json.loads(checkpoint.read_text())
    assert isinstance(data, list)
    assert len(data) == 3
    assert data[0]["fetch_path"] == "exa"


async def test_initial_generation_failure_returns_empty(tmp_path):
    with patch(
        "king_context.research.deepen.generate_queries_fn",
        new_callable=AsyncMock,
        side_effect=QueryGenerationError("boom"),
    ), patch(
        "king_context.research.deepen.fetch_fn",
        new_callable=AsyncMock,
    ) as fetch:
        docs = await run_deepening_loop(
            "topic", EffortLevel.BASIC, make_config(), tmp_path
        )

    assert docs == []
    fetch.assert_not_called()


async def test_fetch_exception_does_not_abort_iteration(tmp_path):
    async def flaky_fetch(q, i, cfg, client):
        if q == "bad":
            raise RuntimeError("network down")
        return [mk_doc(url=f"https://ex.com/{q}", query=q, iteration=i)]

    with patch(
        "king_context.research.deepen.generate_queries_fn",
        new_callable=AsyncMock,
        return_value=["good1", "bad", "good2"],
    ), patch(
        "king_context.research.deepen.fetch_fn",
        side_effect=flaky_fetch,
    ):
        docs = await run_deepening_loop(
            "topic", EffortLevel.BASIC, make_config(), tmp_path
        )

    assert len(docs) == 2
    urls = {d.url for d in docs}
    assert urls == {"https://ex.com/good1", "https://ex.com/good2"}
