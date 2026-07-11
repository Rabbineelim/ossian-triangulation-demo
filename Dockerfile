# Ossian — container image for any Docker host (Fly.io, Render, Railway, Cloud Run)
FROM python:3.12-slim

# System libs pdfplumber/pandas occasionally need
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ossian ./ossian

# Persistent-ish storage (mount a volume here on your host to keep data)
ENV OSSIAN_STORAGE=/app/storage OSSIAN_REPORTS=/app/reports
RUN mkdir -p /app/storage /app/reports

# Hosts inject $PORT; default to 8000 locally.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn ossian.web.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
