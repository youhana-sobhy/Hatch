"""Catalog, templates, inventory, audit and dashboard statistics."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, current_principal, require
from app.core import compliance
from app.core.content import library, reload_library
from app.core.onboarding import Principal
from app.core.state_machine import RUNNING, TRANSITIONS, Status
from app.core.validation import Claims, suggest
from app.models import AuditEvent, ComplianceResult, Device, Onboarding, StageRun, utcnow
from app.schemas import AuditOut, DeviceOut, TemplateOut

router = APIRouter(prefix="/api/v1", tags=["catalog"])


def _template_out(t) -> TemplateOut:
    return TemplateOut(
        key=t.key,
        vendor=t.vendor,
        role=t.role,
        version=t.version,
        full_version=t.full_version,
        status=t.status,
        owner=t.owner,
        description=t.description,
        has_day0=t.has_day0,
        required_vars=list(t.required_vars),
    )


@router.get("/me")
def me(principal: Principal = Depends(current_principal)) -> dict:
    return {"user": principal.user, "role": principal.role, "sites": list(principal.sites)}


@router.get("/templates", response_model=list[TemplateOut], summary="Golden template library")
def list_templates(
    vendor: str | None = None,
    role: str | None = None,
    principal: Principal = Depends(current_principal),
) -> list[TemplateOut]:
    items = library().templates.values()
    return [
        _template_out(t)
        for t in sorted(items, key=lambda t: t.key)
        if (not vendor or t.vendor == vendor) and (not role or t.role == role)
    ]


@router.get("/templates/{vendor}/{role}", summary="Template metadata and source")
def get_template(vendor: str, role: str, principal: Principal = Depends(current_principal)):
    t = library().template_for(vendor, role)
    if t is None:
        raise HTTPException(404, "template not found")
    return {
        **_template_out(t).model_dump(),
        "source": t.source(),
        "day0_source": t.source("day0.j2") if t.has_day0 else None,
        "example": t.example,
    }


@router.post("/templates/reload", summary="Reload templates, layers and catalog from disk")
def reload_templates(principal: Principal = Depends(require("maintainer"))) -> dict:
    lib = reload_library()
    return {"templates": len(lib.templates), "sites": len(lib.sites), "models": len(lib.models)}


@router.get("/catalog", summary="Sites, models and roles for the onboarding form")
def catalog(principal: Principal = Depends(current_principal)) -> dict:
    lib = library()
    return {
        "sites": [
            {"name": s.name, "market": s.market, "mgmt_prefix": s.mgmt_prefix, "description": s.description}
            for s in sorted(lib.sites.values(), key=lambda s: s.name)
            if principal.can_access(s.name)
        ],
        "models": [
            {"name": m.name, "vendor": m.vendor, "roles": list(m.roles), "description": m.description}
            for m in sorted(lib.models.values(), key=lambda m: (m.vendor, m.name))
        ],
        "roles": sorted({r for m in lib.models.values() for r in m.roles}),
        "states": [s.value for s in Status],
        "transitions": {k.value: sorted(v) for k, v in TRANSITIONS.items()},
    }


@router.get("/catalog/suggest", summary="Next free hostnames and management IPs")
def suggest_identities(
    site: str,
    role: str,
    count: int = Query(default=1, ge=1, le=256),
    session: Session = SessionDep,
    principal: Principal = Depends(current_principal),
) -> list[dict[str, str]]:
    lib = library()
    if site not in lib.sites:
        raise HTTPException(404, f"unknown site {site}")
    return suggest(lib, Claims.from_inventory(session), site=site, role=role, count=count)


@router.get("/compliance/rules", summary="Security baseline rules")
def compliance_rules(
    vendor: str | None = None, principal: Principal = Depends(current_principal)
) -> list[dict]:
    rules = compliance.rules_for(vendor) if vendor else compliance.load_rules()
    return [
        {
            "id": r.id,
            "title": r.title,
            "severity": r.severity,
            "vendors": list(r.vendors),
            "remediation": r.remediation,
            "check": r.spec,
        }
        for r in rules
    ]


@router.get("/devices", response_model=list[DeviceOut], summary="Built-in inventory")
def devices(
    site: str | None = None,
    status: str | None = None,
    session: Session = SessionDep,
    principal: Principal = Depends(current_principal),
) -> list[Device]:
    stmt = select(Device).order_by(Device.hostname)
    if site:
        stmt = stmt.where(Device.site == site)
    if status:
        stmt = stmt.where(Device.status == status)
    return [d for d in session.scalars(stmt).all() if principal.can_access(d.site)]


@router.get("/audit", response_model=list[AuditOut], summary="Audit trail")
def audit_log(
    onboarding_id: str | None = None,
    actor: str | None = None,
    limit: int = Query(default=100, le=1000),
    session: Session = SessionDep,
    principal: Principal = Depends(current_principal),
) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if onboarding_id:
        stmt = stmt.where(AuditEvent.onboarding_id == onboarding_id)
    if actor:
        stmt = stmt.where(AuditEvent.actor == actor)
    return list(session.scalars(stmt).all())


@router.get("/stats", summary="Dashboard KPIs")
def stats(session: Session = SessionDep, principal: Principal = Depends(current_principal)):
    by_status = dict(
        session.execute(select(Onboarding.status, func.count()).group_by(Onboarding.status)).all()
    )
    by_vendor = dict(
        session.execute(select(Onboarding.vendor, func.count()).group_by(Onboarding.vendor)).all()
    )
    by_market = dict(
        session.execute(select(Onboarding.market, func.count()).group_by(Onboarding.market)).all()
    )
    completed = session.scalars(select(Onboarding).where(Onboarding.status == Status.COMPLETED.value)).all()
    durations = sorted(
        (ob.completed_at - ob.created_at).total_seconds()
        for ob in completed
        if ob.completed_at and ob.created_at
    )
    median = durations[len(durations) // 2] if durations else None
    total_rules = session.scalar(select(func.count(ComplianceResult.id))) or 0
    passed_rules = (
        session.scalar(select(func.count(ComplianceResult.id)).where(ComplianceResult.passed.is_(True))) or 0
    )
    since = utcnow() - timedelta(days=7)
    stage_failures = dict(
        session.execute(
            select(StageRun.stage, func.count())
            .where(StageRun.status == "failed", StageRun.started_at >= since)
            .group_by(StageRun.stage)
        ).all()
    )
    total = sum(by_status.values())
    first_time = sum(1 for ob in completed if ob.attempt == 1)
    return {
        "total": total,
        "by_status": by_status,
        "by_vendor": by_vendor,
        "by_market": by_market,
        "in_flight": sum(v for k, v in by_status.items() if Status(k) in RUNNING),
        "completed": len(completed),
        "median_seconds_to_complete": median,
        "first_time_right_rate": (first_time / len(completed)) if completed else None,
        "compliance_pass_rate": (passed_rules / total_rules) if total_rules else None,
        "stage_failures_7d": stage_failures,
        "active_devices": session.scalar(select(func.count(Device.id)).where(Device.status == "active")) or 0,
    }
