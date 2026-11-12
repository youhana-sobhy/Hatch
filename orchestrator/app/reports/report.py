"""Onboarding report: what was configured, every check result, and who approved it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, ConfigBackup, Onboarding

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent),
    autoescape=select_autoescape(["html", "j2"]),
)


def build(session: Session, ob: Onboarding) -> dict[str, Any]:
    latest = {}
    for run in ob.stages:  # last attempt of each stage wins
        latest[run.stage] = run
    checks = latest["post_checks"].details.get("checks", []) if "post_checks" in latest else []
    compliance = [c for c in ob.compliance if c.attempt == ob.attempt] or list(ob.compliance)
    audit = session.scalars(
        select(AuditEvent).where(AuditEvent.onboarding_id == ob.id).order_by(AuditEvent.id)
    ).all()
    backups = session.scalars(
        select(ConfigBackup)
        .where(ConfigBackup.onboarding_id == ob.id, ConfigBackup.version > 0)
        .order_by(ConfigBackup.version)
    ).all()
    passed = sum(1 for c in compliance if c.passed)
    return {
        "onboarding": {
            "id": ob.id,
            "hostname": ob.hostname,
            "serial": ob.serial,
            "vendor": ob.vendor,
            "model": ob.model,
            "role": ob.role,
            "site": ob.site,
            "market": ob.market,
            "mode": ob.mode,
            "mgmt_ip": ob.mgmt_ip,
            "status": ob.status,
            "template": ob.template_key,
            "template_version": ob.template_version,
            "config_sha256": ob.rendered_sha256,
            "requested_by": ob.requested_by,
            "approved_by": ob.approved_by,
            "ticket_ref": ob.ticket_ref,
            "created_at": ob.created_at.isoformat(),
            "completed_at": ob.completed_at.isoformat() if ob.completed_at else None,
            "attempts": ob.attempt,
        },
        "stages": [
            {
                "stage": r.stage,
                "attempt": r.attempt,
                "status": r.status,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "output": r.output,
            }
            for r in ob.stages
        ],
        "post_checks": checks,
        "compliance": {
            "passed": passed,
            "total": len(compliance),
            "rules": [
                {
                    "rule_id": c.rule_id,
                    "title": c.title,
                    "severity": c.severity,
                    "passed": c.passed,
                    "evidence": c.evidence,
                }
                for c in compliance
            ],
        },
        "backups": [
            {"version": b.version, "sha256": b.sha256, "created_at": b.created_at.isoformat()}
            for b in backups
        ],
        "audit": [
            {
                "at": e.at.isoformat(),
                "actor": e.actor,
                "action": e.action,
                "from": e.from_status,
                "to": e.to_status,
            }
            for e in audit
        ],
    }


def render_html(data: dict[str, Any]) -> str:
    return _env.get_template("report.html.j2").render(**data)
