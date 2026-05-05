import pytest

from llm_providers.base import ProviderError
from llm_providers.parser import parse_json_object


def test_parse_clean_object():
    assert parse_json_object('{"ok": true}') == {"ok": True}


def test_parse_existing_dict():
    assert parse_json_object({"ok": True}) == {"ok": True}


def test_parse_fenced_object():
    assert parse_json_object('```json\n{"ok": true}\n```') == {"ok": True}


def test_parse_prose_wrapped_object():
    assert parse_json_object('Here is it:\n{"ok": true}\nthanks') == {"ok": True}


def test_parse_repairs_trailing_commas():
    assert parse_json_object('{"items": [1, 2,], "ok": true,}') == {
        "items": [1, 2],
        "ok": True,
    }


def test_parse_malformed_raises_provider_error():
    with pytest.raises(ProviderError) as exc:
        parse_json_object("not json {")

    assert exc.value.reason == "invalid_response"
