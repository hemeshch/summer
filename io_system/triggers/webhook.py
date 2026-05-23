"""HTTP webhook trigger.

Spins up a small stdlib-based HTTP server (``http.server``) on a configurable
port and accepts ``POST /trigger`` requests. The body is a JSON object:

    {
        "title": "Flight booked",
        "content": "United UA1234 SFO -> JFK on 2026-06-15...",
        "source": "user-script",   // optional, default "webhook"
        "event_id": "some-uid"     // optional
    }

The endpoint validates the payload, constructs a ``TriggerEvent``, fires the
callback, and returns 200 with the assigned ``event_id``.

Auth: if ``SUMMER_WEBHOOK_TOKEN`` is set, requests must include a header
``X-Summer-Token`` whose value matches. If unset, the server is open and
binds to 127.0.0.1 unless ``SUMMER_WEBHOOK_BIND`` says otherwise.

Why stdlib: avoids pulling FastAPI/uvicorn into the dependency set just for
this. The endpoint is tiny and ``http.server`` handles it cleanly.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .base import EventTrigger, TriggerCallback, TriggerEvent

logger = logging.getLogger(__name__)


# Cap request bodies to keep a misbehaving (or malicious) client from forcing
# a giant allocation. 64 KiB is more than enough for a JSON trigger payload.
_MAX_BODY_BYTES = 64 * 1024


class WebhookTrigger(EventTrigger):
    """Receives external pushes over HTTP and emits them as TriggerEvents."""

    name = "webhook"

    def __init__(
        self,
        on_event: TriggerCallback,
        port: Optional[int] = None,
        bind: Optional[str] = None,
        token: Optional[str] = None,
    ):
        super().__init__(on_event)
        try:
            self.port = int(
                port if port is not None
                else os.environ.get("SUMMER_WEBHOOK_PORT", "8848")
            )
        except ValueError:
            self.port = 8848
        self.bind = bind or os.environ.get("SUMMER_WEBHOOK_BIND", "127.0.0.1")
        self.token = token if token is not None else os.environ.get(
            "SUMMER_WEBHOOK_TOKEN"
        )
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @classmethod
    def is_available(cls) -> bool:
        # http.server ships with stdlib so we're always available.
        return True

    # ----- lifecycle -----

    def start(self) -> None:
        if self._server is not None:
            return

        trigger = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # quieten default access log
                logger.debug("WebhookTrigger access: " + fmt, *args)

            def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
                if self.path != "/trigger":
                    self._send_json(404, {"error": "not found"})
                    return
                if trigger.token:
                    supplied = self.headers.get("X-Summer-Token", "") or ""
                    # hmac.compare_digest avoids the timing-attack surface
                    # that `!=` on secrets opens up.
                    if not hmac.compare_digest(supplied, trigger.token):
                        self._send_json(401, {"error": "invalid token"})
                        return
                try:
                    length = int(self.headers.get("Content-Length", "0") or 0)
                except ValueError:
                    self._send_json(400, {"error": "bad content-length"})
                    return
                if length > _MAX_BODY_BYTES:
                    self._send_json(413, {"error": "payload too large"})
                    return
                raw = self.rfile.read(length) if length > 0 else b""
                try:
                    payload = json.loads(raw.decode("utf-8")) if raw else {}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._send_json(400, {"error": "invalid json"})
                    return
                if not isinstance(payload, dict):
                    self._send_json(400, {"error": "json object required"})
                    return
                title = payload.get("title")
                content = payload.get("content")
                if not isinstance(title, str) or not isinstance(content, str):
                    self._send_json(
                        400, {"error": "title and content (strings) required"}
                    )
                    return
                source = payload.get("source") or trigger.name
                event_id = payload.get("event_id") or f"webhook:{uuid.uuid4().hex}"
                metadata = payload.get("metadata") or {}
                if not isinstance(metadata, dict):
                    metadata = {"raw_metadata": metadata}
                event = TriggerEvent(
                    source=str(source),
                    title=title,
                    content=content,
                    timestamp=datetime.now(timezone.utc),
                    metadata=metadata,
                    event_id=str(event_id),
                )
                trigger._emit(event)
                self._send_json(200, {"ok": True, "event_id": event_id})

            def do_GET(self):  # noqa: N802
                if self.path == "/healthz":
                    self._send_json(200, {"ok": True})
                    return
                self._send_json(404, {"error": "not found"})

            def _send_json(self, status: int, body: dict) -> None:
                payload = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        try:
            self._server = ThreadingHTTPServer((self.bind, self.port), Handler)
        except OSError:
            logger.exception(
                "WebhookTrigger: cannot bind %s:%s", self.bind, self.port
            )
            self._server = None
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.5},
            name="WebhookTrigger",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "WebhookTrigger: listening on %s:%s (auth=%s)",
            self.bind, self.port, "token" if self.token else "open",
        )

    def stop(self, timeout: float = 5.0) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                logger.exception("WebhookTrigger: shutdown error")
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
