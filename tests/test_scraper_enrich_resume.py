"""Tests for enrich_chunks() resume support."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from king_context.scraper.chunk import Chunk
from king_context.scraper.config import ScraperConfig
from king_context.scraper.enrich import EnrichedChunk, enrich_chunks


def _make_chunk(index: int) -> Chunk:
    return Chunk(
        title=f"Section {index}",
        breadcrumb=f"Section {index}",
        content=f"Content for section {index}.",
        source_url=f"https://docs.example.com/page-{index}",
        path=f"/page/section-{index}",
        token_count=10,
    )


def _make_enriched_dict(index: int) -> dict:
    """Return a serialized enriched chunk as stored in batch files."""
    return {
        "title": f"Section {index}",
        "path": f"/page/section-{index}",
        "url": f"https://docs.example.com/page-{index}",
        "content": f"Content for section {index}.",
        "keywords": ["k1", "k2", "k3", "k4", "k5"],
        "use_cases": ["u1", "u2"],
        "tags": ["t1"],
        "priority": 5,
    }


VALID_ENRICHMENT = {
    "keywords": ["k1", "k2", "k3", "k4", "k5"],
    "use_cases": ["u1", "u2"],
    "tags": ["t1"],
    "priority": 5,
}


def _config() -> ScraperConfig:
    return ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=10,
    )


# ---------------------------------------------------------------------------
# 1. Partial resume: 20 already enriched out of 50 total
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_partial_resume(tmp_path: Path):
    """When enriched/ has a batch with 20 chunks and total is 50,
    only the remaining 30 chunks should be sent to the LLM."""
    enriched_dir = tmp_path / "enriched"
    enriched_dir.mkdir()

    # Pre-existing batch with 20 enriched chunks (cumulative)
    previous = [_make_enriched_dict(i) for i in range(20)]
    (enriched_dir / "batch_0001.json").write_text(json.dumps(previous, indent=2))

    # Full set of 50 chunks
    chunks = [_make_chunk(i) for i in range(50)]
    config = _config()

    call_count = 0

    async def mock_openrouter(prompt, cfg):
        nonlocal call_count
        call_count += 1
        return VALID_ENRICHMENT

    with patch("king_context.scraper.enrich.call_openrouter", side_effect=mock_openrouter):
        result = await enrich_chunks(chunks, config, output_dir=tmp_path)

    # Should have called the API only for the remaining 30 chunks
    assert call_count == 30
    # Returned list includes pre-existing 20 + newly enriched 30
    assert len(result) == 50
    # First 20 come from the batch file (pre-existing)
    assert result[0].title == "Section 0"
    assert result[19].title == "Section 19"


# ---------------------------------------------------------------------------
# 2. Full resume: all chunks already enriched => no API calls
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_full_resume_no_api_calls(tmp_path: Path):
    """When all chunks are already enriched, return the full list without
    making any API calls."""
    enriched_dir = tmp_path / "enriched"
    enriched_dir.mkdir()

    total = 25
    previous = [_make_enriched_dict(i) for i in range(total)]
    (enriched_dir / "batch_0002.json").write_text(json.dumps(previous, indent=2))

    chunks = [_make_chunk(i) for i in range(total)]
    config = _config()

    call_count = 0

    async def mock_openrouter(prompt, cfg):
        nonlocal call_count
        call_count += 1
        return VALID_ENRICHMENT

    with patch("king_context.scraper.enrich.call_openrouter", side_effect=mock_openrouter):
        result = await enrich_chunks(chunks, config, output_dir=tmp_path)

    assert call_count == 0
    assert len(result) == total
    # Verify the returned chunks have correct data from the batch file
    for i, ec in enumerate(result):
        assert ec.title == f"Section {i}"
        assert ec.keywords == ["k1", "k2", "k3", "k4", "k5"]


# ---------------------------------------------------------------------------
# 3. Fresh start: empty enriched/ dir => process all chunks
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fresh_start_no_existing_batches(tmp_path: Path):
    """When enriched/ is empty, all chunks are processed from scratch."""
    chunks = [_make_chunk(i) for i in range(15)]
    config = _config()

    call_count = 0

    async def mock_openrouter(prompt, cfg):
        nonlocal call_count
        call_count += 1
        return VALID_ENRICHMENT

    with patch("king_context.scraper.enrich.call_openrouter", side_effect=mock_openrouter):
        result = await enrich_chunks(chunks, config, output_dir=tmp_path)

    assert call_count == 15
    assert len(result) == 15
    # Batch file should have been created
    enriched_dir = tmp_path / "enriched"
    batch_files = sorted(enriched_dir.glob("batch_*.json"))
    assert len(batch_files) >= 1
    # First batch should be batch_0000
    assert batch_files[0].name == "batch_0000.json"


# ---------------------------------------------------------------------------
# 4. Correct batch numbering: continues from last existing batch number
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_batch_numbering_continues(tmp_path: Path):
    """New batches continue numbering from the last existing batch file.
    If last is batch_0002.json, next should be batch_0003.json."""
    enriched_dir = tmp_path / "enriched"
    enriched_dir.mkdir()

    # Simulate 3 previous batch files (batch_0000, batch_0001, batch_0002)
    # Each cumulative, with the last having 20 chunks
    for i in range(3):
        count = (i + 1) * 7  # 7, 14, 21 -- but only the last one matters
        data = [_make_enriched_dict(j) for j in range(count)]
        (enriched_dir / f"batch_{i:04d}.json").write_text(json.dumps(data, indent=2))

    # Last batch (batch_0002) has 21 enriched chunks
    # Total chunks: 31, so 10 remaining
    total = 31
    chunks = [_make_chunk(i) for i in range(total)]
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=5,  # 10 remaining / 5 = 2 new batches
    )

    async def mock_openrouter(prompt, cfg):
        return VALID_ENRICHMENT

    with patch("king_context.scraper.enrich.call_openrouter", side_effect=mock_openrouter):
        result = await enrich_chunks(chunks, config, output_dir=tmp_path)

    assert len(result) == total

    # Check new batch files were created with correct numbering
    batch_files = sorted(enriched_dir.glob("batch_*.json"))
    batch_names = [f.name for f in batch_files]

    # Original 3 + 2 new = 5 batch files
    assert len(batch_files) == 5
    assert "batch_0003.json" in batch_names
    assert "batch_0004.json" in batch_names

    # The last new batch should be cumulative (contain ALL enriched chunks)
    last_batch_data = json.loads(batch_files[-1].read_text())
    assert len(last_batch_data) == total


# ---------------------------------------------------------------------------
# 5. Cumulative batch content: new batches include pre-existing + new chunks
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_new_batches_are_cumulative(tmp_path: Path):
    """Each new batch file must contain ALL enriched chunks (pre-existing +
    newly enriched), not just the new batch."""
    enriched_dir = tmp_path / "enriched"
    enriched_dir.mkdir()

    # Pre-existing: 5 enriched chunks in batch_0000
    previous = [_make_enriched_dict(i) for i in range(5)]
    (enriched_dir / "batch_0000.json").write_text(json.dumps(previous, indent=2))

    # Total: 10 chunks, batch_size=3 => remaining 5 chunks => 2 new batches
    chunks = [_make_chunk(i) for i in range(10)]
    config = ScraperConfig(
        openrouter_api_key="test-key",
        enrichment_batch_size=3,
    )

    async def mock_openrouter(prompt, cfg):
        return VALID_ENRICHMENT

    with patch("king_context.scraper.enrich.call_openrouter", side_effect=mock_openrouter):
        result = await enrich_chunks(chunks, config, output_dir=tmp_path)

    batch_files = sorted(enriched_dir.glob("batch_*.json"))

    # batch_0001 should have 5 (pre-existing) + 3 (first new batch) = 8
    batch_0001 = json.loads((enriched_dir / "batch_0001.json").read_text())
    assert len(batch_0001) == 8

    # batch_0002 should have all 10
    batch_0002 = json.loads((enriched_dir / "batch_0002.json").read_text())
    assert len(batch_0002) == 10
