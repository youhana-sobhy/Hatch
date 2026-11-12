# Architecture

Hatch is three deployable components plus a body of governed content.

| Component | Tech | Responsibility | State |
|---|---|---|---|
| **Orchestrator** | Python 3.11+, FastAPI, SQLAlchemy 2, Jinja2 | REST + WebSocket API, RBAC, validation, approval policy, state machine, pipeline engine, rendering, compliance, secrets, integrations | PostgreSQL (SQLite for dev/tests), git backup store |
| **ZTP edge service** | Python, FastAPI, httpx | Vendor-native Day-0 bootstraps, call-home relay, image server, per-IP rate limiting | none |
| **UI** | React 18, TypeScript (strict), Vite, nginx | Forms, bulk import, preview/diff, approvals, live status, compliance evidence, reports, audit | none (token in local storage) |
| **Content** | YAML + Jinja2 in git | Golden templates, variable layers, device catalog, compliance rules, pipelines, approval policy | the repo |

```mermaid
flowchart TB
    subgraph orchestrator[Orchestrator]
        direction TB
        api[api/ · onboardings, ztp, catalog, system]
        svc[core/onboarding.py · use-cases]
        sm[core/state_machine.py]
        pipe[core/pipeline.py]
        worker[core/worker.py]
        render[core/rendering.py + content.py]
        val[core/validation.py + policies.py]
        comp[core/compliance.py]
        sec[core/secrets.py]
        drivers[drivers/ · simulated, ssh]
        integ[integrations/ · backups, vault, webhooks]
        api --> svc
        svc --> val
        svc --> sm
        svc -->|after commit| worker
        worker --> pipe
        pipe --> sm
        pipe --> render
        pipe --> comp
        pipe --> drivers
        pipe --> integ
        render --> sec
    end
```

## Layers

* **`api/`** is thin: parse, authenticate, call a use-case, commit, serialise. Errors from the
  core map to HTTP status codes (`ValidationFailed` → 422, `ActionRefused` → 403/409,
  `InvalidTransition` → 409).
* **`core/onboarding.py`** holds every use-case (`create`, `create_batch`, `dry_run`,
  `preview`, `approve`, `retry`, `rollback`, `cancel`, `bootstrap`, `callhome`). It is the only
  place that decides *what* should happen.
* **`core/state_machine.py`** is the only place that changes `Onboarding.status`.
  `transition()` checks the edge, records an `AuditEvent`, flushes and publishes an event.
* **`core/pipeline.py`** executes stages. It never talks to a device directly; it calls a
  `DeviceDriver`.
* **`drivers/`** are the only code that talks to devices. The simulated driver is a
  thread-safe in-memory fleet; the SSH driver uses per-vendor command profiles.

## Data model

```mermaid
erDiagram
    ONBOARDING ||--o{ STAGE_RUN : has
    ONBOARDING ||--o{ COMPLIANCE_RESULT : has
    ONBOARDING ||--o{ AUDIT_EVENT : "is audited by"
    ONBOARDING ||--o| DEVICE : registers
    ONBOARDING ||--o{ CONFIG_BACKUP : produces

    ONBOARDING {
        string id PK
        string hostname
        string serial
        string vendor
        string model
        string role
        string site
        string market
        string mode "ztp | push"
        string mgmt_ip
        json attributes "uplinks, vars, simulate"
        string template_key
        string template_version "semver+content hash"
        string rendered_sha256
        string status
        string failed_stage
        int attempt
        string requested_by
        string approved_by
        string ztp_token_hash "sha256, one-time"
        datetime ztp_token_expires_at
    }
    STAGE_RUN {
        int id PK
        string stage
        int attempt
        string status "running | succeeded | failed | skipped"
        string job_ref
        text output "redacted"
        json details
    }
    COMPLIANCE_RESULT {
        string rule_id
        string severity
        bool passed
        text evidence "redacted"
        int attempt
    }
    AUDIT_EVENT {
        datetime at
        string actor
        string action
        string from_status
        string to_status
        json detail
    }
    DEVICE {
        string hostname UK
        string serial UK
        string mgmt_ip UK
        string status "planned | active"
        bool monitored
    }
    SECRET_RECORD {
        string path PK
        text ciphertext "Fernet"
    }
    CONFIG_BACKUP {
        int version "0 = pre-change snapshot"
        string sha256
        string location
    }
```

`Device` doubles as the built-in source of truth and as the uniqueness guard: hostname, serial
and management IP each have a unique constraint, rows are created as `planned` at
registration and released on cancel or rollback.

## Request flow: push-mode onboarding

```mermaid
sequenceDiagram
    autonumber
    actor Eng as Engineer
    participant UI
    participant API as Orchestrator API
    participant W as Worker
    participant D as Device driver
    participant G as Git backups

    Eng->>UI: fill form, "Validate and preview"
    UI->>API: POST /onboardings/dry-run
    API-->>UI: validation report + rendered config (placeholders) + diff
    Eng->>UI: Submit
    UI->>API: POST /onboardings
    API->>API: validate · test render · REGISTERED → VALIDATED → APPROVED (policy)
    API-->>UI: 201 (pipeline queued after commit)
    API--)W: submit(onboarding)
    W->>D: probe (reachability, serial, model) · snapshot running config
    W->>W: render with live secrets (redactor primed)
    W->>D: apply config
    W->>D: post-checks
    W->>D: read running config → compliance scan (gate)
    W->>G: commit backup (secrets masked)
    W->>API: inventory active · monitoring webhook · report
    W--)UI: WebSocket events at every transition and stage
```

## Request flow: zero-touch

```mermaid
sequenceDiagram
    autonumber
    participant Dev as New device
    participant DHCP
    participant Z as ZTP edge service
    participant API as Orchestrator
    participant W as Worker

    Note over API: onboarding is WAITING_FOR_DEVICE (pre-registered serial)
    Dev->>DHCP: DHCP discover
    DHCP-->>Dev: IP + bootstrap URL (option 67 / 43 / 150)
    Dev->>Z: GET /poap/{serial}.py
    Z->>API: GET /api/v1/ztp/bootstrap/{serial} (service token, X-Client-IP)
    API->>API: mint one-time token (store sha256 + expiry) · render day0.j2
    API-->>Z: Day-0 with call-home URL + token
    Z-->>Dev: vendor-native Day-0
    Dev->>Dev: apply minimal Day-0 (mgmt IP, route, SSH)
    Dev->>Z: POST /callhome {serial, token, model}
    Z->>API: POST /api/v1/ztp/callhome
    API->>API: verify token (constant-time) · expiry · model · consume token
    API->>API: WAITING_FOR_DEVICE → DAY0_APPLIED · queue pipeline
    API--)W: run Day-1 pipeline (same as push mode)
```

## Key design decisions

**One write path for status.** Bugs in workflow systems usually come from status being set
in many places. Here it is set in exactly one function, and the transition table is data that
tests and docs can read.

**Queue after commit.** `schedule()` stores pipeline requests in `session.info`; an
SQLAlchemy `after_commit` hook submits them. A worker therefore never races a row that is not
yet visible, and a rolled-back request never starts a pipeline.

**One transaction per stage.** Progress is visible live, a crash loses at most one stage,
and every stage leaves a `StageRun` row even when it fails.

**Prime the redactor before anything runs.** At the start of every run (including a resumed
one) Hatch renders the config once with live secrets purely to register their values with the
redactor. Even a retry that starts at `compliance_scan` therefore masks secrets in its output.

**Content-addressed template versions.** `1.4.0+522f278f14` combines the declared semantic
version with a hash of every file in the template directory, so "which config was applied" is
unambiguous even if someone forgets to bump the version.

**Pluggable at the edges, simple in the middle.** Drivers, secret backends and outbound
integrations are interfaces with small, swappable implementations. The core has no vendor
SDKs and no dependency on any external automation platform.

**A real simulator, not mocks.** The virtual fleet behaves like devices where it matters
(running config replaced on apply, checks derived from the config, faults injectable), which
lets the same end-to-end tests run on a laptop, in CI and in a demo.

## Scaling notes

The orchestrator runs pipelines in-process on a bounded thread pool, which comfortably handles
refresh projects of hundreds of devices on one replica (pipelines are I/O-bound). Running
several replicas requires moving the queue out of process (see the roadmap); everything else
(state in Postgres, stateless ZTP and UI) already scales horizontally.
