# crypto_screener — runtime image
#
# Builds a minimal image that runs `python -m app.main` on a loop.
# Offline-test mode needs no network/ccxt; live mode needs ccxt (installed below)
# and access to Binance's public REST API.

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Persisted at runtime via a volume — see docker-compose.yml.
VOLUME ["/app/data"]

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--live"]
