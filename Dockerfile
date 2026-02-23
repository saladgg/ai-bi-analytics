FROM python:3.14-slim

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy only the files needed for dependency resolution/install
COPY pyproject.toml uv.lock* ./

# Install ONLY dependencies (skip project install → no build attempt)
RUN uv sync --no-dev --no-install-project --no-editable --frozen

# Now copy the full source code
COPY . .

# Optional: If you want to "install" the project non-editably now that code is present
# (usually not needed for FastAPI apps — uv run will find app.main via PYTHONPATH implicitly)
# RUN uv pip install --no-deps --no-build .

EXPOSE 8000

# uv run ensures it uses the project's venv and finds app/ on path
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]