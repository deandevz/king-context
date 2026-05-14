"""Drift and staleness audit for an indexed corpus.

Walks the URLs of an existing ``data/<name>.json`` corpus and reports which
ones are still reachable, which moved (redirects), which are broken (404),
and optionally which URLs the upstream docs site has gained or lost
since the corpus was indexed. Pure read only: never mutates the corpus
file or the database.

Designed to run cheaply (HEAD requests, no LLM calls, no provider keys
required for the URL health pass) so contributors can rerun it on a
schedule without spending OpenRouter credits.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Iterable
from urllib.parse import urldefrag, urlsplit, urlunsplit

import httpx

from king_context import PROJECT_ROOT


HTTP_TIMEOUT = 15.0
DEFAULT_CONCURRENCY = 10
THROTTLE_RETRY_CAP_SECONDS = 30


def _scraper_version() -> str:
    try:
        return _pkg_version("king-context")
    except PackageNotFoundError:
        return "dev"


def _canonicalize(url: str) -> str:
    """Drop fragment, lowercase scheme/host, strip trailing slash from path."""
    url, _ = urldefrag(url)
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, "")
    )


@dataclass
class SectionAudit:
    url: str
    title: str
    status: str  # fresh | broken | moved | throttled | auth_required | unreachable | unknown
    final_url: str | None = None
    status_code: int | None = None
    error: str | None = None


@dataclass
class CorpusAudit:
    name: str
    base_url: str
    audited_at: str
    corpus_path: str
    sections: list[SectionAudit] = field(default_factory=list)
    new_urls: list[str] = field(default_factory=list)
    orphan_urls: list[str] = field(default_factory=list)
    discovery_skipped: bool = False
    discovery_error: str | None = None

    def counts(self) -> dict[str, int]:
        out = {
            "fresh": 0,
            "broken": 0,
            "moved": 0,
            "throttled": 0,
            "auth_required": 0,
            "unreachable": 0,
            "unknown": 0,
        }
        for s in self.sections:
            out[s.status] = out.get(s.status, 0) + 1
        return out


def _candidate_corpus_paths(name: str) -> list[Path]:
    """Locations to search for the corpus JSON, in order."""
    return [
        PROJECT_ROOT / ".king-context" / "data" / f"{name}.json",
        PROJECT_ROOT / "data" / f"{name}.json",
    ]


def find_corpus(name: str) -> Path:
    for path in _candidate_corpus_paths(name):
        if path.exists():
            return path
    searched = "\n  ".join(str(p) for p in _candidate_corpus_paths(name))
    raise FileNotFoundError(
        f"Corpus '{name}' not found. Searched:\n  {searched}"
    )


def _load_corpus(corpus_path: Path) -> dict:
    raw = corpus_path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"corpus at {corpus_path} is not valid JSON: {exc}"
        ) from exc


def _unique_section_urls(corpus: dict) -> list[tuple[str, str]]:
    """Return ``[(url, title), ...]`` deduped by canonical URL, preserving first seen order."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for section in corpus.get("sections", []):
        url = section.get("url")
        if not url:
            continue
        canonical = _canonicalize(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append((url, section.get("title", "")))
    return out


def _classify(response: httpx.Response) -> tuple[str, str | None]:
    """Map an httpx response to ``(status, final_url)``.

    Classification is keyed off the *final* status code, not the presence of
    redirects. A chain like ``301 -> 308 -> 404`` is broken, not moved. The
    audit exists to surface that, so reporting it as moved would defeat the
    point. The final URL is still captured for context whenever the chain
    has any redirect history, regardless of the final status.
    """
    final_url = str(response.url) if response.history else None
    code = response.status_code
    if 200 <= code < 300:
        return ("moved" if response.history else "fresh"), final_url
    if code in (401, 403):
        return "auth_required", final_url
    if code == 429:
        return "throttled", final_url
    if code in (404, 410):
        return "broken", final_url
    return "unreachable", final_url


def _retry_after_seconds(response: httpx.Response) -> float:
    """Parse a ``Retry-After`` header into a sleep duration, capped to a sane max.

    The header may be either a delta in seconds (RFC 7231) or an HTTP date.
    Unrecognised values (or a date in the past) fall back to one second so the
    audit always makes forward progress.
    """
    raw = response.headers.get("retry-after")
    if not raw:
        return 1.0
    raw = raw.strip()
    try:
        return min(THROTTLE_RETRY_CAP_SECONDS, max(1.0, float(raw)))
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return 1.0
    if target is None:
        return 1.0
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    delta = (target - datetime.now(timezone.utc)).total_seconds()
    return min(THROTTLE_RETRY_CAP_SECONDS, max(1.0, delta))


async def _check_url(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    url: str,
    title: str,
) -> SectionAudit:
    async with semaphore:
        try:
            response = await client.head(url, follow_redirects=True)
            # Some servers return 405/501 on HEAD; retry as GET.
            if response.status_code in (405, 501):
                response = await client.get(url, follow_redirects=True)
            # 429: respect Retry-After once, then accept the result.
            if response.status_code == 429:
                await asyncio.sleep(_retry_after_seconds(response))
                response = await client.head(url, follow_redirects=True)
                if response.status_code in (405, 501):
                    response = await client.get(url, follow_redirects=True)
            status, final_url = _classify(response)
            return SectionAudit(
                url=url,
                title=title,
                status=status,
                final_url=final_url,
                status_code=response.status_code,
            )
        except httpx.TimeoutException:
            return SectionAudit(
                url=url, title=title, status="unreachable", error="timeout"
            )
        except httpx.RequestError as exc:
            return SectionAudit(
                url=url, title=title, status="unreachable", error=str(exc)
            )


async def _check_section_urls(
    section_urls: list[tuple[str, str]],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> list[SectionAudit]:
    semaphore = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers={"User-Agent": f"king-scrape-audit/{_scraper_version()}"},
    ) as client:
        tasks = [_check_url(client, semaphore, url, title) for url, title in section_urls]
        return list(await asyncio.gather(*tasks))


async def _discover_fresh_urls(base_url: str) -> list[str]:
    # Lazy import so audit doesn't pull in scraper-provider deps when --no-discover.
    from scraper_providers import get_discovery_provider, resolve_provider_name

    provider_name = resolve_provider_name("discover")
    provider = get_discovery_provider(provider_name)
    return list(await provider.discover_urls(base_url))


def _diff_urls(corpus_urls: Iterable[str], fresh_urls: Iterable[str]) -> tuple[list[str], list[str]]:
    """Diff two URL lists by canonical form, returning ``(new, orphan)``.

    Reports surface the *original* form from each side so contributors see what
    they have, not a rewritten version they never indexed.
    """
    corpus_by_canon: dict[str, str] = {}
    for url in corpus_urls:
        corpus_by_canon.setdefault(_canonicalize(url), url)
    fresh_by_canon: dict[str, str] = {}
    for url in fresh_urls:
        fresh_by_canon.setdefault(_canonicalize(url), url)

    new = sorted(fresh_by_canon[c] for c in fresh_by_canon if c not in corpus_by_canon)
    orphan = sorted(corpus_by_canon[c] for c in corpus_by_canon if c not in fresh_by_canon)
    return new, orphan


async def audit_corpus(
    corpus_path: Path,
    *,
    do_discover: bool = True,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> CorpusAudit:
    corpus = _load_corpus(corpus_path)
    section_urls = _unique_section_urls(corpus)
    sections = await _check_section_urls(section_urls, concurrency=concurrency)

    result = CorpusAudit(
        name=corpus.get("name", corpus_path.stem),
        base_url=corpus.get("base_url", ""),
        audited_at=datetime.now(timezone.utc).isoformat(),
        corpus_path=str(corpus_path),
        sections=sections,
    )

    if not do_discover:
        result.discovery_skipped = True
        return result

    if not result.base_url:
        result.discovery_skipped = True
        result.discovery_error = "corpus has no base_url"
        return result

    try:
        fresh = await _discover_fresh_urls(result.base_url)
        result.new_urls, result.orphan_urls = _diff_urls(
            (s.url for s in sections), fresh
        )
    except (httpx.RequestError, RuntimeError, ImportError, OSError) as exc:
        # Narrow catch: provider call may surface any of these. A bug class
        # exception (TypeError, AttributeError, etc.) deliberately propagates
        # so broken code does not masquerade as a "discovery skipped" warning.
        result.discovery_skipped = True
        result.discovery_error = f"{type(exc).__name__}: {exc}"

    return result


def render_report(audit: CorpusAudit) -> str:
    counts = audit.counts()
    lines: list[str] = [
        f"# Audit: {audit.name}",
        "",
        f"- **Audited at:** {audit.audited_at}",
        f"- **Corpus:** `{audit.corpus_path}`",
        f"- **Base URL:** {audit.base_url or '(none)'}",
        f"- **Sections checked:** {len(audit.sections)}",
        "",
        "## Summary",
        "",
        f"- fresh: {counts['fresh']}",
        f"- moved: {counts['moved']}",
        f"- broken: {counts['broken']}",
        f"- throttled: {counts['throttled']}",
        f"- auth_required: {counts['auth_required']}",
        f"- unreachable: {counts['unreachable']}",
    ]
    if audit.discovery_skipped:
        reason = audit.discovery_error or "discovery skipped by flag"
        lines.append(f"- discovery: skipped ({reason})")
    else:
        lines.append(f"- new upstream URLs: {len(audit.new_urls)}")
        lines.append(f"- orphan corpus URLs: {len(audit.orphan_urls)}")

    by_status: dict[str, list[SectionAudit]] = {}
    for section in audit.sections:
        by_status.setdefault(section.status, []).append(section)

    for status in ("broken", "moved", "throttled", "auth_required", "unreachable"):
        items = by_status.get(status, [])
        if not items:
            continue
        lines += ["", f"## {status.replace('_', ' ').capitalize()} ({len(items)})", ""]
        for s in items:
            extras: list[str] = []
            if s.status_code is not None:
                extras.append(f"HTTP {s.status_code}")
            if s.final_url:
                extras.append(f"-> {s.final_url}")
            if s.error:
                extras.append(s.error)
            suffix = f" - {' | '.join(extras)}" if extras else ""
            title = f" - {s.title}" if s.title else ""
            lines.append(f"- [{s.url}]({s.url}){title}{suffix}")

    if not audit.discovery_skipped:
        if audit.new_urls:
            lines += ["", f"## New upstream URLs ({len(audit.new_urls)})", ""]
            for url in audit.new_urls:
                lines.append(f"- {url}")
        if audit.orphan_urls:
            lines += ["", f"## Orphan corpus URLs ({len(audit.orphan_urls)})", ""]
            for url in audit.orphan_urls:
                lines.append(f"- {url}")

    return "\n".join(lines) + "\n"


_SAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename_component(value: str) -> str:
    safe = _SAFE_NAME_CHARS.sub("-", value).strip("-")
    return safe or "audit"


def _report_path(audit: CorpusAudit, report_dir: Path) -> Path:
    """Build the report path. Tolerates a malformed or naive ``audited_at``."""
    try:
        dt = datetime.fromisoformat(audit.audited_at)
        if dt.tzinfo is None:
            # A naive timestamp would crash astimezone(); assume UTC and proceed.
            dt = dt.replace(tzinfo=timezone.utc)
        # Microsecond precision avoids collision when audits run in the same
        # second; trailing Z strips the timezone offset for a shorter name.
        stamp = dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    except ValueError:
        stamp = re.sub(r"[^A-Za-z0-9]", "", audit.audited_at)
    name = _sanitize_filename_component(audit.name)
    return report_dir / f"{name}-{stamp}.md"


def write_report(audit: CorpusAudit, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = _report_path(audit, report_dir)
    path.write_text(render_report(audit), encoding="utf-8")
    return path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="king-scrape audit",
        description="Audit an indexed corpus for broken, moved, throttled, or stale URLs.",
    )
    parser.add_argument("name", help="Doc name (matches data/<name>.json)")
    parser.add_argument(
        "--no-discover",
        action="store_true",
        help="Skip the upstream discover diff (faster, no provider key required).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Max concurrent URL probes (default: {DEFAULT_CONCURRENCY}).",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=PROJECT_ROOT / ".king-context" / "audit",
        help="Where to write the Markdown report.",
    )
    return parser


def _print_summary(audit: CorpusAudit, report_path: Path) -> None:
    counts = audit.counts()
    parts = [
        f"{counts['fresh']} fresh",
        f"{counts['moved']} moved",
        f"{counts['broken']} broken",
    ]
    if counts["throttled"]:
        parts.append(f"{counts['throttled']} throttled")
    if counts["auth_required"]:
        parts.append(f"{counts['auth_required']} auth_required")
    if counts["unreachable"]:
        parts.append(f"{counts['unreachable']} unreachable")
    summary = ", ".join(parts)
    print(f"audit {audit.name}: {summary}", end="")
    if not audit.discovery_skipped:
        print(
            f" | new {len(audit.new_urls)} / orphan {len(audit.orphan_urls)}",
            end="",
        )
    print(f" | report: {report_path}")


def audit_main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    try:
        corpus_path = find_corpus(args.name)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.concurrency < 1:
        print("error: --concurrency must be >= 1", file=sys.stderr)
        return 1

    try:
        audit = asyncio.run(
            audit_corpus(
                corpus_path,
                do_discover=not args.no_discover,
                concurrency=args.concurrency,
            )
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report_path = write_report(audit, args.report_dir)
    _print_summary(audit, report_path)

    counts = audit.counts()
    if counts["broken"] > 0:
        return 2
    return 0
