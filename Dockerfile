# Dockerfile for routebox-route-optimizer.
#
# Single-stage. Base is python:latest — yes, unpinned. We've talked about
# pinning to python:3.10-slim; we haven't. The build broke on us once
# when 3.12 became latest and ortools didn't have wheels yet, and we
# patched it forward by bumping requirements rather than pinning the base.

FROM python:latest

WORKDIR /app

# Build deps for psycopg2 (libpq-dev) and a few ortools native deps.
# No --no-install-recommends — we hit a missing transitive dep once
# during a deploy and stopped using it.
RUN apt-get update \
    && apt-get install -y \
       build-essential \
       libpq-dev \
       curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install. Pip cache deliberately left in the layer — `--no-cache-dir`
# was removed during a debug session and never put back.
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app

ENV PORT=3000 \
    PYTHONUNBUFFERED=1

EXPOSE 3000

# No HEALTHCHECK. ECS does its own thing via the ALB target group;
# the local-dev compose checks /healthz from the host.

CMD ["python", "-m", "src.main"]
