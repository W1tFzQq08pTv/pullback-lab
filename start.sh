#!/bin/sh
set -eu
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo '请先安装 uv'; exit 1; }
command -v npm >/dev/null || { echo '请先安装 Node.js'; exit 1; }
[ -x .venv/bin/python ] || uv sync --frozen
[ -d web/node_modules ] || npm --prefix web ci
exec .venv/bin/python scripts/dev.py
