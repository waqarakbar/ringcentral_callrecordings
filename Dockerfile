# Use a standard Python slim image
FROM python:3.10-slim

# 1. Install uv (The fastest way: copy the binary from the official image)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set working directory
WORKDIR /app

# 2. Copy dependency files first (for Docker layer caching)
# We assume you have pyproject.toml and uv.lock.
COPY pyproject.toml uv.lock ./

# 3. Install dependencies into the system environment
# --system: Installs into /usr/local (no virtualenv needed inside container)
# --deploy: Enforces that uv.lock is up to date
RUN uv sync --locked

# 4. Copy the rest of your application code
COPY . .

# 5. Define the entrypoint
ENTRYPOINT ["uv", "run", "main.py"]