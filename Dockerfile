# ============================================================
# qr-system Dockerfile
# ?????????? - Python 3.12 + Gunicorn
# ============================================================
FROM python:3.12-slim

LABEL maintainer="qr-system"
LABEL description="QR Code Production Reporting System"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -s /bin/bash appuser

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY --chown=appuser:appuser . .

# Create data and logs directories
RUN mkdir -p /app/data /app/logs && \
    chown -R appuser:appuser /app/data /app/logs

# Generate self-signed cert if not exists
RUN if [ ! -f server.crt ]; then \
        openssl req -x509 -newkey rsa:2048 -keyout server.key \
        -out server.crt -days 3650 -nodes \
        -subj "/C=CN/ST=GD/L=SZ/O=QR-System/CN=localhost"; \
    fi

USER appuser

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('https://127.0.0.1:3000/api/health')" || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "server:app"]
