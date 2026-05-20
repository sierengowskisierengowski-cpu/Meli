"""
MQTT client — subscribes to meli/events/ingest and dispatches events.
"""
from __future__ import annotations

import json
import time
import structlog
from typing import Callable

import paho.mqtt.client as mqtt

from meli.config import get_config

log = structlog.get_logger()


class MqttHandler:
    def __init__(self, on_event: Callable[[dict], None]) -> None:
        self._on_event = on_event
        cfg = get_config()
        self._host = cfg.get("mqtt", "host", default="127.0.0.1")
        self._port = cfg.get("mqtt", "port", default=1883)
        self._qos = cfg.get("mqtt", "qos", default=1)
        self._topic = cfg.get("mqtt", "topic_ingest", default="meli/events/ingest")
        self._client = mqtt.Client(
            client_id="meli-ingest-daemon",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect
        self._running = False

    def start(self) -> None:
        self._running = True
        retry_delay = 5
        while self._running:
            try:
                self._client.connect(self._host, self._port, keepalive=60)
                self._client.loop_forever()
            except Exception as e:
                log.warning("MQTT connection failed — retrying",
                            host=self._host, port=self._port,
                            error=str(e), delay=retry_delay)
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    def stop(self) -> None:
        self._running = False
        try:
            self._client.disconnect()
            self._client.loop_stop()
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            client.subscribe(self._topic, qos=self._qos)
            log.info("MQTT connected and subscribed", topic=self._topic)
        else:
            log.error("MQTT connect failed", reason=reason_code)

    def _on_message(self, client, userdata, message) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            self._on_event(payload, source="mqtt")
        except json.JSONDecodeError:
            log.warning("MQTT: non-JSON message on ingest topic")
        except Exception as e:
            log.error("MQTT message handling error", error=str(e))

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        if self._running:
            log.warning("MQTT disconnected — will reconnect", reason=reason_code)
