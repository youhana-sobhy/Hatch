"""Append-only audit trail: who did what, to which onboarding, and when."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(
    session: Session,
    *,
    actor: str,
    action: str,
    onboarding_id: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor=actor,
        action=action,
        onboarding_id=onboarding_id,
        from_status=from_status,
        to_status=to_status,
        detail=detail or {},
    )
    session.add(event)
    return event
