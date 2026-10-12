#!/bin/sh
set -eu
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo '请先安装 uv'; exit 1; }
command -v npm >/dev/null || { echo '请先安装 Node.js'; exit 1; }
[ -x .venv/bin/python ] || uv sync --frozen
[ -d web/node_modules ] || npm --prefix web ci
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765 &
backend_pid=$!
cleanup() { kill "$backend_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
npm --prefix web run dev
