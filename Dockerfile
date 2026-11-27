# Base pinned by digest (audit OPS-4): rebuilds are reproducible, and a
# retagged upstream image can't change what ships. Dependabot's docker
# ecosystem bumps the tag and digest together.
FROM python:3.14-slim@sha256:22eafb370920ad8b429e0aec3fff433e0669968519f5d60469d83729c138b28b

# Debian security fixes released after the base image was built (Trivy
# flagged e.g. libzstd1). CI passes today's date so a cached layer can't
# pin stale packages forever.
ARG APT_CACHE_BUST=unset
RUN echo "apt cache bust: ${APT_CACHE_BUST}" \
    && apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# The app runs from its own venv; the base image's pip is unused, and its
# vendored libraries (msgpack, urllib3) carried known CVEs.
RUN python -m pip uninstall -y pip

# Unprivileged runtime user (audit OPS-4). Fixed uid/gid so volume
# permissions and Kubernetes `runAsUser` policies can rely on them.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

# Don't bake uv's download cache into the image (it was ~536 MB).
ENV UV_NO_CACHE=1

WORKDIR /app

# Copy only the files needed for dependency resolution/install
COPY pyproject.toml uv.lock ./

# Install ONLY the API's runtime dependencies: no dev tools, and not the
# Streamlit demo's `frontend` group. uv (pinned by digest, matching CI) is
# bind-mounted from its official image for this step only, so it never
# ships; the app doesn't need it, and the binary's bundled Rust crates
# carry their own CVEs.
RUN --mount=from=ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82,source=/uv,target=/bin/uv \
    uv sync --no-dev --no-install-project --no-editable --frozen

# Now copy the full source code (root-owned, read-only to the app user)
COPY . .

# Install the project itself (non-editable) so its package metadata exists:
# the app reads its version from it (FastAPI docs, OTel service.version).
RUN --mount=from=ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82,source=/uv,target=/bin/uv \
    uv sync --no-dev --no-editable --frozen

USER app

EXPOSE 8000

# Liveness only (audit OPS-3): Docker marks the container unhealthy when
# the process stops serving. Dependency readiness is /api/health/ready,
# for load balancers. Uses the image's Python; slim has no curl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --start-interval=2s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=4)"]

# Run the venv's uvicorn directly: `uv run` would re-sync (and could
# download) at container start. uvicorn puts the working directory on
# sys.path, so the package is importable from /app.
# - --proxy-headers: client address from X-Forwarded-For, trusted only
#   from FORWARDED_ALLOW_IPS (default 127.0.0.1); the rate limiter relies
#   on it.
# - --timeout-graceful-shutdown: on SIGTERM, finish in-flight requests
#   (an LLM round trip can take seconds) before the lifespan cleanup.
# - Workers: uvicorn reads WEB_CONCURRENCY (default 1). Prefer one worker
#   per container and scale by adding containers.
CMD [".venv/bin/uvicorn", "ai_bi_analytics.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-graceful-shutdown", "20"]
