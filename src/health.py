"""Tiny HTTP server for the ECS health check.

We're a worker, not an HTTP service, so this is just liveness — is the
consumer thread alive. No /readyz; the worker either polls SQS or it
doesn't, there is no in-between.
"""

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import config

log = logging.getLogger(__name__)


class _Handler(BaseHTTPRequestHandler):
    consumer_alive_check = staticmethod(lambda: False)

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler convention)
        if self.path != "/healthz":
            self.send_response(404)
            self.end_headers()
            return
        alive = bool(_Handler.consumer_alive_check())
        self.send_response(200 if alive else 503)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        body = b'{"ok":true}\n' if alive else b'{"ok":false,"reason":"consumer_thread_dead"}\n'
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # noqa: N802
        # Suppress the default stderr line; we have structured logs elsewhere.
        log.debug("health: " + fmt, *args)


def start_in_thread(consumer_alive_check) -> threading.Thread:
    """Start the HTTP server in a daemon thread. Returns the thread.

    consumer_alive_check is a callable returning bool; gets called on
    each /healthz request.
    """
    _Handler.consumer_alive_check = staticmethod(consumer_alive_check)
    server = HTTPServer(("0.0.0.0", config.PORT), _Handler)
    t = threading.Thread(
        target=server.serve_forever,
        name="health-server",
        daemon=True,
    )
    t.start()
    log.info("health server listening on :%s", config.PORT)
    return t
