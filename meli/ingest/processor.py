"""
Event processor — classifies, enriches, stores, and fires alerts.
Called by both the MQTT handler and HTTP ingest handler.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import structlog
from datetime import datetime, timezone

log = structlog.get_logger()

# Striped per-IP locking: a fixed-size array of locks indexed by a hash
# of the IP. Two simultaneous events from the same brand-new attacker
# always hash to the same lock, so the second one waits and sees the
# row the first one inserted (preventing the UNIQUE-constraint crash).
# Unrelated IPs collide only ~1/N of the time, so ingest stays parallel.
# Crucially, memory is bounded — earlier per-IP dict grew without limit
# on internet-facing honeypots.
_LOCK_STRIPES = 256
_attacker_stripe_locks: tuple[threading.Lock, ...] = tuple(
    threading.Lock() for _ in range(_LOCK_STRIPES)
)


def _lock_for_ip(ip: str) -> threading.Lock:
    # Hash so adjacent IPs distribute evenly across stripes.
    h = int.from_bytes(hashlib.md5(ip.encode("utf-8", "replace")).digest()[:4], "big")
    return _attacker_stripe_locks[h % _LOCK_STRIPES]


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

        # Carry through trusted in-band fields from internal sources
        # (Labyrinth tarpit emits canary-trip / honeytoken events whose
        # severity is set authoritatively by the trap itself — these
        # are not adversary-controlled, so we honor them instead of
        # routing through classify_event's heuristic rules). The eventid
        # is preserved into normalized so downstream alert rules can
        # target 'labyrinth.canary.tripped' specifically.
        inline_severity = None
        if source == "labyrinth":
            ev_id = raw.get("eventid")
            if ev_id:
                normalized["eventid"] = ev_id
            for k in ("canary_token", "canary_path", "canary_summary",
                      "bot_score", "bot_confidence"):
                if k in raw:
                    normalized[k] = raw[k]
            raw_sev = raw.get("severity")
            if isinstance(raw_sev, str) and raw_sev.upper() in (
                "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"
            ):
                inline_severity = raw_sev.upper()

        # Classify (heuristic). For trusted inline severity, take the
        # MAX of rule-derived and inline so we never silently demote a
        # canary trip and we still pick up any rule-added matches.
        severity, matched_rules = classify_event(normalized)
        if inline_severity is not None:
            from meli.utils.helpers import severity_rank
            if severity_rank(inline_severity) > severity_rank(severity):
                severity = inline_severity
                matched_rules = list(matched_rules) + ["labyrinth.inline-severity"]
        normalized["severity"] = severity
        normalized["classification_rules_matched"] = json.dumps(matched_rules)

        # Geolocate
        ip = normalized.get("source_ip", "")
        geo = geolocate_ip(ip)
        normalized["country_code"] = geo.get("country_code")

        # ── Atomic event + attacker write ─────────────────────────
        # Hold the per-IP stripe lock around the WHOLE transaction so:
        #   (a) the UNIQUE(Attacker.ip) race is closed (two threads on
        #       the same brand-new IP can't both INSERT), and
        #   (b) we never commit an event without the corresponding
        #       attacker upsert (no aggregate drift even if the DB is
        #       transiently locked).
        # On SQLite, retry up to 3 times when the writer lock is held by
        # someone else (WAL "database is locked" appears as OperationalError).
        from sqlalchemy.exc import OperationalError
        from meli.utils.helpers import severity_rank
        event_id = None
        attempts = 3
        last_exc = None
        for attempt in range(attempts):
            try:
                with _lock_for_ip(ip):
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

                        attacker = db.get(Attacker, ip)
                        now = datetime.now(timezone.utc)
                        if attacker:
                            attacker.last_seen = now
                            attacker.total_events += 1
                            if severity_rank(severity) > severity_rank(attacker.max_severity):
                                attacker.max_severity = severity
                        else:
                            db.add(Attacker(
                                ip=ip,
                                first_seen=now,
                                last_seen=now,
                                total_events=1,
                                max_severity=severity,
                                country_code=normalized.get("country_code"),
                            ))
                break  # success
            except OperationalError as oe:
                last_exc = oe
                # SQLite lock contention — back off and retry.
                time.sleep(0.05 * (attempt + 1))
        else:
            # All retries exhausted: log loudly and bail. Neither row
            # was committed because each attempt was a single transaction.
            log.error("Event+attacker write failed after retries",
                      ip=ip, attempts=attempts, error=str(last_exc))
            return

        # Fire alerts asynchronously
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

        # In-process signal so the dashboard pot pulses in real time.
        # Subscribers re-dispatch to the GTK main loop themselves.
        try:
            from meli import event_bus
            event_bus.publish("event.ingested", {
                "severity": severity,
                "source_ip": ip,
                "honeypot_service": normalized.get("honeypot_service", "unknown"),
            })
        except Exception:
            pass

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
