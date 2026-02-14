FROM python:3.14-slim

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy only dependency files first (better caching)
COPY pyproject.toml ./

# Install dependencies
RUN uv sync --no-dev

# Copy source code
COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
