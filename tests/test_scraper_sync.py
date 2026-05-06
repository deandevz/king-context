"""Tests for page-level scraper sync manifests and change detection."""

import json

import pytest

from king_context.scraper.sync import (
    check_for_updates,
    load_page_manifest,
    probe_url_state,
    record_page_state,
)


def test_record_page_state_writes_page_manifest(tmp_path):
    record_page_state(
        tmp_path,
        base_url="https://docs.example.com",
        url="https://docs.example.com/a",
        markdown="# Intro\n\nHello",
        etag='"etag-a"',
        last_modified="Mon, 01 Jan 2026 00:00:00 GMT",
        probe_hash=None,
        content_length=42,
    )

    manifest = json.loads((tmp_path / "page_manifest.json").read_text(encoding="utf-8"))
    assert manifest["base_url"] == "https://docs.example.com"
    assert manifest["page_count"] == 1
    assert "https://docs.example.com/a" in manifest["pages"]


@pytest.mark.asyncio
async def test_check_for_updates_detects_new_removed_changed_and_unchanged(tmp_path):
    record_page_state(
        tmp_path,
        base_url="https://docs.example.com",
        url="https://docs.example.com/a",
        markdown="# A",
        etag='"a1"',
    )
    record_page_state(
        tmp_path,
        base_url="https://docs.example.com",
        url="https://docs.example.com/b",
        markdown="# B",
        etag='"b1"',
    )

    current_urls = [
        "https://docs.example.com/a",
        "https://docs.example.com/c",
    ]

    async def fake_probe(url: str) -> dict:
        if url.endswith("/a"):
            return {"ok": True, "etag": '"a1"', "last_modified": None, "probe_hash": None, "content_length": 10}
        return {"ok": True, "etag": '"c1"', "last_modified": None, "probe_hash": None, "content_length": 10}

    report = await check_for_updates(
        base_url="https://docs.example.com",
        current_urls=current_urls,
        work_dir=tmp_path,
        concurrency=2,
        probe_func=fake_probe,
    )

    assert report.new_urls == ["https://docs.example.com/c"]
    assert report.removed_urls == ["https://docs.example.com/b"]
    assert report.unchanged_urls == ["https://docs.example.com/a"]
    assert report.changed == []
    assert report.unchecked == []


@pytest.mark.asyncio
async def test_check_for_updates_marks_changed_by_body_hash(tmp_path):
    record_page_state(
        tmp_path,
        base_url="https://docs.example.com",
        url="https://docs.example.com/a",
        markdown="# A",
        probe_hash="oldhash",
    )

    async def fake_probe(url: str) -> dict:
        return {"ok": True, "etag": None, "last_modified": None, "probe_hash": "newhash", "content_length": 20}

    report = await check_for_updates(
        base_url="https://docs.example.com",
        current_urls=["https://docs.example.com/a"],
        work_dir=tmp_path,
        probe_func=fake_probe,
    )

    assert len(report.changed) == 1
    assert report.changed[0].url == "https://docs.example.com/a"
    assert report.changed[0].reason == "body_hash_changed"


@pytest.mark.asyncio
async def test_check_for_updates_marks_unchecked_when_probe_fails(tmp_path):
    record_page_state(
        tmp_path,
        base_url="https://docs.example.com",
        url="https://docs.example.com/a",
        markdown="# A",
        etag='"a1"',
    )

    async def fake_probe(url: str) -> dict:
        return {"ok": False, "reason": "timeout"}

    report = await check_for_updates(
        base_url="https://docs.example.com",
        current_urls=["https://docs.example.com/a"],
        work_dir=tmp_path,
        probe_func=fake_probe,
    )

    assert report.new_urls == []
    assert report.removed_urls == []
    assert report.changed == []
    assert report.unchanged_urls == []
    assert len(report.unchecked) == 1
    assert report.unchecked[0].reason == "timeout"


@pytest.mark.asyncio
async def test_probe_url_state_falls_back_to_get_when_head_has_no_useful_metadata():
    class FakeResponse:
        def __init__(self, status_code: int, headers: dict[str, str], text: str = ""):
            self.status_code = status_code
            self.headers = headers
            self.text = text

    class FakeClient:
        def __init__(self):
            self.closed = False

        async def head(self, url: str):
            return FakeResponse(200, {})

        async def get(self, url: str):
            return FakeResponse(200, {}, "Hello world")

        async def aclose(self):
            self.closed = True

    client = FakeClient()
    state = await probe_url_state("https://docs.example.com/a", client=client)

    assert state["ok"] is True
    assert state["probe_hash"] is not None
    assert state["content_length"] == len("Hello world".encode("utf-8"))
    assert client.closed is False


def test_load_page_manifest_returns_empty_when_missing(tmp_path):
    assert load_page_manifest(tmp_path) == {}
