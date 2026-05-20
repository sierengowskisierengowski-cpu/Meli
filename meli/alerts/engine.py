"""
Alert rule evaluation engine.
Evaluates each enabled AlertRule against incoming events,
respects cooldown periods and active hours, fires notifications.
"""
from __future__ import annotations

import json
import re
import time
import structlog
from datetime import datetime, timezone

from meli.database import get_db
from meli.database.models import AlertRule, Alert
from meli.utils.helpers import severity_rank

log = structlog.get_logger()

# In-memory cooldown tracker: rule_id -> last_fired_timestamp
_cooldowns: dict[int, float] = {}


class AlertEngine:
    def evaluate(self, event_id: int, event: dict, severity: str) -> None:
        try:
            with get_db() as db:
                from sqlalchemy import select
                rules = db.execute(
                    select(AlertRule).where(AlertRule.enabled == True)
                ).scalars().all()

                for rule in rules:
                    if self._should_fire(rule, event, severity):
                        self._fire(db, rule, event_id, event, severity)

        except Exception as e:
            log.error("Alert engine error", error=str(e))

    def _should_fire(self, rule: AlertRule, event: dict, severity: str) -> bool:
        # Severity threshold check
        if severity_rank(severity) < severity_rank(rule.severity_threshold):
            return False

        # Active hours check
        if rule.active_hours_start and rule.active_hours_end:
            now_time = datetime.now().strftime("%H:%M")
            if not self._in_active_hours(now_time, rule.active_hours_start, rule.active_hours_end):
                return False

        # Cooldown check
        last_fired = _cooldowns.get(rule.id, 0)
        cooldown = rule.cooldown_seconds or 300
        if time.time() - last_fired < cooldown:
            return False

        # Condition check
        if rule.conditions:
            try:
                conditions = json.loads(rule.conditions)
                if not self._conditions_match(conditions, event):
                    return False
            except Exception:
                pass

        return True

    def _conditions_match(self, conditions: list, event: dict) -> bool:
        for cond in conditions:
            field = cond.get("field", "")
            op = cond.get("operator", "eq")
            value = cond.get("value")
            ev_val = event.get(field, "")

            if op == "eq" and str(ev_val).lower() != str(value).lower():
                return False
            elif op == "in" and str(ev_val).lower() not in [str(v).lower() for v in (value or [])]:
                return False
            elif op == "regex":
                try:
                    if not re.search(value, str(ev_val), re.IGNORECASE):
                        return False
                except Exception:
                    return False
            elif op == "gte":
                try:
                    if float(ev_val or 0) < float(value):
                        return False
                except Exception:
                    return False
        return True

    def _fire(self, db, rule: AlertRule, event_id: int, event: dict, severity: str) -> None:
        now = datetime.now(timezone.utc)
        summary = self._build_summary(rule, event, severity)

        alert = Alert(
            rule_id=rule.id,
            rule_name=rule.name,
            triggered_at=now,
            event_id=event_id,
            severity=severity,
            summary=summary,
        )
        db.add(alert)
        db.flush()

        rule.last_triggered = now
        rule.fire_count = (rule.fire_count or 0) + 1

        _cooldowns[rule.id] = time.time()

        log.info("Alert fired", rule=rule.name, severity=severity, ip=event.get("source_ip"))

        # Send notifications async
        import threading
        channels = json.loads(rule.notification_channels or "[]")
        threading.Thread(
            target=_send_notifications,
            args=(channels, rule.name, summary, severity),
            daemon=True,
        ).start()

    def _build_summary(self, rule: AlertRule, event: dict, severity: str) -> str:
        ip = event.get("source_ip", "unknown")
        service = event.get("honeypot_service", "unknown")
        action = event.get("action_type", "unknown")
        return (
            f"[{severity}] Rule '{rule.name}' fired — "
            f"IP {ip} on {service} ({action})"
        )

    def _in_active_hours(self, now: str, start: str, end: str) -> bool:
        """Check if now (HH:MM) is within start-end range (may wrap midnight)."""
        if start <= end:
            return start <= now <= end
        # Wraps midnight
        return now >= start or now <= end


def _send_notifications(channels: list[str], rule_name: str, summary: str, severity: str) -> None:
    from meli.alerts import notifiers
    for channel in channels:
        try:
            if channel == "desktop":
                notifiers.desktop.notify(rule_name, summary, severity)
            elif channel == "sound":
                from meli.alerts.sound import play_alert_sound
                play_alert_sound(severity)
            elif channel == "discord":
                notifiers.discord.notify(rule_name, summary, severity)
            elif channel == "slack":
                notifiers.slack.notify(rule_name, summary, severity)
            elif channel == "telegram":
                notifiers.telegram.notify(rule_name, summary, severity)
            elif channel == "email":
                notifiers.email_smtp.notify(rule_name, summary, severity)
            elif channel == "webhook":
                notifiers.webhook.notify(rule_name, summary, severity)
        except Exception as e:
            log.error("Notification failed", channel=channel, error=str(e))
