"""ORM models: onboarding state, stage history, compliance evidence, audit and inventory."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Onboarding(Base):
    __tablename__ = "onboardings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("onb"))
    batch_id: Mapped[str | None] = mapped_column(String(32), index=True)

    hostname: Mapped[str] = mapped_column(String(128), index=True)
    serial: Mapped[str] = mapped_column(String(64), index=True)
    vendor: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(64))
    site: Mapped[str] = mapped_column(String(64), index=True)
    region: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(8))  # "ztp" | "push"
    mgmt_ip: Mapped[str] = mapped_column(String(64))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    template_key: Mapped[str] = mapped_column(String(128))
    template_version: Mapped[str] = mapped_column(String(64))
    rendered_sha256: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(32), index=True)
    failed_stage: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, default=1)

    requested_by: Mapped[str] = mapped_column(String(128))
    approved_by: Mapped[str | None] = mapped_column(String(128))
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    ticket_ref: Mapped[str | None] = mapped_column(String(64))

    ztp_token_hash: Mapped[str | None] = mapped_column(String(128))
    ztp_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_ip: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    stages: Mapped[list[StageRun]] = relationship(
        back_populates="onboarding", cascade="all, delete-orphan", order_by="StageRun.id"
    )
    compliance: Mapped[list[ComplianceResult]] = relationship(
        back_populates="onboarding", cascade="all, delete-orphan", order_by="ComplianceResult.id"
    )


class StageRun(Base):
    __tablename__ = "stage_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    onboarding_id: Mapped[str] = mapped_column(ForeignKey("onboardings.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16))  # running|succeeded|failed|skipped
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_ref: Mapped[str] = mapped_column(String(32), default=lambda: new_id("job"))
    output: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    onboarding: Mapped[Onboarding] = relationship(back_populates="stages")


class ComplianceResult(Base):
    __tablename__ = "compliance_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    onboarding_id: Mapped[str] = mapped_column(ForeignKey("onboardings.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    rule_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    severity: Mapped[str] = mapped_column(String(16))
    passed: Mapped[bool] = mapped_column(Boolean)
    evidence: Mapped[str] = mapped_column(Text, default="")

    onboarding: Mapped[Onboarding] = relationship(back_populates="compliance")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    onboarding_id: Mapped[str | None] = mapped_column(String(32), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Device(Base):
    """Built-in inventory / source of truth record for a device."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("dev"))
    hostname: Mapped[str] = mapped_column(String(128), unique=True)
    serial: Mapped[str] = mapped_column(String(64), unique=True)
    mgmt_ip: Mapped[str] = mapped_column(String(64), unique=True)
    vendor: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(64))
    site: Mapped[str] = mapped_column(String(64))
    region: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="planned")  # planned|active
    onboarding_id: Mapped[str | None] = mapped_column(String(32))
    monitored: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SecretRecord(Base):
    __tablename__ = "secrets"

    path: Mapped[str] = mapped_column(String(256), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ConfigBackup(Base):
    __tablename__ = "config_backups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    onboarding_id: Mapped[str] = mapped_column(String(32), index=True)
    hostname: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    location: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
