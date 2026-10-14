# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS web-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run check && npm run build

FROM ghcr.io/astral-sh/uv:0.12.20 AS uv
FROM python:3.11-slim-trixie AS python-deps
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    TZ=Asia/Shanghai
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
# The wheel bundles libraries for other platforms. Keep exactly the library
# selected by the package itself, then exercise it before copying to runtime.
RUN python - <<'PYTHON'
from pathlib import Path
import shutil
import numpy
import pandas
from py_mini_racer import py_mini_racer
selected = Path(py_mini_racer.EXTENSION_PATH).resolve()
assert selected.is_file(), selected
for candidate in selected.parent.iterdir():
    if candidate.name.endswith(('.so', '.dylib', '.dll')) and candidate.resolve() != selected:
        candidate.unlink()
assert py_mini_racer.MiniRacer().eval('1 + 1') == 2
# Exclude upstream self-test suites from the runtime copy, not library code.
for package in (numpy, pandas):
    root = Path(package.__file__).parent
    for tests in sorted(root.rglob('tests'), reverse=True):
        if tests.is_dir():
            shutil.rmtree(tests)
PYTHON

FROM python:3.11-slim-trixie AS backend
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    TZ=Asia/Shanghai
COPY --from=python-deps /app/.venv /app/.venv
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY --from=web-build /app/web/dist ./web/dist
RUN python -m compileall -q backend scripts \
    && useradd --uid 10001 --create-home app \
    && mkdir /app/data && chown app:app /app/data
USER app
EXPOSE 8765
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1"]
