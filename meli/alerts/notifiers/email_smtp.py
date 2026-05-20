"""SMTP email notification."""
import smtplib
import structlog
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from meli.config import get_config

log = structlog.get_logger()


def notify(rule_name: str, summary: str, severity: str) -> None:
    cfg = get_config()
    host = cfg.get("alerts", "email_smtp_host")
    if not host:
        return
    port = cfg.get("alerts", "email_smtp_port", default=587)
    use_tls = cfg.get("alerts", "email_smtp_tls", default=True)
    user = cfg.get("alerts", "email_smtp_user")
    password = cfg.get("alerts", "email_smtp_password")
    from_addr = cfg.get("alerts", "email_from") or user
    to_addr = cfg.get("alerts", "email_to")
    if not to_addr:
        return

    subject = f"[Meli] {severity} Alert: {rule_name}"
    body = f"Meli Honeypot Alert\n\nSeverity: {severity}\nRule: {rule_name}\n\n{summary}"

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        if use_tls:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        if user and password:
            server.login(user, password)
        server.sendmail(from_addr, to_addr, msg.as_string())
        server.quit()
    except Exception as e:
        log.warning("Email notification failed", error=str(e))


def test(host: str, port: int, use_tls: bool, user: str, password: str,
         from_addr: str, to_addr: str) -> tuple[bool, str]:
    try:
        if use_tls:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        if user and password:
            server.login(user, password)
        msg = MIMEText("Meli test email — SMTP integration is working.")
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Subject"] = "[Meli] Test Notification"
        server.sendmail(from_addr, to_addr, msg.as_string())
        server.quit()
        return True, "Test email sent."
    except Exception as e:
        return False, str(e)
