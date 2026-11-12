"""End-to-end flows through the public API against the simulated device fleet."""

from __future__ import annotations

import io

from conftest import auth

from app.drivers.simulated import FLEET


def create(client, body, role="requester"):
    return client.post("/api/v1/onboardings", json=body, headers=auth(role))


def detail(client, onboarding_id):
    response = client.get(f"/api/v1/onboardings/{onboarding_id}", headers=auth("requester"))
    assert response.status_code == 200
    return response.json()


def test_requires_authentication(client):
    assert client.get("/api/v1/onboardings").status_code == 401
    assert client.get("/api/v1/onboardings", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_push_mode_leaf_completes_end_to_end(client, leaf_request):
    response = create(client, leaf_request)
    assert response.status_code == 201, response.text
    ob_id = response.json()["created"][0]["id"]

    ob = detail(client, ob_id)
    assert ob["status"] == "COMPLETED", ob["error"]
    assert ob["approved_by"].startswith("policy:")
    stages = [s["stage"] for s in ob["stages"]]
    assert stages == [
        "pre_validate",
        "os_upgrade",
        "render_config",
        "push_config",
        "post_checks",
        "compliance_scan",
        "backup_config",
        "hand_over",
        "report",
    ]
    assert all(s["status"] == "succeeded" for s in ob["stages"])
    assert ob["compliance"] and all(c["passed"] for c in ob["compliance"])

    device = client.get("/api/v1/devices", headers=auth("requester")).json()[0]
    assert device["status"] == "active" and device["monitored"] is True

    # The device really received the golden config.
    assert "hostname ams-dc1-leaf-01" in FLEET.get("10.201.10.21").running_config


def test_no_secret_is_visible_anywhere(client, leaf_request):
    ob_id = create(client, leaf_request).json()["created"][0]["id"]
    running = FLEET.get("10.201.10.21").running_config
    tacacs_key = running.split("tacacs-server host 10.255.0.49 key 0 ")[1].split()[0]
    assert len(tacacs_key) >= 16

    surfaces = [
        client.get(f"/api/v1/onboardings/{ob_id}", headers=auth("requester")).text,
        client.get(f"/api/v1/onboardings/{ob_id}/preview", headers=auth("requester")).text,
        client.get(f"/api/v1/onboardings/{ob_id}/report", headers=auth("requester")).text,
        client.get(f"/api/v1/onboardings/{ob_id}/report?format=json", headers=auth("requester")).text,
        client.get("/api/v1/audit", headers=auth("requester")).text,
    ]
    for text in surfaces:
        assert tacacs_key not in text


def test_validation_rejects_bad_requests(client, leaf_request):
    bad = {**leaf_request, "hostname": "Leaf_01", "mgmt_ip": "10.9.9.9", "serial": "x"}
    response = create(client, bad)
    assert response.status_code == 422
    fields = {e["field"] for e in response.json()["detail"]["errors"]}
    assert {"hostname", "mgmt_ip", "serial"} <= fields

    wrong_role = {**leaf_request, "role": "dc-fw"}
    assert create(client, wrong_role).status_code == 422


def test_duplicates_are_rejected(client, leaf_request):
    assert create(client, leaf_request).status_code == 201
    again = create(client, {**leaf_request, "hostname": "ams-dc1-leaf-02"})
    messages = " ".join(e["message"] for e in again.json()["detail"]["errors"])
    assert "already registered" in messages and "already allocated" in messages


def test_dry_run_previews_without_creating(client, leaf_request):
    response = client.post("/api/v1/onboardings/dry-run", json=leaf_request, headers=auth("requester"))
    body = response.json()
    assert body["valid"] is True and body["requires_approval"] is False
    assert "{{ secret:aaa/tacacs_key }}" in body["preview"]["config"]
    assert body["preview"]["diff"].startswith("---")
    assert client.get("/api/v1/onboardings", headers=auth("requester")).json()["total"] == 0


def test_approval_flow_with_four_eyes(client, firewall_request):
    ob_id = create(client, firewall_request).json()["created"][0]["id"]
    assert detail(client, ob_id)["status"] == "PENDING_APPROVAL"

    # Requesters cannot approve.
    assert client.post(f"/api/v1/onboardings/{ob_id}/approve", headers=auth("requester")).status_code == 403

    response = client.post(
        f"/api/v1/onboardings/{ob_id}/approve", json={"comment": "LGTM"}, headers=auth("approver")
    )
    assert response.status_code == 200, response.text
    ob = detail(client, ob_id)
    assert ob["status"] == "COMPLETED", ob["error"]
    assert ob["approved_by"] == "adam.approver"


def test_self_approval_is_blocked(client, firewall_request):
    ob_id = create(client, firewall_request, role="approver").json()["created"][0]["id"]
    response = client.post(f"/api/v1/onboardings/{ob_id}/approve", headers=auth("approver"))
    assert response.status_code == 403
    assert "four-eyes" in response.json()["detail"]


def test_failed_post_check_then_retry(client, leaf_request):
    body = {**leaf_request, "simulate": {"fail_check": "ntp_synced", "fail_times": 1}}
    ob_id = create(client, body).json()["created"][0]["id"]
    ob = detail(client, ob_id)
    assert ob["status"] == "FAILED"
    assert ob["failed_stage"] == "post_checks"
    assert "ntp_synced" in ob["error"]
    assert ob["allowed_actions"] == ["retry", "rollback", "cancel"]

    response = client.post(f"/api/v1/onboardings/{ob_id}/retry", headers=auth("requester"))
    assert response.status_code == 200
    assert response.json()["message"] == "retrying from post_checks"
    ob = detail(client, ob_id)
    assert ob["status"] == "COMPLETED"
    assert ob["attempt"] == 2
    # Retry resumed: config was pushed exactly once.
    assert [s["stage"] for s in ob["stages"]].count("push_config") == 1


def test_failed_push_then_rollback_restores_snapshot(client, leaf_request):
    body = {**leaf_request, "simulate": {"fail_check": "aaa_login", "fail_times": 5}}
    ob_id = create(client, body).json()["created"][0]["id"]
    assert detail(client, ob_id)["status"] == "FAILED"
    assert "hostname ams-dc1-leaf-01" in FLEET.get("10.201.10.21").running_config

    response = client.post(f"/api/v1/onboardings/{ob_id}/rollback", headers=auth("requester"))
    assert response.status_code == 200
    assert response.json()["message"] == "pre-change configuration restored"
    assert detail(client, ob_id)["status"] == "ROLLED_BACK"
    assert "minimal day-0" in FLEET.get("10.201.10.21").running_config
    # Identifiers are released and can be reused.
    assert client.get("/api/v1/devices", headers=auth("requester")).json() == []


def test_push_failure_retry_rerenders(client, leaf_request):
    body = {**leaf_request, "simulate": {"fail_stage": "push_config", "fail_times": 1}}
    ob_id = create(client, body).json()["created"][0]["id"]
    assert detail(client, ob_id)["failed_stage"] == "push_config"
    response = client.post(f"/api/v1/onboardings/{ob_id}/retry", headers=auth("requester"))
    assert response.json()["message"] == "retrying from render_config"
    assert detail(client, ob_id)["status"] == "COMPLETED"


def test_compliance_gate_blocks_bad_override(client, leaf_request):
    body = {**leaf_request, "vars": {**leaf_request["vars"], "legacy_snmp_community": "public"}}
    ob_id = create(client, body).json()["created"][0]["id"]
    ob = detail(client, ob_id)
    assert ob["status"] == "FAILED"
    assert ob["failed_stage"] == "compliance_scan"
    assert "NXOS-SNMP-001" in ob["error"]


def test_cancel_releases_inventory(client, firewall_request):
    ob_id = create(client, firewall_request).json()["created"][0]["id"]
    response = client.post(
        f"/api/v1/onboardings/{ob_id}/cancel", json={"reason": "wrong rack"}, headers=auth("requester")
    )
    assert response.status_code == 200
    assert detail(client, ob_id)["status"] == "CANCELLED"
    # Completed or cancelled onboardings cannot be cancelled again.
    again = client.post(f"/api/v1/onboardings/{ob_id}/cancel", headers=auth("requester"))
    assert again.status_code == 409


def test_batch_partially_accepts(client, leaf_request):
    second = {
        **leaf_request,
        "hostname": "ams-dc1-leaf-02",
        "serial": "FDO2401A1BD",
        "mgmt_ip": "10.201.10.22",
        "vars": {"bgp_asn": 65102, "loopback0": "10.250.1.22"},
    }
    duplicate = {**second, "hostname": "ams-dc1-leaf-03"}
    response = client.post(
        "/api/v1/onboardings", json={"devices": [leaf_request, second, duplicate]}, headers=auth("requester")
    )
    body = response.json()
    assert response.status_code == 201
    assert len(body["created"]) == 2 and len(body["rejected"]) == 1
    assert body["rejected"][0]["index"] == 2
    listing = client.get(f"/api/v1/onboardings?batch_id={body['batch_id']}", headers=auth("requester"))
    assert listing.json()["total"] == 2
    # Every accepted row runs its pipeline.
    assert all(detail(client, ob["id"])["status"] == "COMPLETED" for ob in body["created"])


def test_csv_import_auto_allocates_hostnames_and_ips(client):
    csv_text = (
        "serial,model,role,site,mode,ticket_ref,uplinks\n"
        "CZ2401AAAA,PowerEdge-R760,compute-host,ams-dc1,push,CHG-7,vmnic0=ams-dc1-leaf-01:Ethernet1/1\n"
        "CZ2401AAAB,PowerEdge-R760,compute-host,ams-dc1,push,CHG-7,\n"
    )
    response = client.post(
        "/api/v1/onboardings/import",
        files={"file": ("devices.csv", io.BytesIO(csv_text.encode()), "text/csv")},
        headers=auth("requester"),
    )
    assert response.status_code == 201, response.text
    created = response.json()["created"]
    assert [c["hostname"] for c in created] == ["ams-dc1-compute-host-01", "ams-dc1-compute-host-02"]
    assert [c["mgmt_ip"] for c in created] == ["10.201.10.10", "10.201.10.11"]
    assert all(detail(client, c["id"])["status"] == "COMPLETED" for c in created)


def test_report_and_audit_trail(client, leaf_request):
    ob_id = create(client, leaf_request).json()["created"][0]["id"]
    html = client.get(f"/api/v1/onboardings/{ob_id}/report", headers=auth("requester")).text
    assert "ONBOARDING REPORT" in html and "ams-dc1-leaf-01" in html
    data = client.get(f"/api/v1/onboardings/{ob_id}/report?format=json", headers=auth("requester")).json()
    assert data["compliance"]["passed"] == data["compliance"]["total"]
    assert {c["name"] for c in data["post_checks"]} >= {"reachability", "ntp_synced", "lldp_neighbors"}
    audit = client.get(f"/api/v1/audit?onboarding_id={ob_id}", headers=auth("requester")).json()
    actions = [(a["actor"], a["to_status"]) for a in reversed(audit) if a["action"] == "transition"]
    assert actions[0] == ("hatch-validator", "VALIDATED")
    assert actions[-1] == ("hatch-pipeline", "COMPLETED")


def test_site_scoped_tokens(client, leaf_request, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv(
        "HATCH_API_TOKENS",
        '[{"token": "cai-only", "user": "cai.eng", "role": "requester", "sites": ["cai-dc2"]}]',
    )
    get_settings.cache_clear()
    response = client.post(
        "/api/v1/onboardings", json=leaf_request, headers={"Authorization": "Bearer cai-only"}
    )
    assert response.status_code == 403


def test_catalog_suggest_stats_and_metrics(client, leaf_request):
    catalog = client.get("/api/v1/catalog", headers=auth("requester")).json()
    assert {s["name"] for s in catalog["sites"]} == {"ams-dc1", "cai-dc2", "fra-pop1"}
    suggestion = client.get(
        "/api/v1/catalog/suggest?site=ams-dc1&role=leaf&count=2", headers=auth("requester")
    ).json()
    assert suggestion == [
        {"hostname": "ams-dc1-leaf-01", "mgmt_ip": "10.201.10.10"},
        {"hostname": "ams-dc1-leaf-02", "mgmt_ip": "10.201.10.11"},
    ]
    create(client, leaf_request)
    stats = client.get("/api/v1/stats", headers=auth("requester")).json()
    assert stats["completed"] == 1 and stats["compliance_pass_rate"] == 1.0
    metrics = client.get("/metrics").text
    assert 'hatch_onboardings{status="COMPLETED"} 1' in metrics
    templates = client.get("/api/v1/templates", headers=auth("requester")).json()
    assert len(templates) == 6
    assert client.get("/healthz").json()["status"] == "ok"
