# Turnkey Matchmaker backend (FastAPI + LangChain Deep Agents). All LLM calls go through the Codex CLI,
# authenticated with the host user's Codex login (~/.codex mounted at runtime by docker-compose).

# --- Codex CLI (Linux build of the same CLI the desktop app bundles; native binary for the build arch)
FROM node:20-slim AS codex
ARG CODEX_VERSION=0.169.0
RUN npm install -g @openai/codex@${CODEX_VERSION} && codex --version

# --- App
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_PATH=/data/turnkey.db \
    CODEX_HOME=/codex-home

# Node runtime + Codex package from the build stage (codex.js launches the native binary).
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules/@openai/codex /opt/codex
RUN ln -s /opt/codex/bin/codex.js /usr/local/bin/codex && codex --version

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# SQLite database (analyses, cached places) lives on a volume so it survives rebuilds.
RUN mkdir -p /data /codex-home && useradd --create-home appuser && chown -R appuser /app /data /codex-home
USER appuser
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/business-types', timeout=4)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
