FROM python:3.12-slim

WORKDIR /app

# No system deps needed: sqlite3 is in the stdlib, edge-tts is pure Python + aiohttp.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data

# Data (SQLite + cached audio) lives in /app/data — mount a volume over it.
VOLUME ["/app/data"]

ENV DATA_DIR=/app/data
ENV PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
