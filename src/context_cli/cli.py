"""CLI entry point for kctx."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kctx",
        description="File-based documentation search for AI agents",
    )
    parser.add_argument(
        "--version", action="version", version="kctx 0.1.0"
    )
    # Subcommands will be added in T7
    parser.parse_args()
    parser.print_help()


if __name__ == "__main__":
    main()
