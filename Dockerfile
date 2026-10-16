# Production Dockerfile for TraceSpot
# Uses lightweight Python 3.11 with CPU-only PyTorch to minimize image size and RAM usage.

FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HF_HOME=/tmp/hf_cache

WORKDIR /app

# Install system dependencies (build-essential, curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first (drastically reduces image size from ~4GB to ~700MB)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch transformers --index-url https://download.pytorch.org/whl/cpu

# Copy requirements and install remaining dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose port (default 8000, overridable by hosting provider via $PORT)
EXPOSE 8000

# Healthcheck to verify FastAPI is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/ || exit 1

# Start Uvicorn using the environment PORT
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
