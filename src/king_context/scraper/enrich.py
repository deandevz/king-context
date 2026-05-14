import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from king_context.scraper import enrich_cache
from king_context.scraper.chunk import Chunk
from king_context.scraper.config import ScraperConfig
from king_context.scraper.discover import _update_step
from llm_providers import LLMClient, ProviderError, get_stage_clients
from llm_providers.config import ResolvedConfig, resolve
from llm_providers.fallback import FallbackClient
from llm_providers.logging import log_fallback
from llm_providers.openrouter import OpenRouterClient


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


# Derived from the prompt itself so any edit to ENRICHMENT_PROMPT automatically
# invalidates cached entries — no human discipline required.
PROMPT_VERSION = hashlib.sha256(ENRICHMENT_PROMPT.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class EnrichedChunk:
    title: str
    path: str
    url: str
    content: str
    keywords: list[str]
    use_cases: list[str]
    tags: list[str]
    priority: int
    content_hash: str = field(default="")

    def __post_init__(self) -> None:
        if not self.content_hash:
            object.__setattr__(
                self,
                "content_hash",
                hashlib.sha256(self.content.encode("utf-8")).hexdigest(),
            )


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
    """Estimate enrichment cost based on chunk token counts and provider."""
    total_chunks = len(chunks)
    total_batches = (
        (total_chunks + config.enrichment_batch_size - 1) // config.enrichment_batch_size
        if total_chunks > 0 else 0
    )

    prompt_overhead = 200
    estimated_input_tokens = sum(c.token_count for c in chunks) + prompt_overhead * total_chunks
    estimated_output_tokens = total_chunks * 150

    provider_cfg = resolve(
        "enrich",
        validate=False,
        model_override=config.enrichment_model,
        openrouter_api_key_override=config.openrouter_api_key,
    )

    estimated_cost = 0.0
    cost_note = "local_runtime_only"
    if provider_cfg.provider == "openrouter":
        # Approximate pricing for gpt-4o-mini: $0.15/1M input, $0.60/1M output
        input_cost_per_token = 0.15 / 1_000_000
        output_cost_per_token = 0.60 / 1_000_000
        estimated_cost = (
            estimated_input_tokens * input_cost_per_token
            + estimated_output_tokens * output_cost_per_token
        )
        cost_note = "estimated_openrouter_cost"

    return {
        "total_chunks": total_chunks,
        "total_batches": total_batches,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "provider": provider_cfg.provider,
        "model": provider_cfg.model,
        "estimated_cost": round(estimated_cost, 6),
        "cost_note": cost_note,
        "fallback_enabled": provider_cfg.fallback_enabled,
        "fallback_warning": (
            provider_cfg.provider == "ollama" and provider_cfg.fallback_enabled
        ),
    }


async def call_openrouter(prompt: str, config: ScraperConfig) -> dict:
    """Deprecated compatibility wrapper for direct OpenRouter enrichment."""
    provider_cfg = resolve(
        "enrich",
        validate=False,
        model_override=config.enrichment_model,
        openrouter_api_key_override=config.openrouter_api_key,
    )
    openrouter_cfg = ResolvedConfig(
        stage="enrich",
        provider="openrouter",
        model=config.enrichment_model,
        concurrency=provider_cfg.concurrency,
        openrouter_api_key=config.openrouter_api_key or provider_cfg.openrouter_api_key,
        ollama_api_mode=provider_cfg.ollama_api_mode,
        ollama_base_url=provider_cfg.ollama_base_url,
        ollama_api_key=provider_cfg.ollama_api_key,
        fallback_enabled=False,
        fallback_model=provider_cfg.fallback_model,
    )
    return await OpenRouterClient(openrouter_cfg).complete(prompt)


def _to_enriched_chunk(chunk: Chunk, enrichment: dict) -> EnrichedChunk:
    return EnrichedChunk(
        title=chunk.title,
        path=chunk.path,
        url=chunk.source_url,
        content=chunk.content,
        keywords=enrichment["keywords"],
        use_cases=enrichment["use_cases"],
        tags=enrichment["tags"],
        priority=enrichment["priority"],
        content_hash=chunk.content_hash,
    )


class _SemaphoredClient(LLMClient):
    def __init__(self, client: LLMClient, semaphore: asyncio.Semaphore) -> None:
        self._client = client
        self._semaphore = semaphore
        self.name = client.name
        self.model = client.model
        self.concurrency = client.concurrency

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        async with self._semaphore:
            return await self._client.complete(
                prompt,
                system=system,
                json_mode=json_mode,
            )


def _collect_provider_semaphores(
    client: LLMClient | None,
    semaphores: dict[str, asyncio.Semaphore],
) -> None:
    if client is None:
        return
    if isinstance(client, FallbackClient):
        _collect_provider_semaphores(client.primary, semaphores)
        _collect_provider_semaphores(client.fallback, semaphores)
        return
    semaphores.setdefault(client.name, asyncio.Semaphore(client.concurrency))


def _with_provider_semaphores(
    client: LLMClient | None,
    semaphores: dict[str, asyncio.Semaphore],
) -> LLMClient | None:
    if client is None:
        return None
    if isinstance(client, FallbackClient):
        primary = _with_provider_semaphores(client.primary, semaphores)
        fallback = _with_provider_semaphores(client.fallback, semaphores)
        assert primary is not None
        assert fallback is not None
        return FallbackClient(primary=primary, fallback=fallback, stage=client.stage)
    return _SemaphoredClient(client, semaphores[client.name])


async def _enrich_one(
    chunk: Chunk,
    primary_client: LLMClient,
    schema_fallback: LLMClient | None = None,
) -> EnrichedChunk | None:
    """Enrich a single chunk. Never raises; returns ``None`` on terminal failure.

    Tries the primary client up to three times. Transient ``ProviderError``
    rounds are retried; a non-transient ``ProviderError`` (e.g. unparseable
    JSON, schema validation gone wrong) breaks the retry loop early and falls
    through to the schema fallback. Validation failures use the full retry
    budget. If the schema fallback also fails, returns ``None`` so the caller
    can record the chunk as "lost" and continue the batch.

    The "never raises per chunk" contract is what lets ``enrich_chunks`` run
    a 500-chunk batch without one bad model response cancelling the rest of
    the in-flight requests (#47).

    Cache invariant: only successful primary responses get written to the
    enrichment cache. The schema fallback's outputs are intentionally NOT
    cached under the primary's key, because next run with the primary
    healthy would otherwise serve fallback content as if it were primary.
    """
    # Defensive ``getattr`` so a future client wrapper that drops ``.model``
    # produces a stable fallback key rather than a swallowed AttributeError.
    model_id = getattr(primary_client, "model", "unknown")
    cache_key = enrich_cache.make_key(chunk.content, model_id, PROMPT_VERSION)
    cached = enrich_cache.get(cache_key)
    if cached is not None and not validate_enrichment(cached):
        return _to_enriched_chunk(chunk, cached)

    prompt = ENRICHMENT_PROMPT.format(title=chunk.title, content=chunk.content)
    fallback_reason = "validation_failed_3x"

    for attempt in range(3):  # 1 initial attempt + 2 retries
        # Reset to the validation-failure default each iteration so the
        # final reason reflects the LAST attempt's failure mode, not a
        # stale value from an earlier transient retry.
        attempt_reason = "validation_failed_3x"
        try:
            enrichment = await primary_client.complete(prompt)
            errors = validate_enrichment(enrichment)
            if not errors:
                enrich_cache.put(cache_key, enrichment)
                return _to_enriched_chunk(chunk, enrichment)
            # Validation failed; keep retrying within the budget.
        except ProviderError as exc:
            attempt_reason = f"primary_provider_error:{exc.reason or 'unknown'}"
            if not exc.transient:
                # Non-transient: more retries will not help. Break out and
                # let the schema fallback (if any) absorb the failure.
                fallback_reason = attempt_reason
                break
        except (asyncio.TimeoutError, ValueError, json.JSONDecodeError) as exc:
            # Narrow defensive catch: timeouts surface as TimeoutError on
            # newer Python; JSON parse and value errors come from the
            # provider's response handling. Programming errors
            # (AttributeError, TypeError) deliberately propagate so a
            # regression cannot hide as silent retries.
            attempt_reason = f"primary_unexpected_error:{type(exc).__name__}"
        fallback_reason = attempt_reason

    if schema_fallback is not None:
        log_fallback(
            stage="enrich",
            primary=primary_client,
            fallback=schema_fallback,
            reason=fallback_reason,
        )
        try:
            enrichment = await schema_fallback.complete(prompt)
            fallback_errors = validate_enrichment(enrichment)
            if not fallback_errors:
                # Intentionally no cache write: see docstring "Cache invariant".
                return _to_enriched_chunk(chunk, enrichment)
        except (ProviderError, asyncio.TimeoutError, ValueError, json.JSONDecodeError):
            # Provider-class failures from the fallback are absorbed by design;
            # programming errors propagate so regressions surface in CI.
            pass

    return None


async def enrich_chunks(
    chunks: list[Chunk],
    config: ScraperConfig,
    output_dir: Path | None = None,
) -> list[EnrichedChunk]:
    """Enrich chunks in batches, saving a checkpoint JSON after each batch.

    Supports resume: if ``output_dir`` contains prior batch files under
    ``enriched/``, already-processed chunks are skipped and new batches
    continue numbering from where the previous run left off.
    """
    enriched: list[EnrichedChunk] = []
    enriched_dir: Path | None = None
    batch_offset = 0

    if output_dir is not None:
        enriched_dir = output_dir / "enriched"
        enriched_dir.mkdir(parents=True, exist_ok=True)

        # --- resume detection ---
        existing_batches = sorted(enriched_dir.glob("batch_*.json"))
        if existing_batches:
            last_batch_path = existing_batches[-1]
            previous_data = json.loads(last_batch_path.read_text())
            already_enriched = len(previous_data)

            # Reconstruct EnrichedChunk objects from the saved data
            for item in previous_data:
                enriched.append(EnrichedChunk(
                    title=item["title"],
                    path=item["path"],
                    url=item["url"],
                    content=item["content"],
                    keywords=item["keywords"],
                    use_cases=item["use_cases"],
                    tags=item["tags"],
                    priority=item["priority"],
                    content_hash=item.get("content_hash", ""),
                ))

            total_chunks = len(chunks)
            print(f"Resuming: {already_enriched}/{total_chunks} chunks already enriched")

            if already_enriched >= total_chunks:
                _update_step(output_dir, "enrichment", {
                    "status": "done",
                    "enriched": already_enriched,
                    "total": total_chunks,
                })
                return enriched

            # Skip already-processed chunks
            chunks = chunks[already_enriched:]
            # Next batch number continues from existing count
            batch_offset = len(existing_batches)

    clients = get_stage_clients(
        "enrich",
        model_override=config.enrichment_model,
        openrouter_api_key_override=config.openrouter_api_key,
    )
    semaphores: dict[str, asyncio.Semaphore] = {}
    _collect_provider_semaphores(clients.primary, semaphores)
    _collect_provider_semaphores(clients.schema_fallback, semaphores)
    primary_client = _with_provider_semaphores(clients.primary, semaphores)
    schema_fallback = _with_provider_semaphores(clients.schema_fallback, semaphores)
    assert primary_client is not None

    # Avoid double-billing when the primary is a FallbackClient whose own
    # fallback leg is the same underlying client as the configured schema
    # fallback. ``_with_provider_semaphores`` re-wraps clients, so identity
    # on the wrapper is not enough; compare the underlying ``_client`` (or
    # the wrapper itself if it has none).
    def _unwrap(c: LLMClient | None) -> LLMClient | None:
        return getattr(c, "_client", c)

    if (
        isinstance(primary_client, FallbackClient)
        and schema_fallback is not None
        and _unwrap(primary_client.fallback) is _unwrap(schema_fallback)
    ):
        schema_fallback = None

    batch_size = config.enrichment_batch_size
    total_chunks = len(chunks) + len(enriched)  # original total
    total_dropped = 0

    async def guarded(chunk: Chunk) -> EnrichedChunk | None:
        return await _enrich_one(
            chunk,
            primary_client,
            schema_fallback,
        )

    for batch_idx, start in enumerate(range(0, len(chunks), batch_size)):
        batch_num = batch_offset + batch_idx
        batch = chunks[start:start + batch_size]
        # ``return_exceptions=True`` so one chunk's failure cannot cancel the
        # rest of the in-flight batch (#47). ``_enrich_one`` already absorbs
        # per-chunk errors and returns ``None`` on terminal failure; this
        # guard is defensive in case a future change introduces a new raise
        # path or a cancellation slips through.
        results: list[EnrichedChunk | None | BaseException] = await asyncio.gather(
            *[guarded(c) for c in batch], return_exceptions=True
        )

        batch_dropped = 0
        for result in results:
            # An outer-task cancellation propagates through ``await
            # asyncio.gather(...)`` directly; a child CancelledError
            # returned as a value here means a per-task cancel that we
            # treat as a per-chunk failure and keep going.
            if isinstance(result, asyncio.CancelledError):
                print(
                    f"  warning: chunk cancelled: {result}",
                    file=sys.stderr,
                )
                batch_dropped += 1
                continue
            if isinstance(result, BaseException):
                print(
                    f"  warning: chunk failed with {type(result).__name__}: {result}",
                    file=sys.stderr,
                )
                batch_dropped += 1
                continue
            if result is None:
                # _enrich_one absorbed the failure and returned None.
                batch_dropped += 1
                continue
            enriched.append(result)

        total_dropped += batch_dropped
        if batch_dropped:
            survived = len(batch) - batch_dropped
            print(
                f"  batch {batch_num:04d}: {survived} enriched, "
                f"{batch_dropped} dropped (running total dropped: {total_dropped})",
                file=sys.stderr,
            )

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
                    "content_hash": e.content_hash,
                }
                for e in enriched
            ]
            (enriched_dir / f"batch_{batch_num:04d}.json").write_text(
                json.dumps(checkpoint, indent=2)
            )

        if output_dir is not None:
            _update_step(output_dir, "enrichment", {
                "status": "in_progress",
                "enriched": len(enriched),
                "total": total_chunks,
            })

    if output_dir is not None:
        _update_step(output_dir, "enrichment", {
            "status": "done",
            "enriched": len(enriched),
            "total": total_chunks,
        })

    return enriched
