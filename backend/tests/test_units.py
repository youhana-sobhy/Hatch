from app.api.onboardings import parse_uplinks
from app.core.content import library
from app.core.events import EventBus
from app.core.policies import approval_for
from app.core.secrets import generate_password
from app.core.validation import Claims, suggest, validate_request


def test_policy_first_match_wins():
    assert approval_for(
        region="eu-west", site="ams-dc1", role="border", vendor="nxos", mode="push"
    ).require_approval
    assert not approval_for(
        region="eu-west", site="ams-dc1", role="leaf", vendor="nxos", mode="push"
    ).require_approval
    decision = approval_for(region="me-north", site="cai-dc2", role="edge-fw", vendor="fortios", mode="ztp")
    assert decision.require_approval and decision.rule == "me-north-firewalls-need-approval"


def test_generated_passwords_are_strong_and_unique():
    values = {generate_password() for _ in range(50)}
    assert len(values) == 50
    assert all(len(v) == 24 for v in values)


def test_ip_rules():
    lib = library()
    kwargs = dict(
        hostname="ams-dc1-leaf-09",
        serial="ABCD1234",
        model="N9K-C93180YC-FX3",
        role="leaf",
        site="ams-dc1",
        mode="push",
    )
    for ip, message in [("10.201.10.0", "network"), ("10.201.10.1", "gateway"), ("10.201.11.5", "outside")]:
        report, _ = validate_request(lib, Claims(), mgmt_ip=ip, **kwargs)
        assert any(message in e["message"] for e in report.errors), ip


def test_ztp_requires_day0_and_hostname_must_match_site():
    lib = library()
    report, vendor = validate_request(
        lib,
        Claims(),
        hostname="fra-pop1-leaf-01",
        serial="ABCD1234",
        model="N9K-C93180YC-FX3",
        role="leaf",
        site="ams-dc1",
        mgmt_ip="10.201.10.50",
        mode="ztp",
    )
    assert vendor == "nxos"
    assert [e["field"] for e in report.errors] == ["hostname"]


def test_suggest_skips_claimed_identities():
    lib = library()
    claims = Claims(hostnames={"ams-dc1-leaf-01"}, ips={"10.201.10.10"})
    picks = suggest(lib, claims, site="ams-dc1", role="leaf", count=1)
    assert picks == [{"hostname": "ams-dc1-leaf-02", "mgmt_ip": "10.201.10.11"}]


def test_parse_uplinks():
    assert parse_uplinks("Eth1/49=spine-01:Eth1/1; Eth1/50=spine-02") == [
        {"interface": "Eth1/49", "peer": "spine-01", "peer_interface": "Eth1/1"},
        {"interface": "Eth1/50", "peer": "spine-02", "peer_interface": None},
    ]


def test_event_bus_history_and_listeners():
    bus = EventBus(history=2)
    seen = []
    bus.add_listener(seen.append)
    for i in range(3):
        bus.publish({"type": "t", "i": i})
    assert [e["i"] for e in bus.recent()] == [1, 2]
    assert len(seen) == 3
