"""SQS poll loop. The boring outer loop; solver does the work."""

import json
import logging
import threading
import time

import boto3
from botocore.config import Config as BotoConfig

from . import config, db, solver

log = logging.getLogger(__name__)

# Module-level. The main thread sets this False on SIGTERM; the loop
# checks between iterations. boto3 receive_message blocks for SQS
# WaitTimeSeconds; on SIGTERM we accept up to that much delay before
# the loop notices.
_running = threading.Event()
_running.set()


def stop() -> None:
    _running.clear()


def is_running() -> bool:
    return _running.is_set()


def _aws_kwargs() -> dict:
    kwargs: dict = {"region_name": config.AWS_REGION}
    if config.AWS_ENDPOINT_URL:
        kwargs["endpoint_url"] = config.AWS_ENDPOINT_URL
    return kwargs


def _sqs_client():
    return boto3.client(
        "sqs",
        config=BotoConfig(retries={"max_attempts": 5, "mode": "standard"}),
        **_aws_kwargs(),
    )


def _sns_client():
    return boto3.client("sns", **_aws_kwargs())


def run_loop() -> None:
    """Long-running consumer loop. Returns when stop() is called."""
    if not config.SQS_QUEUE_URL:
        log.warning("SQS_QUEUE_URL not set — consumer will idle")
        while is_running():
            time.sleep(1)
        return

    sqs = _sqs_client()
    sns = _sns_client() if config.SNS_TOPIC_ARN else None

    log.info(
        "consumer running queue=%s wait=%ss batch=%s",
        config.SQS_QUEUE_URL, config.SQS_WAIT_SECONDS, config.SQS_BATCH_SIZE,
    )

    while is_running():
        try:
            poll_once(sqs, sns)
        except Exception:  # noqa: BLE001
            log.exception("consumer iteration failed; backing off briefly")
            time.sleep(2)


def poll_once(sqs, sns) -> int:
    """Receive up to one batch and process. Returns number of messages handled.

    Public so tests can drive a single iteration.
    """
    resp = sqs.receive_message(
        QueueUrl=config.SQS_QUEUE_URL,
        MaxNumberOfMessages=config.SQS_BATCH_SIZE,
        WaitTimeSeconds=config.SQS_WAIT_SECONDS,
        VisibilityTimeout=config.SQS_VISIBILITY_TIMEOUT,
        MessageAttributeNames=["All"],
    )
    messages = resp.get("Messages", [])
    if not messages:
        return 0

    handled = 0
    for msg in messages:
        if _handle_message(sqs, sns, msg):
            handled += 1
    return handled


def _handle_message(sqs, sns, msg: dict) -> bool:
    body_text = msg.get("Body", "{}")
    msg_id = msg.get("MessageId")
    receipt = msg["ReceiptHandle"]
    job_id: int | None = None

    try:
        body = json.loads(body_text)
    except json.JSONDecodeError:
        log.error("undecodable SQS message id=%s body=%r", msg_id, body_text[:200])
        # Drop bad messages so they don't churn the queue forever.
        sqs.delete_message(QueueUrl=config.SQS_QUEUE_URL, ReceiptHandle=receipt)
        return False

    tenant_id = int(body.get("tenant_id") or 0)
    account_id = body.get("account_id")
    account_id = int(account_id) if account_id else None

    shipment_id = body.get("shipment_id")
    shipment_ids_raw = body.get("shipment_ids")
    if shipment_id and not shipment_ids_raw:
        shipment_ids = [int(shipment_id)]
    else:
        shipment_ids = [int(x) for x in (shipment_ids_raw or [])]

    if not tenant_id or not shipment_ids:
        log.error(
            "incomplete payload msg_id=%s tenant_id=%s shipment_ids=%s",
            msg_id, tenant_id, shipment_ids,
        )
        sqs.delete_message(QueueUrl=config.SQS_QUEUE_URL, ReceiptHandle=receipt)
        return False

    try:
        job_id = db.claim_job(msg_id, tenant_id, shipment_ids)
        inputs = db.fetch_inputs(tenant_id, shipment_ids)
        result = solver.solve_route(
            inputs["shipments"], inputs["addresses"], tenant_id,
        )
        calc_id = db.write_result(
            tenant_id=tenant_id,
            account_id=account_id,
            shipment_ids=shipment_ids,
            result=result,
            solver_version=solver.SOLVER_VERSION,
            duration_ms=int(result.get("duration_ms") or 0),
            job_id=job_id,
        )

        if sns:
            try:
                sns.publish(
                    TopicArn=config.SNS_TOPIC_ARN,
                    Message=json.dumps({
                        "type": "route_calculation_complete",
                        "calc_id": calc_id,
                        "tenant_id": tenant_id,
                        "shipment_ids": shipment_ids,
                        "ok": bool(result.get("ok")),
                    }),
                )
            except Exception:  # noqa: BLE001
                # SNS failure does NOT fail the message — the row is
                # already in route_calculations and the SQS visibility
                # timeout would re-deliver, causing duplicate solves.
                log.exception("SNS publish failed; not re-driving message")

        sqs.delete_message(QueueUrl=config.SQS_QUEUE_URL, ReceiptHandle=receipt)
        log.info("solve ok msg_id=%s calc_id=%s", msg_id, calc_id)
        return True
    except Exception as err:  # noqa: BLE001
        log.exception("solve failed msg_id=%s", msg_id)
        db.mark_job_failed(job_id, str(err))
        # Don't delete — let SQS retry via visibility timeout.
        return False
