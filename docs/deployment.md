# Deployment

## Docker Compose

```bash
docker compose up --build
```

| Service | Port | Notes |
|---|---|---|
| `ui` | 8080 | nginx serving the SPA, proxying `/api` (and the WebSocket) to the orchestrator |
| `orchestrator` | 8000 | API and OpenAPI docs at `/docs` |
| `ztp` | 8081 | edge service for devices |
| `postgres` | internal | state, audit and encrypted secrets |

Backups persist in the `backups` volume as a git repository (one file per device, one commit
per change).

## Kubernetes (Helm)

```bash
kubectl create namespace hatch
kubectl -n hatch create secret generic hatch-database --from-literal=url='postgresql+psycopg://hatch:***@postgres:5432/hatch'
kubectl -n hatch create secret generic hatch-secret-key --from-literal=key="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
kubectl -n hatch create secret generic hatch-api-tokens --from-file=tokens.json
kubectl -n hatch create secret generic hatch-ztp-token --from-literal=token='<the service token from tokens.json>'

helm install hatch deploy/helm/hatch -n hatch \
  --set ingress.enabled=true --set ingress.host=hatch.example.internal \
  --set orchestrator.publicZtpUrl=http://ztp.example.internal
```

`tokens.json`:

```json
[
  {"token": "<random>", "user": "jane.doe", "role": "requester", "sites": ["ams-dc1"]},
  {"token": "<random>", "user": "lead.eng", "role": "approver"},
  {"token": "<random>", "user": "ztp-service", "role": "service"}
]
```

The chart deploys the orchestrator (one replica, `Recreate`, PVC for backups, Prometheus
annotations), the ZTP service (`LoadBalancer` by default so the management network can reach
it) and the UI, plus an optional Ingress. Images are published to GHCR by the release workflow
on every `v*` tag.

## Configuration reference (orchestrator)

All variables are prefixed with `HATCH_`.

| Variable | Default | Purpose |
|---|---|---|
| `ENV` | `dev` | `dev`, `test` or `prod` (prod disables dev tokens and requires a secret key) |
| `DATABASE_URL` | `sqlite:///./hatch.db` | SQLAlchemy URL; use `postgresql+psycopg://…` in production |
| `TEMPLATES_DIR`, `COMPLIANCE_DIR`, `PIPELINES_DIR`, `POLICIES_FILE` | repo paths | governed content |
| `BACKUP_DIR` | `./var/backups` | git backup store |
| `EXECUTOR` | `thread` | `thread` (worker pool) or `inline` (tests) |
| `WORKERS` | `4` | concurrent pipeline runs |
| `DRIVER` | `simulated` | `simulated` or `ssh` |
| `SECRET_BACKEND` | `local` | `local` or `vault` (KV v2) |
| `SECRET_KEY` | | Fernet key for the local backend |
| `VAULT_ADDR`, `VAULT_TOKEN`, `VAULT_MOUNT` | | KV v2 backend |
| `API_TOKENS` | | JSON list of tokens (dev tokens when empty outside prod) |
| `ALLOW_SELF_APPROVAL` | `false` | relax four-eyes |
| `ALLOW_DRAFT_TEMPLATES` | `false` | allow `status: draft` templates |
| `NOTIFY_WEBHOOK_URL` | | completion / failure notifications |
| `MONITORING_WEBHOOK_URL` | | monitoring registration |
| `ITSM_WEBHOOK_URL` | | ticket updates |
| `PUBLIC_ZTP_URL` | `http://localhost:8081` | call-home URL embedded in Day-0 |
| `ZTP_TOKEN_TTL_MINUTES` | `240` | call-home token lifetime |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:8080` | browser origins |

ZTP edge service: `HATCH_ORCHESTRATOR_URL`, `HATCH_ZTP_SERVICE_TOKEN`, `HATCH_ZTP_IMAGE_DIR`,
`HATCH_ZTP_RATE_LIMIT`. UI container: `HATCH_API_UPSTREAM`.

## Operations

* **Health:** `/healthz` (liveness), `/readyz` (database).
* **Metrics:** `/metrics` for Prometheus.
* **Upgrades:** the schema is created on start-up; versioned migrations are on the roadmap.
* **Backups:** back up Postgres (state, audit, encrypted secrets) and the backup volume. Keep
  `HATCH_SECRET_KEY` in your secret manager; without it the stored secrets cannot be decrypted.
