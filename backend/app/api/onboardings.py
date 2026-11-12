"""/api/v1/onboardings: register, inspect and drive onboardings."""

from __future__ import annotations

import csv
import io
from typing import Literal

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, current_principal, require
from app.core import onboarding as svc
from app.core.content import library
from app.core.rendering import RenderError
from app.core.validation import Claims, suggest
from app.models import Onboarding
from app.reports import report
from app.schemas import (
    ActionResult,
    BatchResult,
    DryRun,
    OnboardingBatch,
    OnboardingCreate,
    OnboardingDetail,
    OnboardingOut,
    Page,
    Preview,
)

router = APIRouter(prefix="/api/v1/onboardings", tags=["onboardings"])


class ApproveBody(BaseModel):
    comment: str | None = None


class CancelBody(BaseModel):
    reason: str | None = None


def _get(session: Session, onboarding_id: str, principal: svc.Principal) -> Onboarding:
    ob = session.get(Onboarding, onboarding_id)
    if ob is None or not principal.can_access(ob.site):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "onboarding not found")
    return ob


def _detail(ob: Onboarding) -> OnboardingDetail:
    base = OnboardingOut.model_validate(ob).model_dump()
    return OnboardingDetail(
        **base,
        attributes={k: v for k, v in (ob.attributes or {}).items()},
        stages=ob.stages,  # type: ignore[arg-type]
        compliance=ob.compliance,  # type: ignore[arg-type]
        allowed_actions=svc.allowed_actions(ob),
    )


def _refused(exc: svc.ActionRefused) -> HTTPException:
    code = status.HTTP_403_FORBIDDEN if exc.forbidden else status.HTTP_409_CONFLICT
    return HTTPException(code, str(exc))


def _create_many(
    session: Session,
    requests: list[OnboardingCreate],
    principal: svc.Principal,
    *,
    strict_single: bool = True,
) -> BatchResult:
    try:
        batch_id, created, rejected = svc.create_batch(session, requests, principal)
    except svc.ActionRefused as exc:
        raise _refused(exc) from exc
    if strict_single and len(requests) == 1 and rejected:
        raise HTTPException(422, {"errors": rejected[0]["errors"]})
    session.commit()
    for ob in created:
        session.refresh(ob)
    return BatchResult(
        batch_id=batch_id,
        created=[OnboardingOut.model_validate(ob) for ob in created],
        rejected=rejected,
    )


@router.post(
    "",
    response_model=BatchResult,
    status_code=status.HTTP_201_CREATED,
    summary="Create one onboarding or a batch",
)
def create_onboardings(
    body: OnboardingCreate | OnboardingBatch = Body(...),
    session: Session = SessionDep,
    principal: svc.Principal = Depends(current_principal),
) -> BatchResult:
    requests = body.devices if isinstance(body, OnboardingBatch) else [body]
    return _create_many(session, requests, principal)


CSV_COLUMNS = ("hostname", "serial", "model", "role", "site", "mgmt_ip", "mode", "ticket_ref", "uplinks")


def parse_uplinks(raw: str) -> list[dict[str, str | None]]:
    """``Eth1/49=spine-01:Eth1/1;Eth1/50=spine-02:Eth1/1``"""
    uplinks = []
    for part in filter(None, (p.strip() for p in (raw or "").split(";"))):
        interface, _, peer = part.partition("=")
        peer_name, _, peer_if = peer.partition(":")
        uplinks.append(
            {
                "interface": interface.strip(),
                "peer": peer_name.strip() or None,
                "peer_interface": peer_if.strip() or None,
            }
        )
    return uplinks


@router.post(
    "/import",
    response_model=BatchResult,
    status_code=status.HTTP_201_CREATED,
    summary="Bulk import from CSV (blank hostname / mgmt_ip are auto-allocated)",
)
async def import_csv(
    file: UploadFile = File(...),
    session: Session = SessionDep,
    principal: svc.Principal = Depends(current_principal),
) -> BatchResult:
    text = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = {"serial", "model", "role", "site"} - set(reader.fieldnames or [])
    if missing:
        raise HTTPException(
            422, {"errors": [{"field": "csv", "message": f"missing columns: {sorted(missing)}"}]}
        )
    lib = library()
    claims = Claims.from_inventory(session)
    requests: list[OnboardingCreate] = []
    parse_errors = []
    for line, row in enumerate(reader, start=2):
        row = {k: (v or "").strip() for k, v in row.items() if k}
        if not row.get("hostname") or not row.get("mgmt_ip"):
            if row.get("site") in lib.sites:
                pick = suggest(lib, claims, site=row["site"], role=row.get("role", "x"), count=1)
                if pick:
                    row.setdefault("hostname", "")
                    row["hostname"] = row["hostname"] or pick[0]["hostname"]
                    row["mgmt_ip"] = row.get("mgmt_ip") or pick[0]["mgmt_ip"]
                    claims.hostnames.add(row["hostname"])
                    claims.ips.add(row["mgmt_ip"])
        try:
            requests.append(
                OnboardingCreate(
                    hostname=row.get("hostname", ""),
                    serial=row["serial"],
                    model=row["model"],
                    role=row["role"],
                    site=row["site"],
                    mgmt_ip=row.get("mgmt_ip", ""),
                    mode="ztp" if row.get("mode") == "ztp" else "push",
                    ticket_ref=row.get("ticket_ref") or None,
                    uplinks=parse_uplinks(row.get("uplinks", "")),  # type: ignore[arg-type]
                )
            )
        except ValidationError as exc:
            parse_errors.append(
                {
                    "index": line,
                    "hostname": row.get("hostname"),
                    "errors": [{"field": "row", "message": str(exc)}],
                }
            )
    if not requests:
        raise HTTPException(422, {"errors": parse_errors or [{"field": "csv", "message": "no rows"}]})
    result = _create_many(session, requests, principal, strict_single=False)
    result.rejected.extend(parse_errors)
    return result


@router.post("/dry-run", response_model=DryRun, summary="Validate and preview without creating")
def dry_run(
    body: OnboardingCreate,
    session: Session = SessionDep,
    principal: svc.Principal = Depends(current_principal),
) -> DryRun:
    return DryRun(**svc.dry_run(session, body))


@router.get("", response_model=Page, summary="List and filter onboardings")
def list_onboardings(
    session: Session = SessionDep,
    principal: svc.Principal = Depends(current_principal),
    site: str | None = None,
    region: str | None = None,
    vendor: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    mode: str | None = None,
    batch_id: str | None = None,
    q: str | None = Query(default=None, description="hostname / serial / IP contains"),
    limit: int = Query(default=50, le=500, ge=1),
    offset: int = Query(default=0, ge=0),
) -> Page:
    stmt = select(Onboarding)
    filters = {"site": site, "region": region, "vendor": vendor, "mode": mode, "batch_id": batch_id}
    for column, value in filters.items():
        if value:
            stmt = stmt.where(getattr(Onboarding, column) == value)
    if status_:
        stmt = stmt.where(Onboarding.status.in_(status_.split(",")))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Onboarding.hostname.ilike(like), Onboarding.serial.ilike(like), Onboarding.mgmt_ip.ilike(like)
            )
        )
    if "*" not in principal.sites:
        stmt = stmt.where(Onboarding.site.in_(principal.sites))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.order_by(Onboarding.created_at.desc()).limit(limit).offset(offset)).all()
    return Page(
        items=[OnboardingOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get(
    "/{onboarding_id}", response_model=OnboardingDetail, summary="Onboarding detail with stage history"
)
def get_onboarding(
    onboarding_id: str,
    session: Session = SessionDep,
    principal: svc.Principal = Depends(current_principal),
) -> OnboardingDetail:
    return _detail(_get(session, onboarding_id, principal))


@router.get(
    "/{onboarding_id}/preview",
    response_model=Preview,
    summary="Rendered golden config (secrets masked) and diff",
)
def preview(
    onboarding_id: str,
    session: Session = SessionDep,
    principal: svc.Principal = Depends(current_principal),
) -> Preview:
    ob = _get(session, onboarding_id, principal)
    try:
        return Preview(**svc.preview(session, svc.facts_from_onboarding(ob)))
    except RenderError as exc:
        raise HTTPException(422, str(exc)) from exc


def _act(session: Session, ob: Onboarding, message: str) -> ActionResult:
    session.commit()
    session.refresh(ob)
    return ActionResult(onboarding=OnboardingOut.model_validate(ob), message=message)


@router.post("/{onboarding_id}/approve", response_model=ActionResult)
def approve(
    onboarding_id: str,
    body: ApproveBody | None = None,
    session: Session = SessionDep,
    principal: svc.Principal = Depends(require("approver")),
) -> ActionResult:
    ob = _get(session, onboarding_id, principal)
    try:
        svc.approve(session, ob, principal, body.comment if body else None)
    except svc.ActionRefused as exc:
        raise _refused(exc) from exc
    return _act(session, ob, "approved")


@router.post("/{onboarding_id}/retry", response_model=ActionResult)
def retry(
    onboarding_id: str,
    session: Session = SessionDep,
    principal: svc.Principal = Depends(current_principal),
) -> ActionResult:
    ob = _get(session, onboarding_id, principal)
    try:
        start = svc.retry(session, ob, principal)
    except svc.ActionRefused as exc:
        raise _refused(exc) from exc
    return _act(session, ob, f"retrying from {start}")


@router.post("/{onboarding_id}/rollback", response_model=ActionResult)
def rollback(
    onboarding_id: str,
    session: Session = SessionDep,
    principal: svc.Principal = Depends(current_principal),
) -> ActionResult:
    ob = _get(session, onboarding_id, principal)
    try:
        message = svc.rollback(session, ob, principal)
    except svc.ActionRefused as exc:
        raise _refused(exc) from exc
    return _act(session, ob, message)


@router.post("/{onboarding_id}/cancel", response_model=ActionResult)
def cancel(
    onboarding_id: str,
    body: CancelBody | None = None,
    session: Session = SessionDep,
    principal: svc.Principal = Depends(current_principal),
) -> ActionResult:
    ob = _get(session, onboarding_id, principal)
    try:
        svc.cancel(session, ob, principal, body.reason if body else None)
    except svc.ActionRefused as exc:
        raise _refused(exc) from exc
    return _act(session, ob, "cancelled")


@router.get(
    "/{onboarding_id}/report", summary="Onboarding report (HTML or JSON)", response_class=HTMLResponse
)
def get_report(
    onboarding_id: str,
    format: Literal["html", "json"] = "html",
    session: Session = SessionDep,
    principal: svc.Principal = Depends(current_principal),
):
    ob = _get(session, onboarding_id, principal)
    data = report.build(session, ob)
    if format == "json":
        return JSONResponse(data)
    return HTMLResponse(
        report.render_html(data),
        headers={"Content-Disposition": f'inline; filename="hatch-{ob.hostname}.html"'},
    )
