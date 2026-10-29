FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    ALIBI_DATA_DIR=/data/ais

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alibi_recorder ./alibi_recorder

# SIGTERM from `docker stop` reaches python directly (exec form) -> clean "stop" in the ledger.
STOPSIGNAL SIGTERM
CMD ["python", "-m", "alibi_recorder"]
