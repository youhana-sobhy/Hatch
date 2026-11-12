"""Sites, IPAM ranges and template test renders."""

from conftest import auth


def test_sites_and_ip_ranges_track_allocations(client, leaf_request):
    before = {r["site"]: r for r in client.get("/api/v1/ip-ranges", headers=auth("requester")).json()}
    assert before["ams-dc1"]["prefix"] == "10.201.10.0/24"
    assert before["ams-dc1"]["region"] == "eu-west"
    assert before["ams-dc1"]["allocated"] == 0

    client.post("/api/v1/onboardings", json=leaf_request, headers=auth("requester"))
    after = {r["site"]: r for r in client.get("/api/v1/ip-ranges", headers=auth("requester")).json()}
    assert after["ams-dc1"]["allocated"] == 1
    assert after["ams-dc1"]["free"] == before["ams-dc1"]["free"] - 1

    sites = client.get("/api/v1/sites", headers=auth("requester")).json()
    assert {s["site"] for s in sites} == {"ams-dc1", "cai-dc2", "fra-pop1"}
    assert all("description" in s for s in sites)


def test_template_test_render_with_overrides_and_gate(client):
    ok = client.post("/api/v1/templates/nxos/leaf/render", headers=auth("maintainer")).json()
    assert ok["gate_passed"] is True
    assert "{{ secret:aaa/tacacs_key }}" in ok["config"]
    assert ok["layers"][1] == "regions/eu-west"

    bad = client.post(
        "/api/v1/templates/nxos/leaf/render",
        json={"overrides": {"vars": {"legacy_snmp_community": "public"}}},
        headers=auth("maintainer"),
    ).json()
    assert bad["gate_passed"] is False
    failed = {c["rule_id"] for c in bad["compliance"] if not c["passed"]}
    assert "NXOS-SNMP-001" in failed

    day0 = client.post(
        "/api/v1/templates/fortios/edge-fw/render", json={"source": "day0.j2"}, headers=auth("maintainer")
    ).json()
    assert "hatch-callhome" in day0["config"] and day0["compliance"] == []

    assert client.post("/api/v1/templates/nxos/nope/render", headers=auth("maintainer")).status_code == 404
