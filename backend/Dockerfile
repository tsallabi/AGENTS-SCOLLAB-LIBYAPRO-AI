FROM python:3.11-slim AS base

# System deps for psycopg, building wheels, and Node.js for code execution sandbox
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir aiosqlite gunicorn

# App code
COPY app ./app
COPY migrations ./migrations
COPY tests ./tests

# Frontend bundled by docker-compose mount or COPY
RUN mkdir -p /app/uploads

EXPOSE 8000

# Use uvicorn directly (FastAPI). For higher concurrency add --workers N.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
