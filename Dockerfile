FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SORTSMART_CONFIG=/config/rules.yaml
WORKDIR /app

COPY pyproject.toml README.md ./
COPY sortsmart ./sortsmart
RUN pip install --no-cache-dir ".[pdf]" \
    && useradd --create-home --uid 1000 sortsmart \
    && mkdir -p /data /config && chown -R sortsmart /data /config

COPY docker/rules.yaml /config/rules.yaml
USER sortsmart
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s CMD sortsmart health

# Watches /data/inbox and sorts into /data/sorted
# docker run -d -v $PWD/data:/data sortsmart
CMD ["sortsmart", "watch"]
