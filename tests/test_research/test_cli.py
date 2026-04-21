"""Tests for the king-research CLI parser and effort resolution."""

import pytest

from king_context.research.cli import _build_parser, _resolve_effort
from king_context.research.config import EffortLevel
from king_context.research.pipeline import RESEARCH_STEPS


def test_default_effort_is_medium():
    parser = _build_parser()
    args = parser.parse_args(["some topic"])
    assert args.effort_flag is None
    assert _resolve_effort(args) == EffortLevel.MEDIUM


def test_basic_flag_sets_basic():
    parser = _build_parser()
    args = parser.parse_args(["topic", "--basic"])
    assert _resolve_effort(args) == EffortLevel.BASIC


def test_high_flag_sets_high():
    parser = _build_parser()
    args = parser.parse_args(["topic", "--high"])
    assert _resolve_effort(args) == EffortLevel.HIGH


def test_extrahigh_flag_sets_extrahigh():
    parser = _build_parser()
    args = parser.parse_args(["topic", "--extrahigh"])
    assert _resolve_effort(args) == EffortLevel.EXTRAHIGH


def test_effort_flags_are_mutually_exclusive():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["topic", "--basic", "--high"])


def test_stop_after_accepts_valid_step():
    parser = _build_parser()
    args = parser.parse_args(["topic", "--stop-after", "chunk"])
    assert args.stop_after == "chunk"


def test_stop_after_rejects_invalid_step():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["topic", "--stop-after", "bogus"])


def test_step_accepts_valid_step():
    parser = _build_parser()
    for step in RESEARCH_STEPS:
        args = parser.parse_args(["topic", "--step", step])
        assert args.step == step


def test_name_none_by_default():
    parser = _build_parser()
    args = parser.parse_args(["topic"])
    assert args.name is None


def test_name_override():
    parser = _build_parser()
    args = parser.parse_args(["topic", "--name", "custom-slug"])
    assert args.name == "custom-slug"


def test_yes_flag_long_form():
    parser = _build_parser()
    args = parser.parse_args(["topic", "--yes"])
    assert args.yes is True


def test_yes_flag_short_form():
    parser = _build_parser()
    args = parser.parse_args(["topic", "-y"])
    assert args.yes is True


def test_yes_flag_default_false():
    parser = _build_parser()
    args = parser.parse_args(["topic"])
    assert args.yes is False


def test_no_filter_sets_flag():
    parser = _build_parser()
    args = parser.parse_args(["topic", "--no-filter"])
    assert args.no_filter is True


def test_no_auto_index_sets_flag():
    parser = _build_parser()
    args = parser.parse_args(["topic", "--no-auto-index"])
    assert args.no_auto_index is True


def test_force_flag_sets_flag():
    parser = _build_parser()
    args = parser.parse_args(["topic", "--force"])
    assert args.force is True


def test_topic_is_required():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
