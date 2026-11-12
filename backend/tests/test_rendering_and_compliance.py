import pytest

from app.cli import main as hatchctl
from app.core import compliance
from app.core.content import deep_merge, library
from app.core.rendering import DeviceFacts, RenderError, render
from app.core.secrets import MASK, Redactor, SecretResolver


def _facts(**overrides) -> DeviceFacts:
    base = dict(
        hostname="ams-dc1-leaf-07",
        serial="FDO0000007",
        vendor="nxos",
        model="N9K-C93180YC-FX3",
        role="leaf",
        site="ams-dc1",
        region="eu-west",
        mgmt_ip="10.201.10.27",
        attributes={"vars": {"bgp_asn": 65107, "loopback0": "10.250.1.27"}, "uplinks": []},
    )
    base.update(overrides)
    return DeviceFacts(**base)


def _preview_resolver(serial="FDO0000007"):
    return SecretResolver(None, Redactor(), serial=serial, live=False, auto_create_shared=False)


def test_deep_merge_layers_override_scalars_and_merge_dicts():
    merged = deep_merge({"a": 1, "n": {"x": 1, "y": 2}, "l": [1]}, {"a": 2, "n": {"y": 3}, "l": [9]})
    assert merged == {"a": 2, "n": {"x": 1, "y": 3}, "l": [9]}


def test_layering_region_beats_global_and_site_supplies_location():
    result = render(library(), _facts(), _preview_resolver())
    assert "clock timezone Europe/Amsterdam" in result.config  # region layer
    assert "ntp server 10.201.0.123" in result.config  # region overrides global NTP
    assert "snmp-server location AMS-DC1, Hall 2" in result.config  # site layer
    assert "vlan 900" in result.config  # role layer
    assert result.layers == ["global", "regions/eu-west", "sites/ams-dc1", "roles/leaf", "device"]


def test_preview_never_contains_secret_values():
    result = render(library(), _facts(), _preview_resolver())
    assert "{{ secret:aaa/tacacs_key }}" in result.config
    assert "{{ device_secret:local_admin }}" in result.config
    assert "aaa/tacacs_key" in result.secrets_used


def test_missing_variable_is_a_hard_error():
    facts = _facts(attributes={"vars": {}, "uplinks": []})  # no bgp_asn / loopback0
    with pytest.raises(RenderError):
        render(library(), facts, _preview_resolver())


def test_redactor_masks_longest_values_first():
    redactor = Redactor()
    redactor.register("s3cret")
    redactor.register("s3cret-longer")
    assert redactor("a s3cret-longer b s3cret") == f"a {MASK} b {MASK}"


def test_every_golden_template_passes_its_baseline():
    assert hatchctl(["templates", "lint"]) == 0


def test_compliance_catches_snmp_community_override():
    facts = _facts(
        attributes={
            "vars": {"bgp_asn": 1, "loopback0": "10.250.1.27", "legacy_snmp_community": "public"},
            "uplinks": [],
        }
    )
    config = render(library(), facts, _preview_resolver()).config
    results = {r.rule.id: r for r in compliance.scan("nxos", config)}
    assert results["NXOS-SNMP-001"].passed is False
    assert "snmp-server community public" in results["NXOS-SNMP-001"].evidence


def test_compliance_rule_types():
    rules = compliance.load_rules()
    by_id = {r.id: r for r in rules}
    assert compliance.evaluate(by_id["NXOS-NTP-001"], "ntp server 1\n").passed is False
    assert compliance.evaluate(by_id["NXOS-NTP-001"], "ntp server 1\nntp server 2\n").passed
    assert compliance.evaluate(by_id["BASE-CRED-001"], "username admin password 0 cisco").passed is False
    assert compliance.evaluate(by_id["JUN-SNMP-001"], "privacy-aes128\n").passed is False


def test_vendor_rule_scoping():
    vendors_seen = {v for r in compliance.rules_for("fortios") for v in r.vendors}
    assert vendors_seen <= {"fortios"}
    assert any(r.id.startswith("BASE-") for r in compliance.rules_for("fortios"))
    assert not any(r.id.startswith("NXOS-") for r in compliance.rules_for("fortios"))
