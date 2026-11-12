# Security

## Goals

1. No secret is ever visible in the UI, the API, logs, reports, backups or the audit trail.
2. A device can only be configured from an approved golden template, with a recorded
   approver where policy demands one.
3. Every action is attributable: who requested, who approved, what template version and
   config hash was applied, and every check result.
4. A device on the management network can obtain nothing it was not meant to have.

## Secrets

* Templates reference secrets by path (`secret()`, `device_secret()`); the values live in the
  secret store. Two backends ship: **local** (Fernet-encrypted in Hatch's database, key from
  `HATCH_SECRET_KEY`) and **KV v2** over HTTP for an external secret engine.
* Per-device local credentials (admin, break-glass, root) are generated (24 characters,
  mixed classes) on first use and are unique per serial.
* Previews render placeholders and never read the store.
* In a pipeline run, every resolved value is registered with a `Redactor`, primed before the
  first stage. Stage output, compliance evidence, backups and diffs pass through it.
* `test_no_secret_is_visible_anywhere` reads the real TACACS+ key from the device and asserts
  it is absent from the detail, preview, HTML report, JSON report and audit endpoints.
* Production refuses to start without `HATCH_SECRET_KEY` and does not auto-generate missing
  shared secrets.

## Authentication and authorisation

* Bearer tokens map to a user, a role and a site scope (`HATCH_API_TOKENS`). Comparison is
  constant-time. Development tokens are disabled when `HATCH_ENV=prod`.
* Roles: `requester` (create, retry, rollback, cancel), `approver` (+ approve), `maintainer`
  (+ reload templates), `admin` (everything), `service` (ZTP endpoints only).
* Site scope filters every list and returns `404` for out-of-scope objects.
* Four-eyes: the approver must differ from the requester (`HATCH_ALLOW_SELF_APPROVAL` can relax
  this in a lab).

## Template governance

* Templates change through pull requests; `owner` in `template.yaml` names the reviewing team
  (map it to CODEOWNERS).
* CI test-renders every template and fails on any critical/high baseline finding.
* `status: draft` templates cannot be used unless explicitly allowed.
* The applied template identity includes a content hash, so the audit trail is exact.

## ZTP hardening

* Bootstrap only for pre-registered, approved serials; opaque `404` otherwise.
* Single-use, expiring call-home tokens, stored hashed, compared in constant time.
* Model must match registration.
* Minimal Day-0; management network only; the edge service is the only exposed surface and is
  rate-limited per IP. Use HTTPS wherever the platform supports it.

## Containers

* Non-root users (`10001`, `10002`), `allowPrivilegeEscalation: false`, all capabilities
  dropped, `RuntimeDefault` seccomp in the Helm chart.
* nginx sets `X-Content-Type-Options`, `X-Frame-Options` and `Referrer-Policy`.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
