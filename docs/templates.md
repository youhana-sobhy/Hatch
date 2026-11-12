# Golden templates

Golden templates are the single definition of how a device of a given **vendor × role** is
configured. They live in [`golden-templates/`](../golden-templates) and change only through reviewed pull
requests that CI has test-rendered.

## Layout

```
golden-templates/
├── _catalog/models.yaml            model → vendor family, allowed roles
├── _layers/
│   ├── global.yaml                 1. global baseline (naming, AAA, NTP, SNMP, banner, mgmt ACL)
│   ├── regions/<region>.yaml       2. region overrides (time zone, regional NTP/syslog/DNS)
│   ├── sites/<site>.yaml           3. site overrides + site metadata (region, mgmt prefix, gateway, naming)
│   └── roles/<role>.yaml           4. role defaults (VLANs, MTU, HA, zones)
└── <vendor>/<role>/
    ├── template.yaml               metadata: version, status, owner, required_vars, example fixture
    ├── config.j2                   Day-1 golden configuration
    └── day0.j2                     Day-0 bootstrap (required for ZTP)
```

The fifth layer, **device**, is the `vars` object on the onboarding request.

## Layering

Layers merge left to right with `deep_merge`: nested mappings merge, lists and scalars are
replaced. For `ams-dc1` (region `eu-west`), role `leaf`:

| Variable | global | eu-west | ams-dc1 | leaf | result |
|---|---|---|---|---|---|
| `timezone` | `UTC` | `Europe/Amsterdam` | | | `Europe/Amsterdam` |
| `ntp_servers` | `10.255.0.123, …` | `10.201.0.123, …` | | | region value |
| `snmp_location` | | | `AMS-DC1, Hall 2` | | site value |
| `vlans` | | | | `100, 110, 120, 900` | role value |

The preview and the `render_config` stage both report the layers that were applied.

## Context available to templates

* Every merged layer variable at the top level (`ntp_servers`, `aaa.tacacs_servers`, …).
* `device`: `hostname`, `serial`, `vendor`, `model`, `role`, `site`, `region`, `mode`,
  `mgmt_ip`, `mgmt_prefix`, `mgmt_prefixlen`, `mgmt_netmask`, `mgmt_gateway`, `uplinks`.
* `template`: `key`, `version`.
* `ztp` (Day-0 only): `callhome_url`, `token`, `serial`.
* Filters: `netmask`, `prefixlen`, `wildcard`, `network`.

Rendering uses `StrictUndefined`. A missing variable fails the request at registration
(test render) instead of producing a broken line on a device.

## Secrets

Never put a secret in a template, a layer or a request. Call:

| Function | Resolves to | Example |
|---|---|---|
| `secret('aaa/tacacs_key')` | a shared secret at that path | TACACS+ key, SNMPv3 keys, HA password |
| `device_secret('local_admin')` | a unique per-device value at `devices/<serial>/local_admin`, generated on first use | local admin, break-glass, root |

In previews these render as `{{ secret:aaa/tacacs_key }}`. In a pipeline run they resolve to
real values that are registered with the redactor and masked everywhere Hatch writes output.

## Metadata (`template.yaml`)

```yaml
version: 1.4.0               # bump on every change; the content hash is appended automatically
status: approved             # draft -> in_review -> approved; only approved templates onboard devices
owner: dc-network-platform   # the team that must review changes
description: NX-OS data-centre leaf (BGP underlay, VLANs, uplinks to spines)
required_vars: [ntp_servers, syslog_servers, aaa, snmp, vlans, mgmt_acl]
example:                     # fixture for the CI test render
  hostname: ams-dc1-leaf-01
  serial: FDO2401A1BC
  model: N9K-C93180YC-FX3
  site: ams-dc1
  mgmt_ip: 10.201.10.21
  uplinks: [...]
  vars: {bgp_asn: 65101, loopback0: 10.250.1.21}
```

The full version identity is `version + "+" + sha256(all files)[:10]`, for example
`1.4.0+522f278f14`. That string is stored on every onboarding and printed in the report.

## Governance

```bash
hatchctl templates lint                       # what CI runs
hatchctl templates render nxos/leaf           # render the example fixture
hatchctl templates render nxos/leaf --vars my-overrides.yaml --source day0.j2
hatchctl compliance check nxos running.cfg    # scan any config file
```

`templates lint` renders every template (and its Day-0) with its fixture and runs the
security baseline against the result. Any critical or high finding fails the build, so a
template change that would onboard a non-compliant device cannot merge.

## Adding a vendor or role

1. Add models to `_catalog/models.yaml` with their vendor family and allowed roles.
2. Create `golden-templates/<vendor>/<role>/` with `template.yaml`, `config.j2` and, for ZTP, `day0.j2`.
3. Add `compliance-rules/<vendor>.yaml` (the common rules apply automatically).
4. Add `pipelines/<vendor>.yaml` to choose post-checks and the approved OS image.
5. For real hardware, add a command profile to `drivers/ssh.py` (or a new driver).
6. Run `hatchctl templates lint` and `pytest`.
