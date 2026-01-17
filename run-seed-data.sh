#!/bin/bash
cd "$(dirname "$0")"
rm -f docs.db
python seed_data.py
