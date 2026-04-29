"""Entry point. Wires up logging, starts the health server, runs the
consumer loop. SIGTERM-aware."""

import logging
import signal
import sys
import threading

import structlog

from . import config, consumer, db, health


def _configure_logging() -> None:
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )


def main() -> int:
    _configure_logging()
    log = logging.getLogger("main")
    log.info("starting route-optimizer env=%s", config.ENV)

    consumer_thread = threading.Thread(
        target=consumer.run_loop,
        name="consumer",
        daemon=False,
    )
    health.start_in_thread(consumer_alive_check=lambda: consumer_thread.is_alive())

    consumer_thread.start()

    def _signal_handler(signum, _frame):
        log.info("signal received signum=%s; stopping consumer", signum)
        consumer.stop()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT,  _signal_handler)

    consumer_thread.join()
    log.info("consumer thread exited; closing pool")
    db.close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(main())
