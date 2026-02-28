import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from king_context.scraper.config import ScraperConfig
from king_context.scraper.discover import get_work_dir, _update_step


INCLUDE_PATTERNS = [
    r"/docs?/",
    r"/api(?:/|$)",
    r"/reference/",
    r"/guides?(?:/|$)",
    r"/tutorials?(?:/|$)",
    r"/getting[-_]started",
    r"/quickstart",
    r"/overview",
    r"/concepts?/",
    r"/examples?/",
    r"/manual/",
    r"/handbook/",
]

EXCLUDE_PATTERNS = [
    r"/blog/",
    r"/changelog/",
    r"/releases?/",
    r"/community/",
    r"/forum/",
    r"/pricing(?:/|$)",
    r"/about(?:/|$)",
    r"/contact(?:/|$)",
    r"/careers?(?:/|$)",
    r"/jobs?(?:/|$)",
    r"/legal/",
    r"/privacy(?:/|$)",
    r"/terms(?:/|$)",
    r"/search(?:/|$)",
    r"/tag/",
    r"/category/",
    r"/author/",
    r"/login(?:/|$)",
    r"/signup(?:/|$)",
    r"/register(?:/|$)",
]

FILTER_PROMPT = """\
You are a documentation URL classifier. Given a list of URLs from a documentation website, \
classify each URL as one of:
- "doc": This is a documentation page (API reference, guide, tutorial, concept, example, etc.)
- "maybe": Unclear, could be documentation
- "skip": Not documentation (blog post, changelog, pricing, community page, etc.)

Respond with a JSON object where keys are the exact URLs and values are "doc", "maybe", or "skip".

URLs to classify:
{urls}"""


@dataclass
class FilterResult:
    accepted: list[str]
    rejected: list[str]
    maybe: list[str]
    filter_method: str
    llm_fallback_used: bool


def _deduplicate(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for url in urls:
        normalized = url.split("?")[0].split("#")[0].rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            result.append(url)
    return result


def _matches_patterns(path: str, patterns: list[str]) -> bool:
    return any(re.search(pat, path, re.IGNORECASE) for pat in patterns)


def _call_llm(urls: list[str], config: ScraperConfig) -> dict[str, str]:
    prompt = FILTER_PROMPT.format(urls="\n".join(urls))
    response = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {config.openrouter_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": config.enrichment_model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
        timeout=60.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def filter_urls(urls: list[str], base_url: str, config: ScraperConfig) -> FilterResult:
    urls = _deduplicate(urls)

    accepted: list[str] = []
    rejected: list[str] = []
    maybe: list[str] = []

    for url in urls:
        path = urlparse(url).path
        if _matches_patterns(path, EXCLUDE_PATTERNS):
            rejected.append(url)
        elif _matches_patterns(path, INCLUDE_PATTERNS):
            accepted.append(url)
        else:
            maybe.append(url)

    total = len(urls)
    rejected_ratio = len(rejected) / total if total > 0 else 0.0
    llm_fallback_used = False
    filter_method = "heuristic"

    if config.filter_llm_fallback and (len(accepted) < 10 or rejected_ratio > 0.6):
        to_classify = maybe.copy()
        if len(accepted) < 10:
            to_classify.extend(rejected)

        if to_classify:
            try:
                classifications = _call_llm(to_classify, config)
                new_accepted = accepted.copy()
                new_rejected = rejected.copy()
                new_maybe = maybe.copy()

                for url in to_classify:
                    label = classifications.get(url, "maybe")
                    if label == "doc":
                        if url in new_rejected:
                            new_rejected.remove(url)
                        if url in new_maybe:
                            new_maybe.remove(url)
                        if url not in new_accepted:
                            new_accepted.append(url)
                    elif label == "skip":
                        if url in new_maybe:
                            new_maybe.remove(url)
                        if url not in new_rejected:
                            new_rejected.append(url)

                accepted, rejected, maybe = new_accepted, new_rejected, new_maybe
                llm_fallback_used = True
                filter_method = "heuristic+llm"
            except Exception:
                pass

    work_dir = get_work_dir(base_url)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "filtered_urls.json").write_text(
        json.dumps(
            {
                "accepted": accepted,
                "rejected": rejected,
                "maybe": maybe,
                "filter_method": filter_method,
                "llm_fallback_used": llm_fallback_used,
            },
            indent=2,
        )
    )
    _update_step(work_dir, "filtering", {
        "status": "done",
        "accepted": len(accepted),
        "rejected": len(rejected),
        "maybe": len(maybe),
        "filter_method": filter_method,
    })

    return FilterResult(
        accepted=accepted,
        rejected=rejected,
        maybe=maybe,
        filter_method=filter_method,
        llm_fallback_used=llm_fallback_used,
    )
