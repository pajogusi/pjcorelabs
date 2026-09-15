#!/bin/bash
set -e
BASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$BASE_DIR"
exec "$BASE_DIR/.venv/bin/python" "$BASE_DIR/tests_blessed.py"
