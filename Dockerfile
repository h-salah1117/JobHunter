# ── JobHunter — Hugging Face Spaces Dockerfile ──────────────────────────────
# Base image: Python 3.11 slim for a small footprint
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (layer caching — only re-installs on change)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

# Create data directory so SQLite + ChromaDB can write on first run
RUN mkdir -p data/chroma_db models

# HuggingFace Spaces runs as non-root user (UID 1000)
RUN useradd -m -u 1000 user
RUN chown -R user:user /app
USER user

# Expose Flask port (HF Spaces maps this automatically for Docker spaces)
EXPOSE 7860

# Environment defaults — override via HF Space Secrets
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_ENV=production \
    SCRAPER_MODE=production \
    REFRESH_HOURS=6 \
    PORT=7860

# Start Flask (run.py reads PORT from env if set)
CMD ["python", "run.py"]
