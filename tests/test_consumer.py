"""Integration tests: real Postgres (testcontainers) + mocked SQS/SNS (moto)."""

import json

from src import consumer


def _send(sqs, queue_url, body):
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))


def test_poll_once_with_no_messages_returns_zero(seeded_tenant, aws_mock):
    n = consumer.poll_once(aws_mock["sqs"], aws_mock["sns"])
    assert n == 0


def test_full_solve_writes_route_calculation(seeded_tenant, aws_mock, db_pool):
    _send(aws_mock["sqs"], aws_mock["queue_url"], {
        "tenant_id":   seeded_tenant["tenant_id"],
        "account_id":  seeded_tenant["account_id"],
        "shipment_ids": seeded_tenant["shipment_ids"],
    })

    handled = consumer.poll_once(aws_mock["sqs"], aws_mock["sns"])
    assert handled == 1

    pool = db_pool
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*)::int FROM route_calculations "
                "WHERE tenant_id = %s",
                (seeded_tenant["tenant_id"],),
            )
            assert cur.fetchone()[0] == 1

            cur.execute(
                "SELECT status, route_calculation_id "
                "FROM route_optimization_jobs",
            )
            row = cur.fetchone()
            assert row[0] == "completed"
            assert row[1] is not None
    finally:
        pool.putconn(conn)

    # Message was acked — re-poll should see nothing.
    n = consumer.poll_once(aws_mock["sqs"], aws_mock["sns"])
    assert n == 0


def test_undecodable_message_is_dropped(seeded_tenant, aws_mock, db_pool):
    aws_mock["sqs"].send_message(
        QueueUrl=aws_mock["queue_url"],
        MessageBody="not valid json {{{",
    )
    n = consumer.poll_once(aws_mock["sqs"], aws_mock["sns"])
    assert n == 0  # dropped, didn't count as handled

    # No row should have been written.
    pool = db_pool
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*)::int FROM route_calculations")
            assert cur.fetchone()[0] == 0
    finally:
        pool.putconn(conn)
