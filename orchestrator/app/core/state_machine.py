"""The onboarding state machine.

Every status change in Hatch goes through :func:`transition`, which enforces the allowed
edges below, writes an audit event and publishes a live event. Nothing else mutates
``Onboarding.status``.

    REGISTERED -> VALIDATED -> [PENDING_APPROVAL] -> APPROVED
        -> WAITING_FOR_DEVICE -> DAY0_APPLIED (ZTP only)
        -> DAY1_CONFIGURING -> VERIFYING -> COMPLIANCE_CHECK -> REGISTERING -> COMPLETED
    any active state -> FAILED -> (retry | rollback | cancel)
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.orm import Session

from app.core import audit
from app.core.events import bus
from app.models import Onboarding, utcnow


class Status(StrEnum):
    REGISTERED = "REGISTERED"
    VALIDATED = "VALIDATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    WAITING_FOR_DEVICE = "WAITING_FOR_DEVICE"
    DAY0_APPLIED = "DAY0_APPLIED"
    DAY1_CONFIGURING = "DAY1_CONFIGURING"
    VERIFYING = "VERIFYING"
    COMPLIANCE_CHECK = "COMPLIANCE_CHECK"
    REGISTERING = "REGISTERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED = "CANCELLED"


TERMINAL: frozenset[Status] = frozenset({Status.COMPLETED, Status.ROLLED_BACK, Status.CANCELLED})

# States in which the pipeline is actively executing stages.
RUNNING: frozenset[Status] = frozenset(
    {
        Status.DAY1_CONFIGURING,
        Status.VERIFYING,
        Status.COMPLIANCE_CHECK,
        Status.REGISTERING,
    }
)

_CANCELLABLE = frozenset(
    {
        Status.REGISTERED,
        Status.VALIDATED,
        Status.PENDING_APPROVAL,
        Status.APPROVED,
        Status.WAITING_FOR_DEVICE,
        Status.FAILED,
    }
)

TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.REGISTERED: frozenset({Status.VALIDATED}),
    Status.VALIDATED: frozenset({Status.PENDING_APPROVAL, Status.APPROVED}),
    Status.PENDING_APPROVAL: frozenset({Status.APPROVED}),
    Status.APPROVED: frozenset({Status.WAITING_FOR_DEVICE, Status.DAY1_CONFIGURING}),
    Status.WAITING_FOR_DEVICE: frozenset({Status.DAY0_APPLIED}),
    Status.DAY0_APPLIED: frozenset({Status.DAY1_CONFIGURING}),
    Status.DAY1_CONFIGURING: frozenset({Status.VERIFYING}),
    Status.VERIFYING: frozenset({Status.COMPLIANCE_CHECK}),
    Status.COMPLIANCE_CHECK: frozenset({Status.REGISTERING}),
    Status.REGISTERING: frozenset({Status.COMPLETED}),
    # Retry resumes at the state that owns the failed stage; ZTP rollback re-arms Day-0.
    Status.FAILED: frozenset(
        {
            Status.DAY1_CONFIGURING,
            Status.VERIFYING,
            Status.COMPLIANCE_CHECK,
            Status.REGISTERING,
            Status.WAITING_FOR_DEVICE,
            Status.ROLLED_BACK,
        }
    ),
    Status.COMPLETED: frozenset(),
    Status.ROLLED_BACK: frozenset(),
    Status.CANCELLED: frozenset(),
}

# Every non-terminal state may fail; cancellable states may be cancelled.
for _state in Status:
    if _state not in TERMINAL and _state is not Status.FAILED:
        TRANSITIONS[_state] = TRANSITIONS[_state] | {Status.FAILED}
    if _state in _CANCELLABLE:
        TRANSITIONS[_state] = TRANSITIONS[_state] | {Status.CANCELLED}


class InvalidTransition(Exception):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"cannot move onboarding from {current} to {target}")
        self.current = current
        self.target = target


def can_transition(current: Status | str, target: Status | str) -> bool:
    return Status(target) in TRANSITIONS[Status(current)]


def transition(
    session: Session,
    onboarding: Onboarding,
    target: Status,
    *,
    actor: str,
    reason: str | None = None,
    detail: dict | None = None,
) -> None:
    current = Status(onboarding.status)
    if not can_transition(current, target):
        raise InvalidTransition(current, target)

    onboarding.status = target.value
    onboarding.updated_at = utcnow()
    if target is Status.COMPLETED:
        onboarding.completed_at = utcnow()

    payload = dict(detail or {})
    if reason:
        payload["reason"] = reason
    audit.record(
        session,
        actor=actor,
        action="transition",
        onboarding_id=onboarding.id,
        from_status=current.value,
        to_status=target.value,
        detail=payload,
    )
    session.flush()
    bus.publish(
        {
            "type": "onboarding.status",
            "onboarding_id": onboarding.id,
            "hostname": onboarding.hostname,
            "from": current.value,
            "to": target.value,
            "actor": actor,
            **({"reason": reason} if reason else {}),
        }
    )


def mermaid() -> str:
    """Render the transition table as a Mermaid state diagram (used by docs tooling)."""
    lines = ["stateDiagram-v2", "    [*] --> REGISTERED"]
    for source, targets in TRANSITIONS.items():
        for target in sorted(targets):
            lines.append(f"    {source.value} --> {target.value}")
    for terminal in sorted(TERMINAL):
        lines.append(f"    {terminal.value} --> [*]")
    return "\n".join(lines)
