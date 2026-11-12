# Onboarding state machine

Source: [`backend/app/core/state_machine.py`](../backend/app/core/state_machine.py).
`hatchctl state-diagram` prints the full transition table as Mermaid.

## States

| State | Meaning | Who moves it on |
|---|---|---|
| `REGISTERED` | Row created, inventory claims taken | validator |
| `VALIDATED` | Naming, IPAM, serial, catalog, template and a test render all passed | policy |
| `PENDING_APPROVAL` | Approval policy matched; waiting for an approver | approver |
| `APPROVED` | Cleared to proceed | system |
| `WAITING_FOR_DEVICE` | ZTP only: Day-0 can be served to this serial | the device (call-home) |
| `DAY0_APPLIED` | ZTP only: device called home with a valid one-time token | pipeline |
| `DAY1_CONFIGURING` | `pre_validate`, `os_upgrade`, `render_config`, `push_config` | pipeline |
| `VERIFYING` | `post_checks` | pipeline |
| `COMPLIANCE_CHECK` | `compliance_scan` (the baseline gate) | pipeline |
| `HANDING_OVER` | `backup_config`, `hand_over`, `report` | pipeline |
| `COMPLETED` | In service: inventory active, monitored, backed up, report ready | terminal |
| `FAILED` | A stage failed; `failed_stage` and `error` say where and why | engineer |
| `ROLLED_BACK` | Pre-change configuration restored, identifiers released | terminal |
| `CANCELLED` | Abandoned before execution, identifiers released | terminal |

## Rules

* Every non-terminal state may move to `FAILED`.
* `REGISTERED`, `VALIDATED`, `PENDING_APPROVAL`, `APPROVED`, `WAITING_FOR_DEVICE` and
  `FAILED` may be cancelled. Running states cannot: you cannot cancel half a commit.
* Terminal states (`COMPLETED`, `ROLLED_BACK`, `CANCELLED`) have no exits.
* Every transition writes an `AuditEvent` (`actor`, `from_status`, `to_status`, `detail`)
  and publishes `onboarding.status` on the event bus.

## Retry semantics

`POST /onboardings/{id}/retry` increments `attempt` and resumes **at the failed stage**:

| Failed stage | Resumes at | Why |
|---|---|---|
| `pre_validate` | `pre_validate` | nothing was changed yet |
| `push_config` | `render_config` | the in-memory render is gone; re-render with the same layers and secrets |
| anything else | that stage | earlier stages already succeeded; config is not pushed twice |

Stage history is append-only: each attempt adds new `StageRun` rows, and compliance results
are kept per attempt.

## Rollback semantics

`POST /onboardings/{id}/rollback` is allowed from `FAILED`:

* **Push mode.** If the failure happened after `push_config`, the pre-change snapshot taken
  in `pre_validate` (stored as backup version 0) is restored through the driver. The inventory
  record is released so the same hostname, serial and IP can be used again. → `ROLLED_BACK`
* **ZTP.** The device is reset to Day-0: the token is cleared, `attempt` increments and the
  onboarding returns to `WAITING_FOR_DEVICE`. When the device boots again it receives a fresh
  bootstrap with a fresh token.

## Events

| Event | Payload |
|---|---|
| `onboarding.status` | `onboarding_id`, `hostname`, `from`, `to`, `actor`, optional `reason` |
| `stage.started` | `onboarding_id`, `stage` |
| `stage.finished` | `onboarding_id`, `stage`, `status`, `output` (redacted) |

Subscribe with `ws://<host>/api/v1/events?token=<api token>`.
