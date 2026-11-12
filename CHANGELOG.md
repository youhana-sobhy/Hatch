# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-12

### Added

- Orchestrator: REST + WebSocket API, guarded onboarding state machine with audit trail,
  nine-stage pipeline engine with per-vendor configuration, retry from the failed stage,
  rollback to snapshot and ZTP reset.
- Layered golden templates (global, market, site, role, device) with content-addressed
  versions, strict rendering, preview and diff.
- Secret store (Fernet or KV v2), per-device generated credentials and output redaction.
- Compliance engine with 44 baseline rules across NX-OS, FortiOS, Junos, PAN-OS and ESXi.
- Validation (naming, IPAM, serial, catalog, template, test render), IPAM suggestions, CSV
  bulk import, approval policy with four-eyes, site-scoped RBAC.
- ZTP edge service with vendor-native Day-0, one-time call-home tokens and rate limiting.
- Simulated device fleet with fault injection and an experimental SSH driver.
- Git configuration backups, onboarding report (HTML/JSON), Prometheus metrics.
- React UI: dashboard, onboarding form and bulk import, live journey track, config preview,
  compliance evidence, audit log, inventory and template browser.
- `hatchctl` CLI, Docker Compose, Helm chart, CI and release workflows, documentation.
