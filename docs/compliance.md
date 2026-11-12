# Compliance

Every onboarding is scanned against the security baseline **on the device's actual running
configuration**, after post-checks and before the device is registered anywhere.

## Rule files

[`compliance/rules/`](../compliance/rules): `common.yaml` applies to every vendor, and
`<vendor>.yaml` applies to that vendor family. Rule ids must be unique across files.

```yaml
rules:
  - id: NXOS-SNMP-001
    title: No SNMPv1/v2c communities
    severity: high
    must_not_match: '^snmp-server community '
    remediation: Use SNMPv3 users (snmp.v3_user) only.
```

## Check types

Checks evaluate regular expressions line by line. A rule may combine several.

| Check | Passes when |
|---|---|
| `must_match: <regex>` | at least one line matches |
| `must_not_match: <regex>` | no line matches |
| `must_match_all: [<regex>, …]` | every regex matches at least one line |
| `count_at_least: {regex: <regex>, min: N}` | at least N lines match |

Evidence records the line that satisfied or violated the rule and is passed through the
redactor before it is stored.

## Severities and the gate

`critical`, `high`, `medium`, `low`. The pipeline's `compliance_scan` stage fails when any rule
whose severity is listed in `fail_on` fails (default `[critical, high]`, set in
[`pipelines/default.yaml`](../pipelines/default.yaml)). Other failures are recorded as
non-blocking findings and appear in the report.

## The shipped baseline

| Family | Highlights |
|---|---|
| common | no default credentials, legal banner, remote logging, hostname |
| NX-OS | TACACS+ group, AAA login with local fallback, no SNMP communities, SNMPv3 auth+priv, telnet off, VTY ACL, SSHv2, ≥2 NTP, exec timeout |
| FortiOS | TACACS+, telnet off, trusted hosts, admin timeout ≤15 min, SNMPv3 auth-priv, strong crypto, ≥2 NTP, HA |
| Junos | TACACS+ first in auth order, no root SSH, no telnet, RE protection filter, SNMPv3 privacy, ≥2 NTP |
| PAN-OS | TACACS+ profile in use, telnet/HTTP off, permitted IPs, SNMPv3, HA, primary+secondary NTP |
| ESXi | SSH disabled and firewalled, SNMPv3, NTP ≥2, remote syslog, shell timeout |

## Demo: the gate catching a bad override

The NX-OS leaf template allows a `legacy_snmp_community` device variable (the kind of
"temporary" exception that lingers). Onboard a leaf with
`"vars": {"legacy_snmp_community": "public", ...}` and the onboarding stops at
`compliance_scan` with `NXOS-SNMP-001` as the blocking finding and the offending line as
evidence. `tools/hatch_demo.py seed` includes this case.
