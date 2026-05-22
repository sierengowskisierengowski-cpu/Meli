"""Slack webhook notification."""
import requests
import structlog
from meli.config import get_config

log = structlog.get_logger()

_COLORS = {"INFO": "#94a3b8", "LOW": "#60a5fa", "MEDIUM": "#f59e0b",
           "HIGH": "#f97316", "CRITICAL": "#ef4444"}


def notify(rule_name: str, summary: str, severity: str) -> None:
    cfg = get_config()
    webhook_url = cfg.get("alerts", "slack_webhook")
    if not webhook_url:
        return
    color = _COLORS.get(severity.upper(), "#94a3b8")
    payload = {
        "attachments": [{
            "color": color,
            "title": f"Meli Alert — {severity}",
            "text": summary,
            "footer": f"Rule: {rule_name}",
        }]
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=8)
        resp.raise_for_status()
    except Exception as e:
        log.warning("Slack notification failed", error=str(e))


def test(webhook_url: str) -> bool:
    try:
        resp = requests.post(webhook_url, json={
            "text": "Meli test notification — Slack integration is working."
        }, timeout=8)
        return resp.status_code == 200
    except Exception:
        return False
