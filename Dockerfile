FROM python:3.14-slim

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

# Don't bake uv's download cache into the image (it was ~536 MB).
ENV UV_NO_CACHE=1

WORKDIR /app

# Copy only the files needed for dependency resolution/install
COPY pyproject.toml uv.lock ./

# Install ONLY dependencies (skip project install → no build attempt).
# uv (pinned to match CI and developers) is bind-mounted from its official
# image for this step only, so it never ships in the runtime image; the
# app doesn't need it, and the binary's bundled Rust crates carry their
# own CVEs.
RUN --mount=from=ghcr.io/astral-sh/uv:0.10.9,source=/uv,target=/bin/uv \
    uv sync --no-dev --no-install-project --no-editable --frozen

# Now copy the full source code
COPY . .

EXPOSE 8000

# Run the venv's uvicorn directly: `uv run` would re-sync (and could
# download) at container start. uvicorn puts the working directory on
# sys.path, so the package is importable from /app.
CMD [".venv/bin/uvicorn", "ai_bi_analytics.main:app", "--host", "0.0.0.0", "--port", "8000"]
