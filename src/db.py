"""Postgres access. psycopg2 ThreadedConnectionPool, real SQL.

Schema definitions live in routebox-db-migrations. Column names tracked
forward from V001 baseline. We write to route_calculations and
route_optimization_jobs; we read shipments, addresses, accounts.
"""

import json
import logging
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

from . import config

log = logging.getLogger(__name__)

# Initialized lazily so tests can override DATABASE_URL before first use.
_pool: pg_pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> pg_pool.ThreadedConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            _pool = pg_pool.ThreadedConnectionPool(
                config.PG_POOL_MIN,
                config.PG_POOL_MAX,
                dsn=config.DATABASE_URL,
            )
            log.info("pg pool initialized (min=%s max=%s)",
                     config.PG_POOL_MIN, config.PG_POOL_MAX)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def cursor(dict_rows: bool = True):
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur_factory = psycopg2.extras.RealDictCursor if dict_rows else None
        with conn.cursor(cursor_factory=cur_factory) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def fetch_inputs(tenant_id: int, shipment_ids: list[int]) -> dict:
    """Pull the inputs the solver needs.

    Returns a dict with shipments + addresses keyed by id. We collapse
    the joins to dicts here rather than passing rows directly to the
    solver so the solver doesn't need to know about Postgres.
    """
    if not shipment_ids:
        return {"shipments": [], "addresses": {}, "tenant_id": tenant_id}

    with cursor() as cur:
        cur.execute(
            """
            SELECT
                s.id, s.tenant_id, s.account_id,
                s.weight_kg, s.status,
                s.origin_address_id, s.destination_address_id,
                s.expected_delivery_at,
                s.metadata
            FROM shipments s
            WHERE s.tenant_id = %s
              AND s.id = ANY(%s::bigint[])
            """,
            (tenant_id, shipment_ids),
        )
        shipments = [dict(r) for r in cur.fetchall()]

        addr_ids = set()
        for s in shipments:
            if s["origin_address_id"]:
                addr_ids.add(s["origin_address_id"])
            if s["destination_address_id"]:
                addr_ids.add(s["destination_address_id"])

        addresses: dict[int, dict] = {}
        if addr_ids:
            cur.execute(
                """
                SELECT id, line1, line2, city, region, postal_code, country
                FROM addresses
                WHERE id = ANY(%s::bigint[])
                """,
                (list(addr_ids),),
            )
            for r in cur.fetchall():
                addresses[r["id"]] = dict(r)

    return {
        "shipments": shipments,
        "addresses": addresses,
        "tenant_id": tenant_id,
    }


def claim_job(sqs_message_id: str, tenant_id: int, shipment_ids: list[int]) -> int:
    """Insert (or upsert) a route_optimization_jobs row, return its id."""
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO route_optimization_jobs
                (sqs_message_id, shipment_ids, status, started_at)
            VALUES (%s, %s::bigint[], 'started', NOW())
            RETURNING id
            """,
            (sqs_message_id, shipment_ids),
        )
        row = cur.fetchone()
        return row["id"]


def write_result(
    tenant_id: int,
    account_id: int | None,
    shipment_ids: list[int],
    result: dict,
    solver_version: str,
    duration_ms: int,
    job_id: int | None,
) -> int:
    """Insert into route_calculations and link/finalize the job row."""
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO route_calculations
                (tenant_id, account_id, shipment_ids, result,
                 solver_version, duration_ms)
            VALUES (%s, %s, %s::bigint[], %s::jsonb, %s, %s)
            RETURNING id
            """,
            (
                tenant_id,
                account_id,
                shipment_ids,
                json.dumps(result),
                solver_version,
                duration_ms,
            ),
        )
        row = cur.fetchone()
        calc_id = row["id"]

        if job_id is not None:
            cur.execute(
                """
                UPDATE route_optimization_jobs SET
                    status = 'completed',
                    completed_at = NOW(),
                    route_calculation_id = %s
                WHERE id = %s
                """,
                (calc_id, job_id),
            )

    return calc_id


def mark_job_failed(job_id: int | None, err: str) -> None:
    if job_id is None:
        return
    try:
        with cursor() as cur:
            cur.execute(
                """
                UPDATE route_optimization_jobs SET
                    status = 'failed',
                    completed_at = NOW(),
                    error = %s
                WHERE id = %s
                """,
                (err[:1000], job_id),
            )
    except Exception:  # noqa: BLE001
        log.exception("mark_job_failed: secondary error")


def ping() -> bool:
    """Used by /healthz to confirm the pool can reach Postgres."""
    try:
        with cursor(dict_rows=False) as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
            return bool(row and row[0] == 1)
    except Exception:  # noqa: BLE001
        return False
