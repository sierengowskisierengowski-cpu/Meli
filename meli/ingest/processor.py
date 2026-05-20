"""
Event processor — classifies, enriches, stores, and fires alerts.
Called by both the MQTT handler and HTTP ingest handler.
"""
from __future__ import annotations

import json
import structlog
from datetime import datetime, timezone

log = structlog.get_logger()


def process_event(raw: dict, source: str = "mqtt") -> None:
    """Full event pipeline: parse → classify → store → enrich → alert."""
    try:
        from meli.ingest.parsers.generic_json import GenericJsonParser
        from meli.classification.severity import classify_event
        from meli.enrichment.geolocation import geolocate_ip
        from meli.database import get_db
        from meli.database.models import Event, Attacker

        # Normalise to internal format
        parser = GenericJsonParser()
        normalized = parser.parse(raw)
        if not normalized:
            log.debug("Event skipped by parser", raw_keys=list(raw.keys()))
            return

        # Classify
        severity, matched_rules = classify_event(normalized)
        normalized["severity"] = severity
        normalized["classification_rules_matched"] = json.dumps(matched_rules)

        # Geolocate
        ip = normalized.get("source_ip", "")
        geo = geolocate_ip(ip)
        normalized["country_code"] = geo.get("country_code")

        # Store event
        with get_db() as db:
            ev = Event(
                timestamp=normalized.get("timestamp", datetime.now(timezone.utc)),
                source_ip=normalized.get("source_ip", ""),
                source_port=normalized.get("source_port"),
                destination_port=normalized.get("destination_port"),
                honeypot_service=normalized.get("honeypot_service", "unknown"),
                protocol=normalized.get("protocol"),
                transport=normalized.get("transport"),
                severity=severity,
                parsed_data=json.dumps(normalized),
                session_id=normalized.get("session_id"),
                country_code=normalized.get("country_code"),
                username=normalized.get("username"),
                command=normalized.get("command"),
                payload_hash=normalized.get("payload_hash"),
                classification_rules_matched=normalized["classification_rules_matched"],
                enrichment_status="pending",
            )
            db.add(ev)
            db.flush()
            event_id = ev.id

            # Upsert attacker record
            attacker = db.get(Attacker, ip)
            now = datetime.now(timezone.utc)
            if attacker:
                attacker.last_seen = now
                attacker.total_events += 1
                from meli.utils.helpers import severity_rank
                if severity_rank(severity) > severity_rank(attacker.max_severity):
                    attacker.max_severity = severity
            else:
                attacker = Attacker(
                    ip=ip,
                    first_seen=now,
                    last_seen=now,
                    total_events=1,
                    max_severity=severity,
                    country_code=normalized.get("country_code"),
                )
                db.add(attacker)

        # Fire alerts asynchronously
        import threading
        threading.Thread(
            target=_check_alerts,
            args=(event_id, normalized, severity),
            daemon=True,
        ).start()

        # Enrich IP asynchronously
        threading.Thread(
            target=_enrich_ip,
            args=(ip,),
            daemon=True,
        ).start()

        # Publish to processed MQTT topic
        _publish_processed(normalized)

        log.debug("Event processed", ip=ip, severity=severity, source=source)

    except Exception as e:
        log.error("Event processing error", error=str(e), exc_info=True)


def _check_alerts(event_id: int, event: dict, severity: str) -> None:
    try:
        from meli.alerts.engine import AlertEngine
        engine = AlertEngine()
        engine.evaluate(event_id, event, severity)
    except Exception as e:
        log.error("Alert check failed", error=str(e))


def _enrich_ip(ip: str) -> None:
    try:
        from meli.enrichment import enrich_ip
        enrich_ip(ip)
    except Exception as e:
        log.debug("Enrichment failed", ip=ip, error=str(e))


def _publish_processed(event: dict) -> None:
    try:
        import paho.mqtt.publish as publish
        from meli.config import get_config
        cfg = get_config()
        publish.single(
            topic=cfg.get("mqtt", "topic_processed", default="meli/events/processed"),
            payload=json.dumps(event, default=str),
            hostname=cfg.get("mqtt", "host", default="127.0.0.1"),
            port=cfg.get("mqtt", "port", default=1883),
            qos=0,
        )
    except Exception:
        pass  # MQTT publish failure is non-fatal
