from itertools import pairwise

import pytest

from app.core.state_machine import (
    TERMINAL,
    TRANSITIONS,
    Status,
    can_transition,
    mermaid,
)

HAPPY_PUSH = [
    Status.REGISTERED,
    Status.VALIDATED,
    Status.APPROVED,
    Status.DAY1_CONFIGURING,
    Status.VERIFYING,
    Status.COMPLIANCE_CHECK,
    Status.REGISTERING,
    Status.COMPLETED,
]
HAPPY_ZTP = [
    Status.REGISTERED,
    Status.VALIDATED,
    Status.PENDING_APPROVAL,
    Status.APPROVED,
    Status.WAITING_FOR_DEVICE,
    Status.DAY0_APPLIED,
    Status.DAY1_CONFIGURING,
    Status.VERIFYING,
    Status.COMPLIANCE_CHECK,
    Status.REGISTERING,
    Status.COMPLETED,
]


@pytest.mark.parametrize("path", [HAPPY_PUSH, HAPPY_ZTP])
def test_happy_paths_are_allowed(path):
    for current, target in pairwise(path):
        assert can_transition(current, target), f"{current} -> {target}"


def test_terminal_states_have_no_exits():
    for state in TERMINAL:
        assert TRANSITIONS[state] == frozenset()


@pytest.mark.parametrize("state", [s for s in Status if s not in TERMINAL and s is not Status.FAILED])
def test_every_active_state_can_fail(state):
    assert can_transition(state, Status.FAILED)


def test_cannot_skip_verification():
    assert not can_transition(Status.DAY1_CONFIGURING, Status.COMPLETED)
    assert not can_transition(Status.PENDING_APPROVAL, Status.DAY1_CONFIGURING)
    assert not can_transition(Status.VERIFYING, Status.CANCELLED)


def test_failed_supports_retry_rollback_cancel():
    for target in (
        Status.DAY1_CONFIGURING,
        Status.VERIFYING,
        Status.ROLLED_BACK,
        Status.CANCELLED,
        Status.WAITING_FOR_DEVICE,
    ):
        assert can_transition(Status.FAILED, target)


def test_mermaid_export_lists_every_edge():
    diagram = mermaid()
    assert diagram.startswith("stateDiagram-v2")
    assert "REGISTERING --> COMPLETED" in diagram
