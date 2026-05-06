"""Page-level sync metadata and change detection for scraped documentation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx


PAGE_MANIFEST_FILE = "page_manifest.json"
SYNC_REPORT_FILE = "sync_report.json"


@dataclass
class PageState:
    url: str
    slug: str
    fetched_at: str
    markdown_hash: str
    etag: str | None
    last_modified: str | None
    probe_hash: str | None
    content_length: int | None


@dataclass
class SyncFinding:
    url: str
    reason: str


@dataclass
class SyncReport:
    base_url: str
    checked_at: str
    total_current_urls: int
    total_known_urls: int
    new_urls: list[str]
    removed_urls: list[str]
    changed: list[SyncFinding]
    unchanged_urls: list[str]
    unchecked: list[SyncFinding]

    def to_dict(self) -> dict:
        return {
            "base_url": self.base_url,
            "checked_at": self.checked_at,
            "total_current_urls": self.total_current_urls,
            "total_known_urls": self.total_known_urls,
            "summary": {
                "new": len(self.new_urls),
                "removed": len(self.removed_urls),
                "changed": len(self.changed),
                "unchanged": len(self.unchanged_urls),
                "unchecked": len(self.unchecked),
            },
            "new_urls": self.new_urls,
            "removed_urls": self.removed_urls,
            "changed": [asdict(item) for item in self.changed],
            "unchanged_urls": self.unchanged_urls,
            "unchecked": [asdict(item) for item in self.unchecked],
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _url_to_slug(url: str) -> str:
    slug = re.sub(r"^https?://", "", url)
    slug = re.sub(r"[^a-zA-Z0-9]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:200]


def _normalize_body(text: str) -> str:
    return " ".join(text.split())


def _page_manifest_path(work_dir: Path) -> Path:
    return work_dir / PAGE_MANIFEST_FILE


def _sync_report_path(work_dir: Path) -> Path:
    return work_dir / SYNC_REPORT_FILE


def load_page_manifest(work_dir: Path) -> dict[str, dict]:
    manifest_path = _page_manifest_path(work_dir)
    if not manifest_path.exists():
        return {}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data.get("pages", {})


def save_page_manifest(work_dir: Path, pages: dict[str, dict], *, base_url: str | None = None) -> None:
    payload = {
        "base_url": base_url or "",
        "updated_at": _utc_now(),
        "page_count": len(pages),
        "pages": pages,
    }
    _page_manifest_path(work_dir).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def record_page_state(
    work_dir: Path,
    *,
    base_url: str,
    url: str,
    markdown: str,
    etag: str | None = None,
    last_modified: str | None = None,
    probe_hash: str | None = None,
    content_length: int | None = None,
) -> None:
    pages = load_page_manifest(work_dir)
    page = PageState(
        url=url,
        slug=_url_to_slug(url),
        fetched_at=_utc_now(),
        markdown_hash=_hash_text(markdown),
        etag=etag,
        last_modified=last_modified,
        probe_hash=probe_hash,
        content_length=content_length,
    )
    pages[url] = asdict(page)
    save_page_manifest(work_dir, pages, base_url=base_url)


async def probe_url_state(url: str, client: httpx.AsyncClient | None = None) -> dict:
    owns_client = client is None
    http = client or httpx.AsyncClient(follow_redirects=True, timeout=10.0)

    try:
        head = await http.head(url)
        if head.status_code >= 400:
            get_resp = await http.get(url)
            if get_resp.status_code >= 400:
                return {
                    "ok": False,
                    "status_code": get_resp.status_code,
                    "reason": f"http_{get_resp.status_code}",
                }
            return {
                "ok": True,
                "status_code": get_resp.status_code,
                "etag": get_resp.headers.get("etag"),
                "last_modified": get_resp.headers.get("last-modified"),
                "probe_hash": _hash_text(_normalize_body(get_resp.text)),
                "content_length": len(get_resp.text.encode("utf-8")),
            }
        etag = head.headers.get("etag")
        last_modified = head.headers.get("last-modified")
        content_length_raw = head.headers.get("content-length")
        content_length = int(content_length_raw) if content_length_raw and content_length_raw.isdigit() else None

        probe_hash = None
        if not etag and not last_modified:
            get_resp = await http.get(url)
            if get_resp.status_code >= 400:
                return {
                    "ok": False,
                    "status_code": get_resp.status_code,
                    "reason": f"http_{get_resp.status_code}",
                }
            probe_hash = _hash_text(_normalize_body(get_resp.text))
            content_length = content_length or len(get_resp.text.encode("utf-8"))

        return {
            "ok": head.status_code < 400,
            "status_code": head.status_code,
            "etag": etag,
            "last_modified": last_modified,
            "probe_hash": probe_hash,
            "content_length": content_length,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "reason": str(exc),
        }
    finally:
        if owns_client:
            await http.aclose()


def _compare_page_state(previous: dict, current: dict) -> tuple[str, str]:
    prev_etag = previous.get("etag")
    prev_last_modified = previous.get("last_modified")
    prev_probe_hash = previous.get("probe_hash")

    curr_etag = current.get("etag")
    curr_last_modified = current.get("last_modified")
    curr_probe_hash = current.get("probe_hash")

    if prev_etag and curr_etag:
        return ("changed", "etag_changed") if prev_etag != curr_etag else ("unchanged", "etag_same")
    if prev_last_modified and curr_last_modified:
        return (
            ("changed", "last_modified_changed")
            if prev_last_modified != curr_last_modified
            else ("unchanged", "last_modified_same")
        )
    if prev_probe_hash and curr_probe_hash:
        return (
            ("changed", "body_hash_changed")
            if prev_probe_hash != curr_probe_hash
            else ("unchanged", "body_hash_same")
        )
    return "unchecked", "missing_comparable_state"


async def check_for_updates(
    *,
    base_url: str,
    current_urls: list[str],
    work_dir: Path,
    concurrency: int = 5,
    probe_func=probe_url_state,
) -> SyncReport:
    known_pages = load_page_manifest(work_dir)
    current_set = set(current_urls)
    known_set = set(known_pages.keys())

    new_urls = sorted(current_set - known_set)
    removed_urls = sorted(known_set - current_set)

    changed: list[SyncFinding] = []
    unchanged_urls: list[str] = []
    unchecked: list[SyncFinding] = []

    semaphore = asyncio.Semaphore(concurrency)

    async def _probe(url: str) -> tuple[str, dict]:
        async with semaphore:
            return url, await probe_func(url)

    existing_urls = sorted(current_set & known_set)
    probe_results = await asyncio.gather(*[_probe(url) for url in existing_urls])

    refreshed_pages = dict(known_pages)

    for url, current_state in probe_results:
        if not current_state.get("ok"):
            unchecked.append(SyncFinding(url=url, reason=current_state.get("reason", "probe_failed")))
            continue

        previous = known_pages[url]
        status, reason = _compare_page_state(previous, current_state)
        if status == "changed":
            changed.append(SyncFinding(url=url, reason=reason))
        elif status == "unchanged":
            unchanged_urls.append(url)
        else:
            unchecked.append(SyncFinding(url=url, reason=reason))

        refreshed_pages[url] = {
            **previous,
            "etag": current_state.get("etag"),
            "last_modified": current_state.get("last_modified"),
            "probe_hash": current_state.get("probe_hash"),
            "content_length": current_state.get("content_length"),
        }

    save_page_manifest(work_dir, refreshed_pages, base_url=base_url)

    report = SyncReport(
        base_url=base_url,
        checked_at=_utc_now(),
        total_current_urls=len(current_urls),
        total_known_urls=len(known_pages),
        new_urls=new_urls,
        removed_urls=removed_urls,
        changed=changed,
        unchanged_urls=unchanged_urls,
        unchecked=unchecked,
    )
    _sync_report_path(work_dir).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report
