"""
Severity classification engine for Meli.
Applies YAML-defined rules to determine event severity.
"""
from __future__ import annotations

import re
import json
import structlog
from typing import Any

from meli.classification.rules import RuleLoader

log = structlog.get_logger()

_SEVERITY_RANK = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
_RANK_SEVERITY = {v: k for k, v in _SEVERITY_RANK.items()}

_loader = RuleLoader()


def classify_event(event: dict[str, Any]) -> tuple[str, list[str]]:
    """
    Classify an event and return (severity, matched_rule_names).
    """
    rules = _loader.get_rules()
    best_rank = 0
    best_severity = "INFO"
    matched: list[str] = []

    # Enrich event with attacker context for threshold-based rules
    _inject_attacker_context(event)

    for rule in sorted(rules, key=lambda r: r.get("priority", 99)):
        if _rule_matches(rule, event):
            severity = rule.get("severity", "INFO").upper()
            rank = _SEVERITY_RANK.get(severity, 0)
            matched.append(rule["name"])
            if rank > best_rank:
                best_rank = rank
                best_severity = severity

    return best_severity, matched


def _rule_matches(rule: dict, event: dict) -> bool:
    """Return True if ALL conditions in a rule match the event."""
    conditions = rule.get("conditions", [])
    if not conditions:
        return False
    return all(_condition_matches(c, event) for c in conditions)


def _condition_matches(condition: dict, event: dict) -> bool:
    field = condition.get("field", "")
    operator = condition.get("operator", "eq")
    value = condition.get("value")

    # Resolve nested field
    ev_val = event.get(field)

    if operator == "eq":
        return str(ev_val or "").lower() == str(value).lower()
    elif operator == "in":
        return str(ev_val or "").lower() in [str(v).lower() for v in (value or [])]
    elif operator == "regex":
        try:
            return bool(re.search(value, str(ev_val or ""), re.IGNORECASE))
        except re.error:
            return False
    elif operator == "exists":
        return ev_val is not None and ev_val != ""
    elif operator == "gte":
        try:
            return float(ev_val or 0) >= float(value)
        except (TypeError, ValueError):
            return False
    elif operator == "lte":
        try:
            return float(ev_val or 0) <= float(value)
        except (TypeError, ValueError):
            return False
    return False


def _inject_attacker_context(event: dict) -> None:
    """
    Add attacker_event_count and attacker_service_count to event
    for threshold-based rules. Uses a fast DB query.
    """
    ip = event.get("source_ip")
    if not ip:
        return
    try:
        from meli.database import get_db
        from meli.database.models import Attacker
        with get_db() as db:
            attacker = db.get(Attacker, ip)
            if attacker:
                event["attacker_event_count"] = attacker.total_events
    except Exception:
        pass
