import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from king_context.scraper.chunk import Chunk
from king_context.scraper.config import ScraperConfig


ENRICHMENT_PROMPT = """\
You are a documentation metadata specialist. Analyze the following documentation section and generate structured metadata.

Return a JSON object with exactly these fields:
- keywords: list of 5-12 specific technical terms and concepts from this section
- use_cases: list of 2-7 descriptions of when/how to use this feature (start with verbs like "Use when", "Implement when", "Configure when")
- tags: list of 1-5 broad category labels
- priority: integer 1-10 representing importance (10 = core feature, 1 = edge case/deprecated)

Rules:
- keywords: specific, searchable terms; include API names, methods, config keys, error codes
- use_cases: practical scenarios; start with action verbs; be specific, not generic
- tags: broad categories like "authentication", "configuration", "error-handling", "api-reference"
- priority: 10 for main concepts, 7-9 for important features, 4-6 for secondary features, 1-3 for edge cases

Documentation section:
Title: {title}
Content:
{content}

Return only the JSON object, no explanation."""


@dataclass
class EnrichedChunk:
    title: str
    path: str
    url: str
    content: str
    keywords: list[str]
    use_cases: list[str]
    tags: list[str]
    priority: int


def validate_enrichment(enrichment: dict) -> list[str]:
    """Validate enrichment fields. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    keywords = enrichment.get("keywords", [])
    if not isinstance(keywords, list) or not (5 <= len(keywords) <= 12):
        count = len(keywords) if isinstance(keywords, list) else type(keywords).__name__
        errors.append(f"keywords must be a list of 5-12 items, got {count}")

    use_cases = enrichment.get("use_cases", [])
    if not isinstance(use_cases, list) or not (2 <= len(use_cases) <= 7):
        count = len(use_cases) if isinstance(use_cases, list) else type(use_cases).__name__
        errors.append(f"use_cases must be a list of 2-7 items, got {count}")

    tags = enrichment.get("tags", [])
    if not isinstance(tags, list) or not (1 <= len(tags) <= 5):
        count = len(tags) if isinstance(tags, list) else type(tags).__name__
        errors.append(f"tags must be a list of 1-5 items, got {count}")

    priority = enrichment.get("priority")
    if not isinstance(priority, int) or not (1 <= priority <= 10):
        errors.append(f"priority must be an integer 1-10, got {priority!r}")

    return errors


def estimate_cost(chunks: list[Chunk], config: ScraperConfig) -> dict:
    """Estimate enrichment cost based on chunk token counts."""
    total_chunks = len(chunks)
    total_batches = (
        (total_chunks + config.enrichment_batch_size - 1) // config.enrichment_batch_size
        if total_chunks > 0 else 0
    )

    prompt_overhead = 200
    estimated_input_tokens = sum(c.token_count for c in chunks) + prompt_overhead * total_chunks
    estimated_output_tokens = total_chunks * 150

    # Approximate pricing for gpt-4o-mini: $0.15/1M input, $0.60/1M output
    input_cost_per_token = 0.15 / 1_000_000
    output_cost_per_token = 0.60 / 1_000_000
    estimated_cost = (
        estimated_input_tokens * input_cost_per_token
        + estimated_output_tokens * output_cost_per_token
    )

    return {
        "total_chunks": total_chunks,
        "total_batches": total_batches,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "model": config.enrichment_model,
        "estimated_cost": round(estimated_cost, 6),
    }


async def call_openrouter(prompt: str, config: ScraperConfig) -> dict:
    """POST to OpenRouter and return parsed JSON from the model response."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
            json={
                "model": config.enrichment_model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)


async def _enrich_one(chunk: Chunk, config: ScraperConfig) -> EnrichedChunk | None:
    """Enrich a single chunk with up to 2 retries on validation failure."""
    prompt = ENRICHMENT_PROMPT.format(title=chunk.title, content=chunk.content)

    for _ in range(3):  # 1 initial attempt + 2 retries
        try:
            enrichment = await call_openrouter(prompt, config)
            errors = validate_enrichment(enrichment)
            if not errors:
                return EnrichedChunk(
                    title=chunk.title,
                    path=chunk.path,
                    url=chunk.source_url,
                    content=chunk.content,
                    keywords=enrichment["keywords"],
                    use_cases=enrichment["use_cases"],
                    tags=enrichment["tags"],
                    priority=enrichment["priority"],
                )
        except Exception:
            pass

    return None


async def enrich_chunks(
    chunks: list[Chunk],
    config: ScraperConfig,
    output_dir: Path | None = None,
) -> list[EnrichedChunk]:
    """Enrich chunks in batches, saving a checkpoint JSON after each batch."""
    enriched: list[EnrichedChunk] = []
    enriched_dir: Path | None = None

    if output_dir is not None:
        enriched_dir = output_dir / "enriched"
        enriched_dir.mkdir(parents=True, exist_ok=True)

    batch_size = config.enrichment_batch_size

    for batch_num, start in enumerate(range(0, len(chunks), batch_size)):
        batch = chunks[start:start + batch_size]
        results = await asyncio.gather(*[_enrich_one(c, config) for c in batch])

        for result in results:
            if result is not None:
                enriched.append(result)

        if enriched_dir is not None:
            checkpoint = [
                {
                    "title": e.title,
                    "path": e.path,
                    "url": e.url,
                    "content": e.content,
                    "keywords": e.keywords,
                    "use_cases": e.use_cases,
                    "tags": e.tags,
                    "priority": e.priority,
                }
                for e in enriched
            ]
            (enriched_dir / f"batch_{batch_num:04d}.json").write_text(
                json.dumps(checkpoint, indent=2)
            )

    return enriched
