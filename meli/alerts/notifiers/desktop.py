"""Desktop notification via libnotify (notify-send)."""
import subprocess
import structlog
log = structlog.get_logger()

_SEVERITY_URGENCY = {
    "INFO": "low", "LOW": "low", "MEDIUM": "normal",
    "HIGH": "critical", "CRITICAL": "critical",
}


def notify(rule_name: str, summary: str, severity: str) -> None:
    urgency = _SEVERITY_URGENCY.get(severity.upper(), "normal")
    try:
        subprocess.Popen([
            "notify-send",
            "--app-name=Meli",
            f"--urgency={urgency}",
            "--icon=meli",
            f"Meli Alert: {rule_name}",
            summary[:256],
        ])
    except Exception as e:
        log.warning("Desktop notification failed", error=str(e))
