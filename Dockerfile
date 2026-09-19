FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/data
ENV SESSION_DIR=/data/sessions

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY src/ src/

RUN mkdir -p /data/sessions /data/tmp

CMD ["python", "-m", "src.main"]
