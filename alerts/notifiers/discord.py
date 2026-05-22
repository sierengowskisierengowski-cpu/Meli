"""Discord webhook notification."""
import requests
import structlog
from meli.config import get_config

log = structlog.get_logger()

_COLORS = {"INFO": 0x94a3b8, "LOW": 0x60a5fa, "MEDIUM": 0xf59e0b,
           "HIGH": 0xf97316, "CRITICAL": 0xef4444}


def notify(rule_name: str, summary: str, severity: str) -> None:
    cfg = get_config()
    webhook_url = cfg.get("alerts", "discord_webhook")
    if not webhook_url:
        return
    color = _COLORS.get(severity.upper(), 0x94a3b8)
    payload = {
        "embeds": [{
            "title": f"Meli Alert — {severity}",
            "description": summary,
            "color": color,
            "footer": {"text": f"Rule: {rule_name}"},
        }]
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=8)
        resp.raise_for_status()
    except Exception as e:
        log.warning("Discord notification failed", error=str(e))


def test(webhook_url: str) -> bool:
    try:
        resp = requests.post(webhook_url, json={
            "content": "Meli test notification — Discord integration is working."
        }, timeout=8)
        return resp.status_code in (200, 204)
    except Exception:
        return False
