FROM node:22-bookworm-slim AS ui
WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN corepack enable && corepack prepare pnpm@11.0.0 --activate && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.14-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --locked --no-dev
COPY LICENSE THIRD_PARTY_NOTICES.md ./
COPY backend/ ./backend/
COPY config/ ./config/
COPY samples/ ./samples/
COPY scripts/install_epubcheck.py ./scripts/install_epubcheck.py
# Official distribution, version and SHA-256 verified by the installer.
RUN .venv/bin/python scripts/install_epubcheck.py
COPY --from=ui /src/frontend/dist ./frontend/dist
ENV DATA_DIR=/app/data EPUBCHECK_JAR=/app/.tools/epubcheck-5.4.0/epubcheck.jar
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD [".venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).close()"]
CMD [".venv/bin/uvicorn","epub_proofreader.app:app","--app-dir","backend","--host","0.0.0.0","--port","8000","--workers","1","--timeout-graceful-shutdown","5"]
