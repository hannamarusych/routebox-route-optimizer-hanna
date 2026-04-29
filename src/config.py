"""Env-driven config. No fancy schema lib; we don't need one."""

import os


def _bool(val: str, default: bool) -> bool:
    if val is None or val == "":
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _int(val: str, default: int) -> int:
    try:
        return int(val) if val not in (None, "") else default
    except (TypeError, ValueError):
        return default


# DATABASE_URL is populated at boot from Secrets Manager
# (routebox/<env>/DATABASE_URL). For local dev the compose file sets it.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgres://routebox:routebox@postgres:5432/routebox",
)

SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AWS_ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL")  # set in dev/test for LocalStack

ENV = os.environ.get("ENV", os.environ.get("NODE_ENV", "development"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").lower()

PORT = _int(os.environ.get("PORT"), 3000)

# Per-process solver wallclock cap. Some enterprise tenants need longer;
# see solver.TENANT_TIME_LIMITS for the hardcoded overrides. Should be in
# the database. Isn't.
SOLVER_TIME_LIMIT_SECONDS = _int(os.environ.get("SOLVER_TIME_LIMIT_SECONDS"), 30)

MAX_CONCURRENT_SOLVES = _int(
    os.environ.get("MAX_CONCURRENT_SOLVES"),
    4 if ENV == "production" else 1,
)

# SQS receive_message tuning. Long-poll because short-poll burns API calls.
SQS_WAIT_SECONDS = _int(os.environ.get("SQS_WAIT_SECONDS"), 20)
SQS_BATCH_SIZE = _int(os.environ.get("SQS_BATCH_SIZE"), 1)
SQS_VISIBILITY_TIMEOUT = _int(os.environ.get("SQS_VISIBILITY_TIMEOUT"), 120)

PG_POOL_MIN = _int(os.environ.get("PG_POOL_MIN"), 1)
PG_POOL_MAX = _int(os.environ.get("PG_POOL_MAX"), 5)

# Whether the consumer loop should block forever. Tests and one-shot
# CLI runs flip this to False.
RUN_FOREVER = _bool(os.environ.get("RUN_FOREVER"), True)
