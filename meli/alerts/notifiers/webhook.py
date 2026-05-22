"""Generic HTTP webhook notification."""
import requests
import structlog
from meli.config import get_config

log = structlog.get_logger()


def notify(rule_name: str, summary: str, severity: str) -> None:
    cfg = get_config()
    url = cfg.get("alerts", "webhook_url")
    if not url:
        return
    payload = {
        "source": "meli",
        "severity": severity,
        "rule": rule_name,
        "summary": summary,
    }
    try:
        requests.post(url, json=payload, timeout=8)
    except Exception as e:
        log.warning("Webhook notification failed", error=str(e))
