import argparse
import asyncio
import logging

from king_context.research.config import EffortLevel, load_research_config
from king_context.research.pipeline import RESEARCH_STEPS, run_pipeline
from king_context.scraper.config import ConfigError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="king-research",
        description="Research a topic and index sources into .king-context/data/research/",
    )
    parser.add_argument("topic", help="Research topic (quote multi-word topics)")

    effort = parser.add_mutually_exclusive_group()
    effort.add_argument(
        "--basic",
        dest="effort_flag",
        action="store_const",
        const=EffortLevel.BASIC,
        help="Basic effort: fewer queries, no deepening iterations",
    )
    effort.add_argument(
        "--medium",
        dest="effort_flag",
        action="store_const",
        const=EffortLevel.MEDIUM,
        help="Medium effort (default)",
    )
    effort.add_argument(
        "--high",
        dest="effort_flag",
        action="store_const",
        const=EffortLevel.HIGH,
        help="High effort: more queries and deepening iterations",
    )
    effort.add_argument(
        "--extrahigh",
        dest="effort_flag",
        action="store_const",
        const=EffortLevel.EXTRAHIGH,
        help="Extra-high effort: maximum queries and iterations",
    )

    parser.add_argument(
        "--name",
        default=None,
        help="Slug override for the output JSON (default: derived from topic)",
    )
    parser.add_argument(
        "--step",
        choices=RESEARCH_STEPS,
        default=None,
        help="Start the pipeline from this step (P1: no rehydration)",
    )
    parser.add_argument(
        "--stop-after",
        dest="stop_after",
        choices=RESEARCH_STEPS,
        default=None,
        help="Run up to and including this step, then stop",
    )
    parser.add_argument(
        "--no-filter",
        dest="no_filter",
        action="store_true",
        help="Skip relevance filter (P1: filter is not implemented — this is a no-op)",
    )
    parser.add_argument(
        "--yes",
        "-y",
        dest="yes",
        action="store_true",
        help="Skip the enrichment cost prompt",
    )
    parser.add_argument(
        "--no-auto-index",
        dest="no_auto_index",
        action="store_true",
        help="Do not run auto_index after export",
    )
    parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        help="(P3) Skip URL dedup — currently a no-op",
    )
    return parser


def _resolve_effort(args: argparse.Namespace) -> EffortLevel:
    return args.effort_flag if args.effort_flag is not None else EffortLevel.MEDIUM


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args()

    args.effort = _resolve_effort(args)

    if args.no_filter:
        logging.getLogger("king_context.research.cli").info(
            "--no-filter accepted (filter is not implemented in P1)"
        )

    try:
        config = load_research_config()
        asyncio.run(run_pipeline(args, config))
    except ConfigError as exc:
        parser.error(str(exc))
