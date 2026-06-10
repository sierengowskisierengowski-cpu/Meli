"""
Report generator for Meli.
Produces daily/weekly/monthly/custom reports in PDF, Markdown, JSON, CSV.
"""
from __future__ import annotations

import json
import structlog
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from meli.config import get_config
from meli.database import get_db
from meli.database.models import Event, Attacker, Credential, Command, Payload, Alert, Report

log = structlog.get_logger()


def _period_bounds(report_type: str, from_dt: datetime | None = None,
                   to_dt: datetime | None = None) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if report_type == "daily":
        end = now
        start = now - timedelta(days=1)
    elif report_type == "weekly":
        end = now
        start = now - timedelta(days=7)
    elif report_type == "monthly":
        end = now
        start = now - timedelta(days=30)
    elif report_type == "custom" and from_dt and to_dt:
        start, end = from_dt, to_dt
    else:
        end = now
        start = now - timedelta(days=7)
    return start, end


def _gather_stats(start: datetime, end: datetime) -> dict[str, Any]:
    """Collect all stats needed for a report."""
    from sqlalchemy import func, select, and_

    stats: dict[str, Any] = {}

    with get_db() as db:
        # Event counts
        total = db.execute(
            select(func.count(Event.id)).where(
                and_(Event.timestamp >= start, Event.timestamp <= end)
            )
        ).scalar() or 0
        stats["total_events"] = total

        # Severity breakdown
        sev_rows = db.execute(
            select(Event.severity, func.count(Event.id)).where(
                and_(Event.timestamp >= start, Event.timestamp <= end)
            ).group_by(Event.severity)
        ).all()
        stats["severity_breakdown"] = {r[0]: r[1] for r in sev_rows}

        # Top attackers
        top_attk = db.execute(
            select(Event.source_ip, func.count(Event.id).label("cnt")).where(
                and_(Event.timestamp >= start, Event.timestamp <= end)
            ).group_by(Event.source_ip).order_by(func.count(Event.id).desc()).limit(20)
        ).all()
        stats["top_attackers"] = [{"ip": r[0], "count": r[1]} for r in top_attk]

        # Top credentials
        top_creds = db.execute(
            select(Credential.username, Credential.password, Credential.attempt_count)
            .order_by(Credential.attempt_count.desc()).limit(20)
        ).all()
        stats["top_credentials"] = [
            {"username": r[0], "password": r[1], "count": r[2]} for r in top_creds
        ]

        # Top commands
        top_cmds = db.execute(
            select(Command.command_text, Command.execution_count, Command.detected_intent)
            .order_by(Command.execution_count.desc()).limit(20)
        ).all()
        stats["top_commands"] = [
            {"command": r[0], "count": r[1], "intent": r[2]} for r in top_cmds
        ]

        # Payloads
        payload_count = db.execute(
            select(func.count(Payload.id)).where(
                Payload.captured_at >= start, Payload.captured_at <= end
            )
        ).scalar() or 0
        stats["payloads_captured"] = payload_count

        # Alerts fired
        alert_count = db.execute(
            select(func.count(Alert.id)).where(
                and_(Alert.triggered_at >= start, Alert.triggered_at <= end)
            )
        ).scalar() or 0
        stats["alerts_fired"] = alert_count

        # Per-service breakdown
        svc_rows = db.execute(
            select(Event.honeypot_service, func.count(Event.id)).where(
                and_(Event.timestamp >= start, Event.timestamp <= end)
            ).group_by(Event.honeypot_service).order_by(func.count(Event.id).desc())
        ).all()
        stats["per_service"] = [{"service": r[0], "count": r[1]} for r in svc_rows]

        # Unique IPs
        unique_ips = db.execute(
            select(func.count(func.distinct(Event.source_ip))).where(
                and_(Event.timestamp >= start, Event.timestamp <= end)
            )
        ).scalar() or 0
        stats["unique_ips"] = unique_ips

        # Top countries
        country_rows = db.execute(
            select(Event.country_code, func.count(Event.id)).where(
                and_(Event.timestamp >= start, Event.timestamp <= end,
                     Event.country_code.isnot(None))
            ).group_by(Event.country_code).order_by(func.count(Event.id).desc()).limit(15)
        ).all()
        stats["top_countries"] = [{"country_code": r[0], "count": r[1]} for r in country_rows]

        # Notable events (HIGH + CRITICAL)
        notable = db.execute(
            select(Event).where(
                and_(Event.timestamp >= start, Event.timestamp <= end,
                     Event.severity.in_(["HIGH", "CRITICAL"]))
            ).order_by(Event.timestamp.desc()).limit(20)
        ).scalars().all()
        stats["notable_events"] = [
            {
                "timestamp": str(e.timestamp),
                "ip": e.source_ip,
                "service": e.honeypot_service,
                "severity": e.severity,
                "country": e.country_code,
            }
            for e in notable
        ]

    return stats


def generate_report(report_type: str, fmt: str = "markdown",
                    from_dt: datetime | None = None,
                    to_dt: datetime | None = None) -> Path:
    """Generate a report and return the path to the output file."""
    start, end = _period_bounds(report_type, from_dt, to_dt)
    stats = _gather_stats(start, end)
    stats["period_start"] = start.isoformat()
    stats["period_end"] = end.isoformat()
    stats["generated_at"] = datetime.now(timezone.utc).isoformat()
    stats["report_type"] = report_type

    cfg = get_config()
    output_dir = Path(cfg.get("reports", "output_path")) / report_type
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"meli_{report_type}_{ts}.{fmt}"
    out_path = output_dir / filename

    if fmt == "json":
        out_path.write_text(json.dumps(stats, indent=2, default=str))
    elif fmt == "markdown":
        content = _render_markdown(stats)
        out_path.write_text(content)
    elif fmt == "pdf":
        content = _render_markdown(stats)
        _export_pdf(content, out_path.with_suffix(".pdf"))
        out_path = out_path.with_suffix(".pdf")
    elif fmt == "csv":
        _export_csv(stats, out_path)
    else:
        out_path.write_text(json.dumps(stats, indent=2, default=str))

    # Persist to DB
    with get_db() as db:
        r = Report(
            report_type=report_type,
            period_start=start,
            period_end=end,
            file_path=str(out_path),
            report_format=fmt,
            summary=f"{stats['total_events']} events, {stats['unique_ips']} unique IPs",
        )
        db.add(r)

    log.info("Report generated", type=report_type, fmt=fmt, path=str(out_path))
    return out_path


def _render_markdown(stats: dict) -> str:
    lines = [
        f"# Meli Threat Intelligence Report",
        f"**Type:** {stats['report_type'].title()}  ",
        f"**Period:** {stats['period_start'][:10]} → {stats['period_end'][:10]}  ",
        f"**Generated:** {stats['generated_at'][:19]}Z  ",
        "",
        "## Executive Summary",
        f"- **Total Events:** {stats['total_events']:,}",
        f"- **Unique Attackers:** {stats['unique_ips']:,}",
        f"- **Payloads Captured:** {stats['payloads_captured']}",
        f"- **Alerts Fired:** {stats['alerts_fired']}",
        "",
        "## Severity Breakdown",
    ]
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
        cnt = stats.get("severity_breakdown", {}).get(sev, 0)
        lines.append(f"- **{sev}:** {cnt:,}")

    lines += ["", "## Top Attacking IPs"]
    for a in stats.get("top_attackers", [])[:10]:
        lines.append(f"- `{a['ip']}` — {a['count']:,} events")

    lines += ["", "## Top Credentials"]
    for c in stats.get("top_credentials", [])[:10]:
        lines.append(f"- `{c['username']}:{c['password']}` — {c['count']:,} attempts")

    lines += ["", "## Top Commands (Post-Auth)"]
    for cmd in stats.get("top_commands", [])[:10]:
        intent = f" [{cmd['intent']}]" if cmd.get("intent") else ""
        lines.append(f"- `{cmd['command'][:80]}`{intent} — {cmd['count']:,}×")

    lines += ["", "## Per-Service Breakdown"]
    for svc in stats.get("per_service", []):
        lines.append(f"- **{svc['service']}:** {svc['count']:,} events")

    lines += ["", "## Top Countries"]
    for c in stats.get("top_countries", [])[:10]:
        lines.append(f"- {c['country_code']}: {c['count']:,}")

    lines += ["", "## Notable Events (HIGH/CRITICAL)"]
    for e in stats.get("notable_events", [])[:10]:
        lines.append(
            f"- [{e['severity']}] {e['timestamp'][:19]} — `{e['ip']}` "
            f"({e.get('country', '?')}) → {e['service']}"
        )

    lines += ["", "---", "*Generated by Meli Honeypot Command Center*",
              "*Author: Joseph Sierengowski*"]
    return "\n".join(lines)


def _export_pdf(markdown_content: str, out_path: Path) -> None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm

        doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                                leftMargin=2*cm, rightMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        story = []
        for line in markdown_content.splitlines():
            if line.startswith("# "):
                story.append(Paragraph(line[2:], styles["Heading1"]))
            elif line.startswith("## "):
                story.append(Paragraph(line[3:], styles["Heading2"]))
            elif line.strip():
                story.append(Paragraph(line.replace("`", ""), styles["Normal"]))
            else:
                story.append(Spacer(1, 6))
        doc.build(story)
    except Exception as e:
        log.error("PDF generation failed", error=str(e))
        out_path.write_text(markdown_content)


def _export_csv(stats: dict, out_path: Path) -> None:
    import csv
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Report Type", "Period Start", "Period End", "Total Events",
                    "Unique IPs", "Payloads", "Alerts"])
        w.writerow([stats["report_type"], stats["period_start"], stats["period_end"],
                    stats["total_events"], stats["unique_ips"],
                    stats["payloads_captured"], stats["alerts_fired"]])
        w.writerow([])
        w.writerow(["Top Attackers"])
        w.writerow(["IP", "Count"])
        for a in stats.get("top_attackers", []):
            w.writerow([a["ip"], a["count"]])
