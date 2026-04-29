"""pytest fixtures.

Spins up Postgres via testcontainers, applies the Flyway migrations from
a sibling clone of routebox-db-migrations, then exposes per-test fixtures
for a clean DB and mocked SQS/SNS via moto. moto runs in-process; for
end-to-end stack-shaped tests a dev would still use docker-compose with
the pinned LocalStack image (per README).
"""

import os
import pathlib
import time

import boto3
import psycopg2
import pytest
from moto import mock_sns, mock_sqs
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

DEFAULT_MIGRATIONS_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "routebox-db-migrations" / "flyway" / "sql"
)


@pytest.fixture(scope="session")
def migrations_dir() -> pathlib.Path:
    p = pathlib.Path(
        os.environ.get("ROUTEBOX_MIGRATIONS_DIR", str(DEFAULT_MIGRATIONS_DIR))
    )
    if not p.is_dir():
        pytest.skip(
            f"migrations dir not found: {p} — set ROUTEBOX_MIGRATIONS_DIR or "
            "clone routebox-db-migrations alongside this repo"
        )
    return p


@pytest.fixture(scope="session")
def pg_url(migrations_dir: pathlib.Path):
    """Start Postgres in a container, apply all migrations, yield DSN."""
    container = (
        DockerContainer("postgres:14")
        .with_env("POSTGRES_USER", "test")
        .with_env("POSTGRES_PASSWORD", "test")
        .with_env("POSTGRES_DB", "routebox_test")
        .with_exposed_ports(5432)
    )
    container.start()
    try:
        wait_for_logs(container, "database system is ready to accept connections")
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        dsn = f"postgres://test:test@{host}:{port}/routebox_test"

        # Postgres logs "ready" before it's actually ready for connections
        # on slower CI; retry the first connect for a few seconds.
        deadline = time.time() + 30
        while True:
            try:
                conn = psycopg2.connect(dsn)
                conn.autocommit = True
                break
            except psycopg2.OperationalError:
                if time.time() > deadline:
                    raise
                time.sleep(0.5)

        files = sorted(
            p for p in migrations_dir.iterdir()
            if p.name.startswith("V") and p.suffix == ".sql"
        )
        try:
            with conn.cursor() as cur:
                for f in files:
                    cur.execute(f.read_text())
        finally:
            conn.close()
        yield dsn
    finally:
        container.stop()


@pytest.fixture
def db_pool(pg_url):
    """Per-test: point the app at the test DB and reset writable tables."""
    os.environ["DATABASE_URL"] = pg_url
    # Make src.config re-read; importable singletons cache it on first call.
    from src import config, db
    config.DATABASE_URL = pg_url
    db.close_pool()

    pool = db.get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE route_calculations, route_optimization_jobs, "
                "shipment_status_history, shipment_events, shipments, "
                "addresses, users, accounts, tenants, legacy_export_runs "
                "RESTART IDENTITY CASCADE"
            )
        conn.commit()
    finally:
        pool.putconn(conn)

    yield pool

    db.close_pool()


@pytest.fixture
def seeded_tenant(db_pool):
    """Insert a tenant + account + a few shipments. Returns ids."""
    pool = db_pool
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (name, slug) VALUES (%s, %s) RETURNING id",
                ("Test Tenant", f"test-{os.getpid()}"),
            )
            tenant_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO accounts (tenant_id, name) VALUES (%s, %s) RETURNING id",
                (tenant_id, "Acct"),
            )
            account_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO addresses (tenant_id, line1, city) "
                "VALUES (%s, %s, %s) RETURNING id",
                (tenant_id, "1 Test Way", "Springfield"),
            )
            origin_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO addresses (tenant_id, line1, city) "
                "VALUES (%s, %s, %s) RETURNING id",
                (tenant_id, "2 Other Rd", "Shelbyville"),
            )
            dest_id = cur.fetchone()[0]

            shipment_ids = []
            for w in (1.0, 2.5, 4.0):
                cur.execute(
                    """INSERT INTO shipments
                        (tenant_id, account_id, origin_address_id,
                         destination_address_id, weight_kg, status)
                       VALUES (%s, %s, %s, %s, %s, 'created')
                       RETURNING id""",
                    (tenant_id, account_id, origin_id, dest_id, w),
                )
                shipment_ids.append(cur.fetchone()[0])
        conn.commit()
    finally:
        pool.putconn(conn)
    return {
        "tenant_id": int(tenant_id),
        "account_id": int(account_id),
        "shipment_ids": [int(x) for x in shipment_ids],
    }


@pytest.fixture
def aws_mock():
    """moto fixture for SQS + SNS. Returns a dict with queue_url + topic_arn."""
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

    with mock_sqs(), mock_sns():
        sqs = boto3.client("sqs", region_name="us-east-1")
        sns = boto3.client("sns", region_name="us-east-1")
        q = sqs.create_queue(QueueName="route-calc-requests")
        t = sns.create_topic(Name="route-calc-completions")

        # Tell src.config + consumer where the mocks are.
        from src import config
        config.SQS_QUEUE_URL = q["QueueUrl"]
        config.SNS_TOPIC_ARN = t["TopicArn"]
        # Long-poll wastes wallclock in tests; short-poll.
        config.SQS_WAIT_SECONDS = 0
        config.SQS_BATCH_SIZE = 5
        config.AWS_ENDPOINT_URL = None  # let boto3 use the moto in-process mock

        yield {
            "queue_url": q["QueueUrl"],
            "topic_arn": t["TopicArn"],
            "sqs": sqs,
            "sns": sns,
        }


@pytest.fixture(autouse=True)
def reset_solver_caches():
    """The solver's module-level caches MUST be cleared between tests
    even though they're a deliberate leak vector — otherwise tests
    interfere with each other in confusing ways."""
    from src import solver
    solver._carrier_route_cache.clear()
    solver._telemetry.clear()
    yield
