#!/bin/bash
cd "$(dirname "$0")/.."
rm -f docs.db
python -m king_context.seed_data
