"""
SQLAlchemy models for Meli.
Uses SQLite by default; PostgreSQL optional.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, create_engine, event, text,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from meli.config import get_config


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Engine ────────────────────────────────────────────────────────────────────

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        cfg = get_config()
        db_path = cfg.db_path
        _engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )

        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Base ──────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Models ────────────────────────────────────────────────────────────────────

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_uuid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    source_ip = Column(String(45), nullable=False, index=True)
    source_port = Column(Integer)
    destination_ip = Column(String(45))
    destination_port = Column(Integer)
    honeypot_service = Column(String(50), nullable=False, index=True)
    protocol = Column(String(20))
    transport = Column(String(20))
    severity = Column(String(10), nullable=False, default="INFO", index=True)
    raw_payload = Column(Text)         # encrypted
    parsed_data = Column(Text)         # JSON
    session_id = Column(String(36), index=True)
    country_code = Column(String(2))
    asn = Column(String(20))
    classification_rules_matched = Column(Text)  # JSON list
    enrichment_status = Column(String(20), default="pending")
    username = Column(String(255))
    password = Column(String(255))    # encrypted
    command = Column(Text)
    payload_hash = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_events_ts_sev", "timestamp", "severity"),
        Index("ix_events_ip_ts", "source_ip", "timestamp"),
    )


class EventSession(Base):
    __tablename__ = "event_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), unique=True, nullable=False)
    source_ip = Column(String(45), nullable=False, index=True)
    honeypot_service = Column(String(50))
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True))
    event_count = Column(Integer, default=0)
    max_severity = Column(String(10), default="INFO")
    summary = Column(Text)


class Attacker(Base):
    __tablename__ = "attackers"

    ip = Column(String(45), primary_key=True)
    first_seen = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    total_events = Column(Integer, default=0)
    max_severity = Column(String(10), default="INFO")
    country_code = Column(String(2))
    asn = Column(String(20))
    organization = Column(String(255))
    is_tor = Column(Boolean, default=False)
    is_vpn = Column(Boolean, default=False)
    is_known_bot = Column(Boolean, default=False)
    reputation_score = Column(Integer, default=0)  # 0-100 abuse confidence
    notes = Column(Text)
    enriched_at = Column(DateTime(timezone=True))
    greynoise_classification = Column(String(50))
    greynoise_tags = Column(Text)      # JSON
    abuseipdb_score = Column(Integer)
    virustotal_malicious = Column(Integer)


class Credential(Base):
    __tablename__ = "credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), nullable=False)
    password = Column(String(255), nullable=False)  # encrypted at rest
    attempt_count = Column(Integer, default=1)
    first_seen = Column(DateTime(timezone=True), default=_utcnow)
    last_seen = Column(DateTime(timezone=True), default=_utcnow)
    source_honeypots = Column(Text)    # JSON list
    source_ips = Column(Text)          # JSON list

    __table_args__ = (
        Index("ix_cred_user_pass", "username", "password", unique=True),
    )


class Command(Base):
    __tablename__ = "commands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    command_text = Column(Text, nullable=False)
    execution_count = Column(Integer, default=1)
    detected_intent = Column(String(50))
    first_seen = Column(DateTime(timezone=True), default=_utcnow)
    last_seen = Column(DateTime(timezone=True), default=_utcnow)
    source_ips = Column(Text)          # JSON list


class Payload(Base):
    __tablename__ = "payloads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sha256 = Column(String(64), unique=True, nullable=False)
    sha1 = Column(String(40))
    md5 = Column(String(32))
    file_size = Column(Integer)
    file_type = Column(String(100))
    captured_at = Column(DateTime(timezone=True), default=_utcnow)
    source_ip = Column(String(45))
    source_honeypot = Column(String(50))
    file_path = Column(String(500))    # path inside quarantine
    virustotal_status = Column(String(20), default="unchecked")
    virustotal_score = Column(String(20))
    virustotal_results = Column(Text)  # JSON
    analyzed = Column(Boolean, default=False)
    marked_benign = Column(Boolean, default=False)


class Honeypot(Base):
    __tablename__ = "honeypots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    honeypot_type = Column(String(50), nullable=False)
    ingest_method = Column(String(20), default="mqtt")  # mqtt, logfile, http
    endpoint = Column(String(500))
    ingest_token = Column(Text)        # encrypted
    enabled = Column(Boolean, default=True)
    last_event_at = Column(DateTime(timezone=True))
    total_events_received = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    enabled = Column(Boolean, default=True)
    severity_threshold = Column(String(10), default="HIGH")
    conditions = Column(Text)          # JSON
    notification_channels = Column(Text)  # JSON list
    cooldown_seconds = Column(Integer, default=300)
    active_hours_start = Column(String(5))
    active_hours_end = Column(String(5))
    last_triggered = Column(DateTime(timezone=True))
    fire_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    alerts = relationship("Alert", back_populates="rule", cascade="all, delete-orphan")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id", ondelete="SET NULL"))
    rule_name = Column(String(200))
    triggered_at = Column(DateTime(timezone=True), default=_utcnow, index=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="SET NULL"))
    severity = Column(String(10), nullable=False)
    summary = Column(Text)
    acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime(timezone=True))

    rule = relationship("AlertRule", back_populates="alerts")


class ApiKey(Base):
    __tablename__ = "api_keys"

    service = Column(String(50), primary_key=True)
    encrypted_key = Column(Text)
    last_used = Column(DateTime(timezone=True))
    usage_count = Column(Integer, default=0)


class EnrichmentCache(Base):
    __tablename__ = "enrichment_cache"

    key = Column(String(200), primary_key=True)  # "service:ip"
    data = Column(Text)                           # JSON
    fetched_at = Column(DateTime(timezone=True), default=_utcnow)
    expires_at = Column(DateTime(timezone=True))


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_type = Column(String(20), nullable=False)   # daily/weekly/monthly/custom
    period_start = Column(DateTime(timezone=True))
    period_end = Column(DateTime(timezone=True))
    generated_at = Column(DateTime(timezone=True), default=_utcnow)
    file_path = Column(String(500))
    report_format = Column(String(10), default="markdown")
    summary = Column(Text)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), default=_utcnow, index=True)
    event_type = Column(String(100), nullable=False)
    actor = Column(String(100))
    description = Column(Text)
    ip_address = Column(String(45))


class UserSetting(Base):
    __tablename__ = "user_settings"

    key = Column(String(200), primary_key=True)
    value = Column(Text)
