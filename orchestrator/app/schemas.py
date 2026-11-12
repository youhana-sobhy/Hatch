"""Pydantic request / response schemas for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Uplink(BaseModel):
    interface: str
    peer: str | None = None
    peer_interface: str | None = None


class OnboardingCreate(BaseModel):
    hostname: str = Field(examples=["ams-dc1-leaf-01"])
    serial: str = Field(examples=["FDO2401A1BC"])
    model: str = Field(examples=["N9K-C93180YC-FX3"])
    role: str = Field(examples=["leaf"])
    site: str = Field(examples=["ams-dc1"])
    mgmt_ip: str = Field(examples=["10.10.0.21"])
    mode: Literal["ztp", "push"] = "push"
    ticket_ref: str | None = None
    uplinks: list[Uplink] = Field(default_factory=list)
    vars: dict[str, Any] = Field(
        default_factory=dict, description="Device-specific variables (last template layer)."
    )
    simulate: dict[str, Any] | None = Field(
        default=None, description="Fault injection for the simulated driver (demo/testing)."
    )


class OnboardingBatch(BaseModel):
    devices: list[OnboardingCreate] = Field(min_length=1, max_length=1000)


class StageRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    attempt: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    job_ref: str
    output: str
    details: dict[str, Any]


class ComplianceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    title: str
    severity: str
    passed: bool
    evidence: str
    attempt: int


class OnboardingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_id: str | None
    hostname: str
    serial: str
    vendor: str
    model: str
    role: str
    site: str
    market: str
    mode: str
    mgmt_ip: str
    status: str
    failed_stage: str | None
    error: str | None
    attempt: int
    template_key: str
    template_version: str
    rendered_sha256: str | None
    requested_by: str
    approved_by: str | None
    requires_approval: bool
    ticket_ref: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class OnboardingDetail(OnboardingOut):
    attributes: dict[str, Any]
    stages: list[StageRunOut]
    compliance: list[ComplianceOut]
    allowed_actions: list[str]


class Page(BaseModel):
    items: list[OnboardingOut]
    total: int
    limit: int
    offset: int


class BatchResult(BaseModel):
    batch_id: str | None
    created: list[OnboardingOut]
    rejected: list[dict[str, Any]]


class ValidationIssue(BaseModel):
    field: str
    message: str


class Preview(BaseModel):
    template: str
    template_version: str
    layers: list[str]
    config: str
    diff: str
    diff_against: str
    secrets: list[str]
    sha256: str


class DryRun(BaseModel):
    valid: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    vendor: str | None
    requires_approval: bool | None
    preview: Preview | None


class ActionResult(BaseModel):
    onboarding: OnboardingOut
    message: str


class CallHome(BaseModel):
    serial: str
    token: str
    model: str | None = None
    ip: str | None = None
    os_version: str | None = None


class TemplateOut(BaseModel):
    key: str
    vendor: str
    role: str
    version: str
    full_version: str
    status: str
    owner: str
    description: str
    has_day0: bool
    required_vars: list[str]


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    actor: str
    action: str
    onboarding_id: str | None
    from_status: str | None
    to_status: str | None
    detail: dict[str, Any]


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hostname: str
    serial: str
    mgmt_ip: str
    vendor: str
    model: str
    role: str
    site: str
    market: str
    status: str
    monitored: bool
    onboarding_id: str | None
