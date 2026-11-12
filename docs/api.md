# API reference

Base URL `http://localhost:8000`. Interactive OpenAPI docs at `/docs`, schema at
`/openapi.json`. Every `/api/v1` endpoint requires `Authorization: Bearer <token>`.

Development tokens: `dev-requester`, `dev-approver`, `dev-maintainer`, `dev-admin`,
`dev-ztp-service`. In production set `HATCH_API_TOKENS` (see [deployment](deployment.md)).

## Errors

| Status | When | Body |
|---|---|---|
| `401` | missing or unknown token | `{"detail": "missing or invalid API token"}` |
| `403` | role or site scope not allowed, four-eyes, bad ZTP token | `{"detail": "..."}` |
| `404` | unknown id, or a site outside your scope | `{"detail": "onboarding not found"}` |
| `409` | action not allowed in the current state | `{"detail": "only FAILED onboardings can be retried (is COMPLETED)"}` |
| `422` | validation failed | `{"detail": {"errors": [{"field": "mgmt_ip", "message": "..."}]}}` |

## Onboardings

### Create

```http
POST /api/v1/onboardings
Content-Type: application/json

{
  "hostname": "ams-dc1-leaf-01",
  "serial": "FDO2401A1BC",
  "model": "N9K-C93180YC-FX3",
  "role": "leaf",
  "site": "ams-dc1",
  "mgmt_ip": "10.201.10.21",
  "mode": "push",
  "ticket_ref": "CHG-20431",
  "uplinks": [
    {"interface": "Ethernet1/49", "peer": "ams-dc1-spine-01", "peer_interface": "Ethernet1/1"}
  ],
  "vars": {"bgp_asn": 65101, "loopback0": "10.250.1.21"}
}
```

`201 Created`:

```json
{
  "batch_id": null,
  "created": [{"id": "onb_d8d6616f74b1", "status": "APPROVED", "template_version": "1.4.0+522f278f14", "...": "..."}],
  "rejected": []
}
```

Send `{"devices": [ ... ]}` for a batch. A batch is processed row by row in savepoints:
valid rows are created, invalid rows come back in `rejected` with their index and errors.

`simulate` (optional) injects faults into the simulated driver, for demos and tests:
`{"fail_check": "ntp_synced", "fail_times": 1}`, `{"fail_stage": "push_config"}`,
`{"wrong_serial": true}`.

### Bulk import (CSV)

```bash
curl -H "Authorization: Bearer dev-requester" -F file=@devices.csv \
  localhost:8000/api/v1/onboardings/import
```

Columns: `serial,model,role,site` (required) and `hostname,mgmt_ip,mode,ticket_ref,uplinks`.
Blank `hostname` / `mgmt_ip` are allocated from the site naming pattern and management prefix.
`uplinks` is `Eth1/49=spine-01:Eth1/1;Eth1/50=spine-02:Eth1/1`.

### Dry run

`POST /api/v1/onboardings/dry-run` takes the same body as create and returns
`{valid, errors, warnings, vendor, requires_approval, preview}` without creating anything.

### List

`GET /api/v1/onboardings?status=FAILED,PENDING_APPROVAL&site=ams-dc1&q=leaf&limit=50&offset=0`

Filters: `site`, `market`, `vendor`, `status` (comma-separated), `mode`, `batch_id`, `q`
(hostname, serial or IP contains). Returns `{items, total, limit, offset}`.

### Detail

`GET /api/v1/onboardings/{id}` adds `attributes`, `stages` (every `StageRun`, all attempts),
`compliance` and `allowed_actions` (for example `["retry", "rollback", "cancel"]`).

### Preview

`GET /api/v1/onboardings/{id}/preview`

```json
{
  "template": "nxos/leaf",
  "template_version": "1.4.0+522f278f14",
  "layers": ["global", "markets/eu-west", "sites/ams-dc1", "roles/leaf", "device"],
  "config": "hostname ams-dc1-leaf-01\n...tacacs-server host 10.255.0.49 key 0 {{ secret:aaa/tacacs_key }}\n...",
  "diff": "--- current running configuration\n+++ ams-dc1-leaf-01 (golden)\n@@ ...",
  "diff_against": "current running configuration",
  "secrets": ["aaa/tacacs_key", "devices/FDO2401A1BC/local_admin", "snmp/v3_auth", "snmp/v3_priv"],
  "sha256": "..."
}
```

### Actions

| Endpoint | Body | Role |
|---|---|---|
| `POST /{id}/approve` | `{"comment": "..."}` optional | approver, admin (not the requester) |
| `POST /{id}/retry` | none | requester, approver, maintainer, admin |
| `POST /{id}/rollback` | none | requester, approver, maintainer, admin |
| `POST /{id}/cancel` | `{"reason": "..."}` optional | any role with site access |

Each returns `{"onboarding": {...}, "message": "retrying from post_checks"}`.

### Report

`GET /api/v1/onboardings/{id}/report` returns a print-ready HTML report;
`?format=json` returns the same data: device, template version, config hash, every stage,
post-check results, compliance results with evidence, backups and the audit trail.

## ZTP (service role only)

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/ztp/bootstrap/{serial}` | Day-0 for a serial in `WAITING_FOR_DEVICE`. Mints a fresh one-time token. `404` for anything else. Headers: `X-Hatch-Onboarding`, `X-Hatch-Vendor`. |
| `POST /api/v1/ztp/callhome` | `{"serial", "token", "model"?, "ip"?}`. Verifies and consumes the token, moves to `DAY0_APPLIED`, queues the pipeline. |

Devices never call these directly; they call the [ZTP edge service](ztp.md).

## Catalog, inventory, audit

| Endpoint | Returns |
|---|---|
| `GET /api/v1/me` | your user, role and site scope |
| `GET /api/v1/catalog` | sites, models (vendor, allowed roles), roles, states, transitions |
| `GET /api/v1/catalog/suggest?site=&role=&count=` | next free `{hostname, mgmt_ip}` pairs |
| `GET /api/v1/templates[?vendor=&role=]` | template metadata |
| `GET /api/v1/templates/{vendor}/{role}` | metadata, `source`, `day0_source`, `example` |
| `POST /api/v1/templates/reload` | reload content from disk (maintainer) |
| `GET /api/v1/compliance/rules[?vendor=]` | baseline rules |
| `GET /api/v1/devices[?site=&status=]` | inventory |
| `GET /api/v1/audit[?onboarding_id=&actor=&limit=]` | audit events, newest first |
| `GET /api/v1/stats` | KPIs: totals by status/vendor/market, median time to complete, first-time-right rate, compliance pass rate, stage failures (7 days), active devices |

## System

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | liveness |
| `GET /readyz` | readiness (database round-trip) |
| `GET /metrics` | Prometheus: `hatch_onboardings{status}`, `hatch_stage_runs_total{stage,result}`, `hatch_compliance_results_total{result}` |
| `WS /api/v1/events?token=` | live events (see [state machine](state-machine.md#events)) |
