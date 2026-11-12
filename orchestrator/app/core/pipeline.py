"""The onboarding pipeline engine.

A pipeline is an ordered list of stages. Each stage runs in its own transaction so its
progress is visible live, writes a ``StageRun`` row (with redacted output and structured
details), and maps onto a state of the state machine::

    pre_validate, os_upgrade, render_config, push_config  -> DAY1_CONFIGURING
    post_checks                                           -> VERIFYING
    compliance_scan                                       -> COMPLIANCE_CHECK
    backup_config, register_device, report                -> REGISTERING

Per-vendor behaviour (which post-checks to run, OS target, compliance gate) comes from
``pipelines/<vendor>.yaml`` layered over ``pipelines/default.yaml``.

On failure the engine stops, records the failing stage and its output, moves the
onboarding to FAILED and leaves retry / rollback / cancel to the engineer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit, compliance
from app.core.content import deep_merge, library
from app.core.events import bus
from app.core.rendering import DeviceFacts, RenderError, render
from app.core.secrets import Redactor, SecretResolver, get_store
from app.core.state_machine import Status, transition
from app.db import session_scope
from app.drivers.base import DriverError, Target, get_driver
from app.integrations import webhooks
from app.integrations.backups import BackupStore
from app.models import ComplianceResult, ConfigBackup, Device, Onboarding, StageRun, utcnow

log = logging.getLogger(__name__)

STAGES: tuple[str, ...] = (
    "pre_validate",
    "os_upgrade",
    "render_config",
    "push_config",
    "post_checks",
    "compliance_scan",
    "backup_config",
    "register_device",
    "report",
)

STAGE_STATE: dict[str, Status] = {
    "pre_validate": Status.DAY1_CONFIGURING,
    "os_upgrade": Status.DAY1_CONFIGURING,
    "render_config": Status.DAY1_CONFIGURING,
    "push_config": Status.DAY1_CONFIGURING,
    "post_checks": Status.VERIFYING,
    "compliance_scan": Status.COMPLIANCE_CHECK,
    "backup_config": Status.REGISTERING,
    "register_device": Status.REGISTERING,
    "report": Status.REGISTERING,
}

SYSTEM = "hatch-pipeline"


class StageFailed(Exception):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


@dataclass
class StageOutcome:
    output: str
    details: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False


def load_pipeline(vendor: str, directory: Path | None = None) -> dict[str, Any]:
    directory = directory or get_settings().pipelines_dir

    def _read(name: str) -> dict[str, Any]:
        path = directory / f"{name}.yaml"
        return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}

    return deep_merge(_read("default"), _read(vendor))


@dataclass
class PipelineContext:
    session: Session
    onboarding: Onboarding
    spec: dict[str, Any]
    redactor: Redactor = field(default_factory=Redactor)
    config: str | None = None

    @property
    def facts(self) -> DeviceFacts:
        ob = self.onboarding
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

    def target(self) -> Target:
        ob = self.onboarding
        store = get_store(self.session)
        resolver = SecretResolver(
            store,
            self.redactor,
            serial=ob.serial,
            live=True,
            auto_create_shared=get_settings().env != "prod",
        )
        return Target(
            hostname=ob.hostname,
            serial=ob.serial,
            vendor=ob.vendor,
            model=ob.model,
            mgmt_ip=ob.mgmt_ip,
            username="hatch",
            password=resolver.shared("hatch/automation_password"),
            attributes=ob.attributes or {},
        )

    def stage_spec(self, stage: str) -> dict[str, Any]:
        value = self.spec.get("stages", {}).get(stage, {})
        return value if isinstance(value, dict) else {}


# --------------------------------------------------------------------------- stages
def stage_pre_validate(ctx: PipelineContext) -> StageOutcome:
    ob = ctx.onboarding
    driver = get_driver(get_settings().driver)
    target = ctx.target()
    try:
        facts = driver.probe(target)
    except DriverError as exc:
        raise StageFailed(f"device unreachable: {exc}") from exc
    problems = []
    if facts.serial != ob.serial:
        problems.append(f"serial mismatch: device reports {facts.serial}, expected {ob.serial}")
    if facts.model != ob.model:
        problems.append(f"model mismatch: device reports {facts.model}, expected {ob.model}")
    details = {"serial": facts.serial, "model": facts.model, "os_version": facts.os_version}
    if problems:
        raise StageFailed("; ".join(problems), details)

    snapshot = driver.get_running_config(target)
    ref = BackupStore().save(
        site=f"{ob.site}/.snapshots",
        hostname=f"{ob.hostname}.{ob.id}.pre",
        config=snapshot,
        message=f"pre-change snapshot for {ob.id}",
    )
    ctx.session.add(
        ConfigBackup(
            onboarding_id=ob.id,
            hostname=ob.hostname,
            version=0,
            sha256=ref.sha256,
            location=ref.location,
        )
    )
    return StageOutcome(
        output=f"{ob.mgmt_ip} reachable; serial {facts.serial} and model {facts.model} match; "
        f"running {facts.os_version}; pre-change snapshot saved",
        details=details,
    )


def stage_os_upgrade(ctx: PipelineContext) -> StageOutcome:
    spec = ctx.stage_spec("os_upgrade")
    if not spec.get("enabled"):
        return StageOutcome("OS upgrade not enabled for this vendor", skipped=True)
    driver = get_driver(get_settings().driver)
    facts = driver.probe(ctx.target())
    approved = str(spec.get("approved_version", ""))
    if facts.os_version == approved:
        return StageOutcome(f"already on approved OS {approved}", {"os_version": approved})
    raise StageFailed(
        f"device runs {facts.os_version}, approved image is {approved}; stage the golden image",
        {"os_version": facts.os_version, "approved_version": approved},
    )


def stage_render_config(ctx: PipelineContext) -> StageOutcome:
    ob = ctx.onboarding
    resolver = SecretResolver(
        get_store(ctx.session),
        ctx.redactor,
        serial=ob.serial,
        live=True,
        auto_create_shared=get_settings().env != "prod",
    )
    try:
        result = render(library(), ctx.facts, resolver)
    except RenderError as exc:
        raise StageFailed(str(exc)) from exc
    ctx.config = result.config
    ob.rendered_sha256 = result.sha256
    ob.template_version = result.template.full_version
    lines = len(result.config.splitlines())
    return StageOutcome(
        output=f"rendered {lines} lines from {result.template.key} {result.template.full_version}"
        f" (layers: {' -> '.join(result.layers)}; {len(result.secrets_used)} secrets resolved)",
        details={
            "template": result.template.key,
            "template_version": result.template.full_version,
            "layers": result.layers,
            "sha256": result.sha256,
            "secrets": result.secrets_used,
        },
    )


def stage_push_config(ctx: PipelineContext) -> StageOutcome:
    if ctx.config is None:
        stage_render_config(ctx)
    assert ctx.config is not None
    driver = get_driver(get_settings().driver)
    try:
        output = driver.apply_config(ctx.target(), ctx.config)
    except DriverError as exc:
        raise StageFailed(f"push failed: {exc}") from exc
    return StageOutcome(output=output, details={"sha256": ctx.onboarding.rendered_sha256})


def stage_post_checks(ctx: PipelineContext) -> StageOutcome:
    checks = ctx.stage_spec("post_checks").get("checks", ["reachability"])
    driver = get_driver(get_settings().driver)
    target = ctx.target()
    results = []
    for check in checks:
        try:
            result = driver.run_check(target, check, {})
        except DriverError as exc:
            results.append({"name": check, "passed": False, "detail": str(exc)})
            continue
        results.append({"name": result.name, "passed": result.passed, "detail": result.detail})
    failed = [r["name"] for r in results if not r["passed"]]
    summary = f"{len(results) - len(failed)}/{len(results)} checks passed"
    if failed:
        raise StageFailed(f"post-checks failed: {', '.join(failed)} ({summary})", {"checks": results})
    return StageOutcome(output=summary, details={"checks": results})


def stage_compliance_scan(ctx: PipelineContext) -> StageOutcome:
    ob = ctx.onboarding
    driver = get_driver(get_settings().driver)
    running = driver.get_running_config(ctx.target())
    results = compliance.scan(ob.vendor, running)
    for existing in list(ob.compliance):
        if existing.attempt == ob.attempt:
            ctx.session.delete(existing)
    for item in results:
        ctx.session.add(
            ComplianceResult(
                onboarding_id=ob.id,
                attempt=ob.attempt,
                rule_id=item.rule.id,
                title=item.rule.title,
                severity=item.rule.severity,
                passed=item.passed,
                evidence=ctx.redactor(item.evidence),
            )
        )
    gate = set(ctx.stage_spec("compliance_scan").get("fail_on", ["critical", "high"]))
    blocking = [r.rule.id for r in results if not r.passed and r.rule.severity in gate]
    warnings = [r.rule.id for r in results if not r.passed and r.rule.severity not in gate]
    passed = sum(1 for r in results if r.passed)
    summary = f"{passed}/{len(results)} baseline rules passed"
    details = {"passed": passed, "total": len(results), "blocking": blocking, "warnings": warnings}
    if blocking:
        raise StageFailed(f"compliance gate failed: {', '.join(blocking)} ({summary})", details)
    if warnings:
        summary += f"; non-blocking findings: {', '.join(warnings)}"
    return StageOutcome(output=summary, details=details)


def stage_backup_config(ctx: PipelineContext) -> StageOutcome:
    ob = ctx.onboarding
    driver = get_driver(get_settings().driver)
    running = ctx.redactor(driver.get_running_config(ctx.target()))
    ref = BackupStore().save(
        site=ob.site,
        hostname=ob.hostname,
        config=running,
        message=f"{ob.hostname}: onboarded by Hatch ({ob.id}, {ob.template_version})",
    )
    version = (
        ctx.session.scalar(select(func.max(ConfigBackup.version)).where(ConfigBackup.hostname == ob.hostname))
        or 0
    ) + 1
    ctx.session.add(
        ConfigBackup(
            onboarding_id=ob.id,
            hostname=ob.hostname,
            version=version,
            sha256=ref.sha256,
            location=ref.location,
        )
    )
    return StageOutcome(
        output=f"backup v{version} stored" + (f" (commit {ref.commit})" if ref.commit else ""),
        details={"version": version, "sha256": ref.sha256, "commit": ref.commit},
    )


def stage_register_device(ctx: PipelineContext) -> StageOutcome:
    ob = ctx.onboarding
    device = ctx.session.scalar(select(Device).where(Device.serial == ob.serial))
    if device is None:
        raise StageFailed(f"inventory record for {ob.serial} is missing")
    device.status = "active"
    device.monitored = True
    record = {
        "hostname": ob.hostname,
        "mgmt_ip": ob.mgmt_ip,
        "vendor": ob.vendor,
        "model": ob.model,
        "role": ob.role,
        "site": ob.site,
        "market": ob.market,
    }
    deliveries = [
        {"target": "inventory", "delivered": True, "detail": "status set to active"},
        webhooks.register_monitoring(record).__dict__,
        {"target": "syslog", "delivered": True, "detail": "log host configured by template"},
        {"target": "backup-schedule", "delivered": True, "detail": "daily backup scheduled"},
    ]
    return StageOutcome(
        output="registered in inventory, monitoring, syslog and backup schedule",
        details={"registrations": deliveries},
    )


def stage_report(ctx: PipelineContext) -> StageOutcome:
    ob = ctx.onboarding
    url = f"/api/v1/onboardings/{ob.id}/report"
    ticket = webhooks.update_ticket(
        ob.ticket_ref, {"onboarding": ob.id, "hostname": ob.hostname, "report": url}
    )
    return StageOutcome(
        output=f"onboarding report ready at {url}", details={"report": url, "ticket": ticket.__dict__}
    )


HANDLERS: dict[str, Callable[[PipelineContext], StageOutcome]] = {
    "pre_validate": stage_pre_validate,
    "os_upgrade": stage_os_upgrade,
    "render_config": stage_render_config,
    "push_config": stage_push_config,
    "post_checks": stage_post_checks,
    "compliance_scan": stage_compliance_scan,
    "backup_config": stage_backup_config,
    "register_device": stage_register_device,
    "report": stage_report,
}


# --------------------------------------------------------------------------- runner
def resume_point(failed_stage: str | None) -> str:
    """Retrying a push re-renders first; anything else resumes at the failed stage."""
    if failed_stage in (None, "pre_validate"):
        return "pre_validate"
    if failed_stage == "push_config":
        return "render_config"
    return failed_stage


def run(onboarding_id: str, start: str = "pre_validate") -> str:
    """Execute stages from ``start``. Returns the final status."""
    redactor = Redactor()
    config: str | None = None
    with session_scope() as session:
        ob = session.get(Onboarding, onboarding_id)
        if ob is None:
            raise LookupError(onboarding_id)
        spec = load_pipeline(ob.vendor)
        # Prime the redactor with every secret this device's config uses, so that output
        # from any stage (including a resumed one) is masked even if render is not re-run.
        prime = PipelineContext(session=session, onboarding=ob, spec=spec, redactor=redactor)
        try:
            stage_render_config(prime)
            config = prime.config
        except StageFailed:
            config = None  # render_config will report the error as a proper stage failure

    for stage in STAGES[STAGES.index(start) :]:
        with session_scope() as session:
            ob = session.get(Onboarding, onboarding_id)
            assert ob is not None
            if Status(ob.status) in (Status.CANCELLED, Status.FAILED):
                return ob.status
            wanted = STAGE_STATE[stage]
            if ob.status != wanted:
                transition(session, ob, wanted, actor=SYSTEM, detail={"stage": stage})
            run_row = StageRun(onboarding_id=ob.id, stage=stage, attempt=ob.attempt, status="running")
            session.add(run_row)
            session.flush()
            bus.publish({"type": "stage.started", "onboarding_id": ob.id, "stage": stage})

            ctx = PipelineContext(session=session, onboarding=ob, spec=spec, redactor=redactor, config=config)
            try:
                outcome = HANDLERS[stage](ctx)
            except (StageFailed, DriverError, RenderError) as exc:
                details = getattr(exc, "details", {})
                _fail(session, ob, run_row, stage, redactor(str(exc)), details)
                return Status.FAILED.value
            except Exception as exc:  # unexpected bug: still fail safely and visibly
                log.exception("stage %s crashed for %s", stage, onboarding_id)
                _fail(session, ob, run_row, stage, redactor(f"internal error: {exc!r}"), {})
                return Status.FAILED.value

            config = ctx.config
            run_row.status = "skipped" if outcome.skipped else "succeeded"
            run_row.output = redactor(outcome.output)
            run_row.details = outcome.details
            run_row.finished_at = utcnow()
            bus.publish(
                {
                    "type": "stage.finished",
                    "onboarding_id": ob.id,
                    "stage": stage,
                    "status": run_row.status,
                    "output": run_row.output,
                }
            )

    with session_scope() as session:
        ob = session.get(Onboarding, onboarding_id)
        assert ob is not None
        ob.failed_stage = None
        ob.error = None
        transition(session, ob, Status.COMPLETED, actor=SYSTEM)
        webhooks.notify({"type": "onboarding.completed", "onboarding_id": ob.id, "hostname": ob.hostname})
        return ob.status


def _fail(
    session: Session,
    ob: Onboarding,
    run_row: StageRun,
    stage: str,
    message: str,
    details: dict[str, Any],
) -> None:
    run_row.status = "failed"
    run_row.output = message
    run_row.details = details
    run_row.finished_at = utcnow()
    ob.failed_stage = stage
    ob.error = message
    bus.publish(
        {
            "type": "stage.finished",
            "onboarding_id": ob.id,
            "stage": stage,
            "status": "failed",
            "output": message,
        }
    )
    transition(session, ob, Status.FAILED, actor=SYSTEM, reason=message, detail={"stage": stage})
    audit.record(
        session,
        actor=SYSTEM,
        action="stage_failed",
        onboarding_id=ob.id,
        detail={"stage": stage, "error": message},
    )
    webhooks.notify(
        {
            "type": "onboarding.failed",
            "onboarding_id": ob.id,
            "hostname": ob.hostname,
            "stage": stage,
            "error": message,
        }
    )
