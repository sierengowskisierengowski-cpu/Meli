"""Telegram bot notification."""
import requests
import structlog
from meli.config import get_config

log = structlog.get_logger()
_BASE = "https://api.telegram.org/bot"


def notify(rule_name: str, summary: str, severity: str) -> None:
    cfg = get_config()
    token = cfg.get("alerts", "telegram_bot_token")
    chat_id = cfg.get("alerts", "telegram_chat_id")
    if not token or not chat_id:
        return
    text = f"*Meli Alert — {severity}*\n{summary}\n_Rule: {rule_name}_"
    try:
        resp = requests.post(
            f"{_BASE}{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
        resp.raise_for_status()
    except Exception as e:
        log.warning("Telegram notification failed", error=str(e))


def test(token: str, chat_id: str) -> bool:
    try:
        resp = requests.post(
            f"{_BASE}{token}/sendMessage",
            json={"chat_id": chat_id, "text": "Meli test notification — Telegram integration is working."},
            timeout=8,
        )
        return resp.status_code == 200
    except Exception:
        return False
