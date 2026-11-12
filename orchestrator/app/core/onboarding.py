"""Onboarding use-cases: create, preview, approve, retry, rollback, cancel and ZTP.

The API layer is a thin shell over these functions. Pipelines are queued with
:func:`schedule`, which defers the actual start until the surrounding transaction commits,
so a worker never races a row that is not yet visible.
"""

from __future__ import annotations

import hashlib
import secrets as pysecrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.content import library
from app.core.pipeline import STAGE_STATE, resume_point
from app.core.policies import approval_for
from app.core.rendering import DeviceFacts, RenderError, render, unified_diff
from app.core.secrets import Redactor, SecretResolver, get_store
from app.core.state_machine import RUNNING, TERMINAL, Status, can_transition, transition
from app.core.validation import Claims, ValidationReport, validate_request
from app.core.worker import worker
from app.drivers.base import DriverError, Target, get_driver
from app.models import ConfigBackup, Device, Onboarding, utcnow
from app.schemas import OnboardingCreate


class ValidationFailed(Exception):
    def __init__(self, report: ValidationReport) -> None:
        super().__init__("validation failed")
        self.report = report


class ActionRefused(Exception):
    """The action is not allowed for this onboarding or this user (maps to HTTP 409/403)."""

    def __init__(self, message: str, *, forbidden: bool = False) -> None:
        super().__init__(message)
        self.forbidden = forbidden


@dataclass(frozen=True)
class Principal:
    user: str
    role: str
    sites: tuple[str, ...] = ("*",)

    def can_access(self, site: str) -> bool:
        return "*" in self.sites or site in self.sites

    def has(self, *roles: str) -> bool:
        return self.role == "admin" or self.role in roles


# --------------------------------------------------------------------------- scheduling
def schedule(session: Session, onboarding_id: str, start: str = "pre_validate") -> None:
    session.info.setdefault("hatch_pipelines", []).append((onboarding_id, start))


@event.listens_for(Session, "after_commit")
def _start_pipelines(session: Session) -> None:
    for onboarding_id, start in session.info.pop("hatch_pipelines", []):
        worker.submit(onboarding_id, start)


# --------------------------------------------------------------------------- helpers
def facts_from_request(req: OnboardingCreate, vendor: str, market: str) -> DeviceFacts:
    return DeviceFacts(
        hostname=req.hostname,
        serial=req.serial,
        vendor=vendor,
        model=req.model,
        role=req.role,
        site=req.site,
        market=market,
        mgmt_ip=req.mgmt_ip,
        mode=req.mode,
        attributes=attributes_from_request(req),
    )


def attributes_from_request(req: OnboardingCreate) -> dict:
    attrs: dict = {"uplinks": [u.model_dump(exclude_none=True) for u in req.uplinks]}
    if req.vars:
        attrs["vars"] = req.vars
    if req.simulate:
        attrs["simulate"] = req.simulate
    return attrs


def facts_from_onboarding(ob: Onboarding) -> DeviceFacts:
    return DeviceFacts(
        hostname=ob.hostname,
        serial=ob.serial,
        vendor=ob.vendor,
        model=ob.model,
        role=ob.role,
        site=ob.site,
        market=ob.market,
        mgmt_ip=ob.mgmt_ip,
        mode=ob.mode,
        attributes=ob.attributes or {},
    )


def allowed_actions(ob: Onboarding) -> list[str]:
    status = Status(ob.status)
    actions = []
    if status is Status.PENDING_APPROVAL:
        actions.append("approve")
    if status is Status.FAILED:
        actions += ["retry", "rollback"]
    if can_transition(status, Status.CANCELLED):
        actions.append("cancel")
    return actions


def _ensure_access(principal: Principal, ob: Onboarding) -> None:
    if not principal.can_access(ob.site):
        raise ActionRefused(f"no access to site {ob.site}", forbidden=True)


# --------------------------------------------------------------------------- preview
def preview(session: Session, facts: DeviceFacts, *, compare_running: bool = True) -> dict:
    """Render with secret placeholders and diff against what the device runs today."""
    lib = library()
    resolver = SecretResolver(None, Redactor(), serial=facts.serial, live=False, auto_create_shared=False)
    result = render(lib, facts, resolver)
    before, against = "", "empty configuration (device not reachable yet)"
    if compare_running and facts.mode == "push":
        try:
            target = Target(
                hostname=facts.hostname,
                serial=facts.serial,
                vendor=facts.vendor,
                model=facts.model,
                mgmt_ip=facts.mgmt_ip,
                attributes=facts.attributes,
            )
            driver = get_driver(get_settings().driver)
            if driver.name != "simulated" or _sim_exists(facts.mgmt_ip):
                # The running config holds real secrets: resolve them (never returned) only
                # so the redactor can mask them in the diff.
                redactor = Redactor()
                render(
                    lib,
                    facts,
                    SecretResolver(
                        get_store(session),
                        redactor,
                        serial=facts.serial,
                        live=True,
                        auto_create_shared=get_settings().env != "prod",
                    ),
                )
                before = redactor(driver.get_running_config(target))
                against = "current running configuration"
        except DriverError:
            pass
    elif facts.mode == "ztp" and result.template.has_day0:
        ztp_facts = DeviceFacts(**{**facts.__dict__})
        ztp_facts.attributes = {
            **facts.attributes,
            "vars": {
                **facts.attributes.get("vars", {}),
                "ztp": {
                    "callhome_url": f"{get_settings().public_ztp_url}/callhome",
                    "token": "{{ one-time-token }}",
                    "serial": facts.serial,
                },
            },
        }
        day0 = render(lib, ztp_facts, resolver, source="day0.j2")
        before, against = day0.config, "Day-0 bootstrap configuration"
    return {
        "template": result.template.key,
        "template_version": result.template.full_version,
        "layers": result.layers,
        "config": result.config,
        "diff": unified_diff(
            before, result.config, before_name=against, after_name=f"{facts.hostname} (golden)"
        ),
        "diff_against": against,
        "secrets": result.secrets_used,
        "sha256": result.sha256,
    }


def _sim_exists(mgmt_ip: str) -> bool:
    from app.drivers.simulated import FLEET

    return FLEET.get(mgmt_ip) is not None


def dry_run(session: Session, req: OnboardingCreate) -> dict:
    lib = library()
    report, vendor = validate_request(
        lib,
        Claims.from_inventory(session),
        hostname=req.hostname,
        serial=req.serial,
        model=req.model,
        role=req.role,
        site=req.site,
        mgmt_ip=req.mgmt_ip,
        mode=req.mode,
    )
    out: dict = {
        "valid": report.ok,
        "errors": report.errors,
        "warnings": report.warnings,
        "vendor": vendor,
        "requires_approval": None,
        "preview": None,
    }
    if report.ok and vendor:
        market = lib.sites[req.site].market
        out["requires_approval"] = approval_for(
            market=market, site=req.site, role=req.role, vendor=vendor, mode=req.mode
        ).require_approval
        try:
            out["preview"] = preview(session, facts_from_request(req, vendor, market))
        except RenderError as exc:
            out["valid"] = False
            out["errors"].append({"field": "template", "message": str(exc)})
    return out


# --------------------------------------------------------------------------- create
def create(
    session: Session,
    req: OnboardingCreate,
    principal: Principal,
    *,
    claims: Claims | None = None,
    batch_id: str | None = None,
) -> Onboarding:
    if not principal.has("requester", "approver", "maintainer"):
        raise ActionRefused("your role cannot request onboardings", forbidden=True)
    if not principal.can_access(req.site):
        raise ActionRefused(f"no access to site {req.site}", forbidden=True)

    lib = library()
    claims = claims if claims is not None else Claims.from_inventory(session)
    report, vendor = validate_request(
        lib,
        claims,
        hostname=req.hostname,
        serial=req.serial,
        model=req.model,
        role=req.role,
        site=req.site,
        mgmt_ip=req.mgmt_ip,
        mode=req.mode,
    )
    if not report.ok or vendor is None:
        raise ValidationFailed(report)

    market = lib.sites[req.site].market
    facts = facts_from_request(req, vendor, market)
    try:  # test render: a template that cannot render must never reach approval
        preview(session, facts, compare_running=False)
    except RenderError as exc:
        report.error("template", str(exc))
        raise ValidationFailed(report) from exc

    template = lib.template_for(vendor, req.role)
    assert template is not None
    ob = Onboarding(
        batch_id=batch_id,
        hostname=req.hostname,
        serial=req.serial,
        vendor=vendor,
        model=req.model,
        role=req.role,
        site=req.site,
        market=market,
        mode=req.mode,
        mgmt_ip=req.mgmt_ip,
        attributes=facts.attributes,
        template_key=template.key,
        template_version=template.full_version,
        status=Status.REGISTERED.value,
        requested_by=principal.user,
        ticket_ref=req.ticket_ref,
    )
    session.add(ob)
    session.flush()
    session.add(
        Device(
            hostname=ob.hostname,
            serial=ob.serial,
            mgmt_ip=ob.mgmt_ip,
            vendor=vendor,
            model=ob.model,
            role=ob.role,
            site=ob.site,
            market=market,
            status="planned",
            onboarding_id=ob.id,
        )
    )
    claims.hostnames.add(ob.hostname)
    claims.serials.add(ob.serial)
    claims.ips.add(ob.mgmt_ip)
    audit.record(
        session,
        actor=principal.user,
        action="created",
        onboarding_id=ob.id,
        to_status=ob.status,
        detail={
            "template": template.key,
            "version": template.full_version,
            "mode": ob.mode,
            "ticket": ob.ticket_ref,
            "batch": batch_id,
        },
    )

    transition(
        session,
        ob,
        Status.VALIDATED,
        actor="hatch-validator",
        detail={"checks": "naming, ipam, serial, catalog, template, test render"},
    )
    decision = approval_for(market=market, site=ob.site, role=ob.role, vendor=vendor, mode=ob.mode)
    ob.requires_approval = decision.require_approval
    if decision.require_approval:
        transition(
            session, ob, Status.PENDING_APPROVAL, actor="hatch-policy", detail={"policy": decision.rule}
        )
    else:
        ob.approved_by = f"policy:{decision.rule}"
        transition(
            session, ob, Status.APPROVED, actor="hatch-policy", detail={"policy": decision.rule, "auto": True}
        )
        _advance(session, ob, actor="hatch-policy")
    return ob


def create_batch(
    session: Session, requests: list[OnboardingCreate], principal: Principal
) -> tuple[str | None, list[Onboarding], list[dict]]:
    batch_id = f"bat_{uuid.uuid4().hex[:12]}" if len(requests) > 1 else None
    claims = Claims.from_inventory(session)
    created: list[Onboarding] = []
    rejected: list[dict] = []
    for index, req in enumerate(requests):
        try:
            with session.begin_nested():
                created.append(create(session, req, principal, claims=claims, batch_id=batch_id))
        except ValidationFailed as exc:
            rejected.append({"index": index, "hostname": req.hostname, "errors": exc.report.errors})
    return batch_id, created, rejected


def _advance(session: Session, ob: Onboarding, *, actor: str) -> None:
    """From APPROVED: ZTP waits for the device, push mode starts the pipeline."""
    if ob.mode == "ztp":
        transition(session, ob, Status.WAITING_FOR_DEVICE, actor=actor)
    else:
        schedule(session, ob.id)


# --------------------------------------------------------------------------- actions
def approve(session: Session, ob: Onboarding, principal: Principal, comment: str | None) -> None:
    _ensure_access(principal, ob)
    if not principal.has("approver"):
        raise ActionRefused("only approvers can approve onboardings", forbidden=True)
    if Status(ob.status) is not Status.PENDING_APPROVAL:
        raise ActionRefused(f"onboarding is {ob.status}, not PENDING_APPROVAL")
    if ob.requested_by == principal.user and not get_settings().allow_self_approval:
        raise ActionRefused("four-eyes policy: you cannot approve your own request", forbidden=True)
    ob.approved_by = principal.user
    transition(
        session, ob, Status.APPROVED, actor=principal.user, detail={"comment": comment} if comment else None
    )
    _advance(session, ob, actor=principal.user)


def retry(session: Session, ob: Onboarding, principal: Principal) -> str:
    _ensure_access(principal, ob)
    if not principal.has("requester", "approver", "maintainer"):
        raise ActionRefused("your role cannot retry onboardings", forbidden=True)
    if Status(ob.status) is not Status.FAILED:
        raise ActionRefused(f"only FAILED onboardings can be retried (is {ob.status})")
    if worker.is_running(ob.id):
        raise ActionRefused("a pipeline run is still in progress")
    start = resume_point(ob.failed_stage)
    ob.attempt += 1
    transition(
        session,
        ob,
        STAGE_STATE[start],
        actor=principal.user,
        reason=f"retry from {start}",
        detail={"attempt": ob.attempt},
    )
    schedule(session, ob.id, start)
    return start


def rollback(session: Session, ob: Onboarding, principal: Principal) -> str:
    _ensure_access(principal, ob)
    if not principal.has("requester", "approver", "maintainer"):
        raise ActionRefused("your role cannot roll back onboardings", forbidden=True)
    if Status(ob.status) is not Status.FAILED:
        raise ActionRefused(f"only FAILED onboardings can be rolled back (is {ob.status})")

    if ob.mode == "ztp":
        # ZTP: reset to Day-0 and wait for the device to call home again.
        if get_settings().driver == "simulated":
            from app.drivers.simulated import FLEET

            FLEET.remove(ob.mgmt_ip)
        ob.ztp_token_hash = None
        ob.attempt += 1
        transition(
            session, ob, Status.WAITING_FOR_DEVICE, actor=principal.user, reason="rollback: reset to Day-0"
        )
        return "device reset to Day-0; power-cycle it to start ZTP again"

    snapshot = session.scalar(
        select(ConfigBackup).where(ConfigBackup.onboarding_id == ob.id, ConfigBackup.version == 0)
    )
    message = "no change had been pushed; nothing to restore"
    if snapshot is not None and ob.failed_stage not in ("pre_validate", "os_upgrade", "render_config"):
        config = Path(snapshot.location).read_text(encoding="utf-8")
        target = Target(
            hostname=ob.hostname,
            serial=ob.serial,
            vendor=ob.vendor,
            model=ob.model,
            mgmt_ip=ob.mgmt_ip,
            attributes=ob.attributes or {},
        )
        try:
            get_driver(get_settings().driver).restore_config(target, config)
        except DriverError as exc:
            raise ActionRefused(f"rollback failed: {exc}") from exc
        message = "pre-change configuration restored"
    _release_inventory(session, ob)
    transition(session, ob, Status.ROLLED_BACK, actor=principal.user, reason=message)
    return message


def cancel(session: Session, ob: Onboarding, principal: Principal, reason: str | None) -> None:
    _ensure_access(principal, ob)
    status = Status(ob.status)
    if status in TERMINAL or status in RUNNING or not can_transition(status, Status.CANCELLED):
        raise ActionRefused(f"an onboarding in {ob.status} cannot be cancelled")
    if worker.is_running(ob.id):
        raise ActionRefused("a pipeline run is in progress")
    _release_inventory(session, ob)
    transition(session, ob, Status.CANCELLED, actor=principal.user, reason=reason)


def _release_inventory(session: Session, ob: Onboarding) -> None:
    device = session.scalar(select(Device).where(Device.onboarding_id == ob.id))
    if device is not None:
        session.delete(device)


# --------------------------------------------------------------------------- ZTP
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _waiting(session: Session, serial: str) -> Onboarding | None:
    return session.scalar(
        select(Onboarding).where(
            Onboarding.serial == serial, Onboarding.status == Status.WAITING_FOR_DEVICE.value
        )
    )


def bootstrap(session: Session, serial: str, client_ip: str | None) -> tuple[Onboarding, str]:
    """Render the Day-0 bootstrap for a pre-registered serial, embedding a fresh one-time
    call-home token. Unknown serials get nothing."""
    ob = _waiting(session, serial)
    if ob is None:
        raise LookupError(serial)
    token = pysecrets.token_urlsafe(24)
    ob.ztp_token_hash = _token_hash(token)
    ob.ztp_token_expires_at = utcnow() + timedelta(minutes=get_settings().ztp_token_ttl_minutes)

    lib = library()
    resolver = SecretResolver(
        get_store(session),
        Redactor(),
        serial=ob.serial,
        live=True,
        auto_create_shared=get_settings().env != "prod",
    )
    facts = facts_from_onboarding(ob)
    facts.attributes = {
        **facts.attributes,
        "vars": {
            **facts.attributes.get("vars", {}),
            "ztp": {
                "callhome_url": f"{get_settings().public_ztp_url}/callhome",
                "token": token,
                "serial": ob.serial,
            },
        },
    }
    day0 = render(lib, facts, resolver, source="day0.j2")
    audit.record(
        session,
        actor="ztp-service",
        action="ztp_bootstrap_served",
        onboarding_id=ob.id,
        detail={"client_ip": client_ip},
    )
    return ob, day0.config


def callhome(
    session: Session, payload_serial: str, token: str, ip: str | None, model: str | None
) -> Onboarding:
    ob = _waiting(session, payload_serial)
    if ob is None or not ob.ztp_token_hash:
        raise ActionRefused("unknown serial or no bootstrap issued", forbidden=True)
    expires = ob.ztp_token_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=utcnow().tzinfo)
    if not pysecrets.compare_digest(ob.ztp_token_hash, _token_hash(token)):
        raise ActionRefused("invalid call-home token", forbidden=True)
    if expires is not None and expires < utcnow():
        raise ActionRefused("call-home token expired", forbidden=True)
    if model and model != ob.model:
        raise ActionRefused(f"model mismatch: device is {model}, expected {ob.model}", forbidden=True)

    ob.ztp_token_hash = None  # one-time
    ob.discovered_ip = ip
    if get_settings().driver == "simulated":
        from app.drivers.simulated import power_on

        attributes = dict(ob.attributes or {})
        if ob.attempt > 1:  # injected faults are transient: a re-imaged device is healthy
            attributes.pop("simulate", None)
        power_on(
            Target(
                hostname=ob.hostname,
                serial=ob.serial,
                vendor=ob.vendor,
                model=ob.model,
                mgmt_ip=ob.mgmt_ip,
                attributes=attributes,
            )
        )
    transition(session, ob, Status.DAY0_APPLIED, actor=f"device:{ob.serial}", detail={"discovered_ip": ip})
    schedule(session, ob.id)
    return ob
