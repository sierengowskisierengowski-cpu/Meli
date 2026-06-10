"""
Meli ingest daemon — runs as a background systemd user service.
Consumes events from MQTT and the HTTP POST API,
classifies them, enriches IPs, stores to DB, and fires alerts.
"""
from __future__ import annotations

import json
import signal
import threading
import time
import structlog
from http.server import BaseHTTPRequestHandler, HTTPServer

from meli.config import get_config
from meli.ingest.mqtt_handler import MqttHandler
from meli.ingest.processor import process_event

log = structlog.get_logger()


class IngestDaemon:
    """Main daemon — starts MQTT consumer + HTTP ingest server."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._mqtt: MqttHandler | None = None
        self._http_server: HTTPServer | None = None

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        cfg = get_config()

        # Start MQTT handler
        self._mqtt = MqttHandler(on_event=process_event)
        mqtt_thread = threading.Thread(target=self._mqtt.start, daemon=True, name="mqtt-consumer")
        mqtt_thread.start()
        log.info("MQTT consumer started",
                 host=cfg.get("mqtt", "host"),
                 port=cfg.get("mqtt", "port"))

        # Start HTTP ingest server
        if cfg.get("http_ingest", "enabled"):
            host = cfg.get("http_ingest", "host", default="127.0.0.1")
            port = cfg.get("http_ingest", "port", default=17654)
            self._http_server = HTTPServer((host, port), _IngestHTTPHandler)
            http_thread = threading.Thread(
                target=self._http_server.serve_forever,
                daemon=True,
                name="http-ingest"
            )
            http_thread.start()
            log.info("HTTP ingest server started", host=host, port=port)

        log.info("Meli ingest daemon running — waiting for events")

        while not self._stop_event.is_set():
            time.sleep(1)

        self._shutdown()

    def _handle_signal(self, signum, frame) -> None:
        log.info("Shutdown signal received", signal=signum)
        self._stop_event.set()

    def _shutdown(self) -> None:
        log.info("Shutting down ingest daemon")
        if self._mqtt:
            self._mqtt.stop()
        if self._http_server:
            self._http_server.shutdown()


class _IngestHTTPHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for event ingestion via POST."""

    def log_message(self, fmt, *args) -> None:
        pass  # suppress default access log

    def do_GET(self) -> None:
        if self.path == "/api/v1/health":
            self._json(200, {"status": "ok", "service": "meli-ingest"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/api/v1/events/ingest":
            self._json(404, {"error": "not found"})
            return

        # Auth
        token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not self._verify_token(token):
            self._json(401, {"error": "Unauthorized"})
            return

        # Parse body
        length = int(self.headers.get("Content-Length", 0))
        if length == 0 or length > 1_000_000:
            self._json(400, {"error": "Bad request"})
            return

        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._json(400, {"error": "Invalid JSON"})
            return

        try:
            process_event(body, source="http")
            self._json(202, {"status": "accepted"})
        except Exception as e:
            log.error("Event processing failed", error=str(e))
            self._json(500, {"error": "internal error"})

    def _verify_token(self, token: str) -> bool:
        if not token:
            return False
        cfg = get_config()
        from meli.database import get_db
        from meli.database.models import Honeypot
        with get_db() as db:
            from sqlalchemy import select
            # Token matches any enabled honeypot's ingest token
            rows = db.execute(select(Honeypot).where(Honeypot.enabled == True)).scalars().all()
            for hp in rows:
                if hp.ingest_token and hp.ingest_token == token:
                    return True
        return False

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
