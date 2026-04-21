import asyncio
import logging
import re
from dataclasses import dataclass

from exa_py import Exa

from king_context.research.config import ResearchConfig

logger = logging.getLogger(__name__)


MAX_ATTEMPTS = 3
BACKOFF_DELAYS = (1.0, 2.0)


@dataclass
class ExaResult:
    url: str
    title: str
    text: str
    highlights: list[str]
    author: str | None
    published_date: str | None
    score: float


class ExaTransientError(Exception):
    """Retry-able: 429, 5xx, network errors."""


class ExaPermanentError(Exception):
    """Skip this query: 422 (per-query issue)."""


class ExaBudgetError(Exception):
    """Fatal: 402 — credits exhausted. Abort the whole run."""


class ExaConfigError(Exception):
    """Fatal: 400 or 401 — bug in request or missing/invalid key."""


_STATUS_RE = re.compile(r"\b(4\d\d|5\d\d)\b")


def _extract_status(err: Exception) -> int | None:
    code = getattr(err, "status_code", None)
    if isinstance(code, int):
        return code
    status = getattr(err, "status", None)
    if isinstance(status, int):
        return status
    match = _STATUS_RE.search(str(err))
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _classify_error(err: Exception) -> Exception:
    status = _extract_status(err)
    if status is None:
        return ExaTransientError(f"Unknown Exa error: {err}")
    if status == 402:
        return ExaBudgetError(f"Exa credits exhausted (402): {err}")
    if status in (400, 401):
        return ExaConfigError(f"Exa config error ({status}): {err}")
    if status == 422:
        return ExaPermanentError(f"Exa unprocessable (422): {err}")
    if status == 429 or 500 <= status < 600:
        return ExaTransientError(f"Exa transient error ({status}): {err}")
    return ExaTransientError(f"Unclassified Exa error ({status}): {err}")


def _parse_results(response) -> list[ExaResult]:
    raw_results = getattr(response, "results", None) or []
    parsed: list[ExaResult] = []
    for item in raw_results:
        parsed.append(
            ExaResult(
                url=getattr(item, "url", "") or "",
                title=getattr(item, "title", "") or "",
                text=getattr(item, "text", "") or "",
                highlights=list(getattr(item, "highlights", None) or []),
                author=getattr(item, "author", None),
                published_date=getattr(item, "published_date", None),
                score=float(getattr(item, "score", 0.0) or 0.0),
            )
        )
    return parsed


def _call_exa_sync(client: Exa, query: str, config: ResearchConfig):
    return client.search_and_contents(
        query=query,
        type="auto",
        num_results=config.exa_results_per_query,
        text={
            "max_characters": config.exa_max_chars,
            "verbosity": "full",
            "exclude_sections": ["navigation", "footer", "sidebar"],
        },
        highlights={"max_characters": 2000},
        livecrawl="always",
    )


async def search(query: str, config: ResearchConfig) -> list[ExaResult]:
    """Run one Exa search_and_contents call. Returns parsed results."""
    client = Exa(api_key=config.exa_api_key)
    loop = asyncio.get_running_loop()

    last_transient: ExaTransientError | None = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            response = await loop.run_in_executor(
                None, _call_exa_sync, client, query, config
            )
            return _parse_results(response)
        except Exception as err:
            mapped = _classify_error(err)
            if isinstance(mapped, ExaPermanentError):
                logger.warning(
                    "Exa skipped query %r due to permanent error: %s", query, err
                )
                return []
            if isinstance(mapped, (ExaBudgetError, ExaConfigError)):
                raise mapped from err
            if isinstance(mapped, ExaTransientError):
                last_transient = mapped
                if attempt < MAX_ATTEMPTS - 1:
                    delay = BACKOFF_DELAYS[attempt]
                    logger.warning(
                        "Exa transient error (attempt %d/%d) for %r: %s; retrying in %ss",
                        attempt + 1,
                        MAX_ATTEMPTS,
                        query,
                        err,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise mapped from err
            raise mapped from err

    if last_transient is not None:
        raise last_transient
    return []
