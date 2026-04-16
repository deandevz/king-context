#!/bin/bash
SCRIPT_DIR="$(cd "${0%/*}" && pwd)"
exec "$SCRIPT_DIR/../core/venv/bin/king-scrape" "$@"
