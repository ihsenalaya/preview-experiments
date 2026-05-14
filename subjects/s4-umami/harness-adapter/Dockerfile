FROM ghcr.io/umami-software/umami:postgresql-v2.15.1 AS umami-app

FROM python:3.12-slim

# Node.js runtime required to start Next.js
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy the built Next.js application
COPY --from=umami-app /app /umamiapp
COPY --from=umami-app /usr/local/lib/node_modules /usr/local/lib/node_modules 2>/dev/null || true

# Python test dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Test scripts (contract: /app/tests/)
COPY tests/ /app/tests/
COPY wrapper.py /wrapper.py

EXPOSE 3000
CMD ["python3", "/wrapper.py"]
