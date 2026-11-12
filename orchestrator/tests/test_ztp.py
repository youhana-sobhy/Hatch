"""Zero-touch provisioning: pre-registration, one-time tokens, call-home, Day-0 reset."""

from conftest import auth

ZTP_LEAF = {
    "hostname": "ams-dc1-leaf-05",
    "serial": "FDO2401ZTP1",
    "model": "N9K-C93180YC-FX3",
    "role": "leaf",
    "site": "ams-dc1",
    "mgmt_ip": "10.201.10.25",
    "mode": "ztp",
    "vars": {"bgp_asn": 65105, "loopback0": "10.250.1.25"},
}


def _token_from(day0: str) -> str:
    return day0.split('"token": "')[1].split('"')[0]


def _create(client):
    response = client.post("/api/v1/onboardings", json=ZTP_LEAF, headers=auth("requester"))
    assert response.status_code == 201, response.text
    return response.json()["created"][0]["id"]


def test_ztp_full_flow(client):
    ob_id = _create(client)
    status = client.get(f"/api/v1/onboardings/{ob_id}", headers=auth("requester")).json()["status"]
    assert status == "WAITING_FOR_DEVICE"

    boot = client.get("/api/v1/ztp/bootstrap/FDO2401ZTP1", headers=auth("service"))
    assert boot.status_code == 200
    assert "ip address 10.201.10.25/24" in boot.text
    token = _token_from(boot.text)

    callhome = client.post(
        "/api/v1/ztp/callhome",
        headers=auth("service"),
        json={"serial": "FDO2401ZTP1", "token": token, "model": "N9K-C93180YC-FX3", "ip": "10.201.10.25"},
    )
    assert callhome.status_code == 200, callhome.text

    ob = client.get(f"/api/v1/onboardings/{ob_id}", headers=auth("requester")).json()
    assert ob["status"] == "COMPLETED", ob["error"]

    # Tokens are one-time.
    replay = client.post(
        "/api/v1/ztp/callhome", headers=auth("service"), json={"serial": "FDO2401ZTP1", "token": token}
    )
    assert replay.status_code == 403


def test_bootstrap_only_for_registered_serials_and_service_role(client):
    _create(client)
    assert client.get("/api/v1/ztp/bootstrap/UNKNOWN123", headers=auth("service")).status_code == 404
    assert client.get("/api/v1/ztp/bootstrap/FDO2401ZTP1", headers=auth("requester")).status_code == 403


def test_callhome_rejects_bad_token_and_wrong_model(client):
    _create(client)
    boot = client.get("/api/v1/ztp/bootstrap/FDO2401ZTP1", headers=auth("service"))
    token = _token_from(boot.text)
    bad = client.post(
        "/api/v1/ztp/callhome", headers=auth("service"), json={"serial": "FDO2401ZTP1", "token": "forged"}
    )
    assert bad.status_code == 403
    wrong = client.post(
        "/api/v1/ztp/callhome",
        headers=auth("service"),
        json={"serial": "FDO2401ZTP1", "token": token, "model": "N9K-C9336C-FX2"},
    )
    assert wrong.status_code == 403
    assert "model mismatch" in wrong.json()["detail"]


def test_ztp_rollback_resets_to_day0(client):
    body = {**ZTP_LEAF, "simulate": {"fail_check": "lldp_neighbors", "fail_times": 1}}
    ob_id = client.post("/api/v1/onboardings", json=body, headers=auth("requester")).json()["created"][0][
        "id"
    ]
    token = _token_from(client.get("/api/v1/ztp/bootstrap/FDO2401ZTP1", headers=auth("service")).text)
    client.post(
        "/api/v1/ztp/callhome", headers=auth("service"), json={"serial": "FDO2401ZTP1", "token": token}
    )
    assert client.get(f"/api/v1/onboardings/{ob_id}", headers=auth("requester")).json()["status"] == "FAILED"

    response = client.post(f"/api/v1/onboardings/{ob_id}/rollback", headers=auth("requester"))
    assert response.status_code == 200
    ob = client.get(f"/api/v1/onboardings/{ob_id}", headers=auth("requester")).json()
    assert ob["status"] == "WAITING_FOR_DEVICE"

    # The device boots again, gets a fresh token and completes.
    token = _token_from(client.get("/api/v1/ztp/bootstrap/FDO2401ZTP1", headers=auth("service")).text)
    client.post(
        "/api/v1/ztp/callhome", headers=auth("service"), json={"serial": "FDO2401ZTP1", "token": token}
    )
    assert (
        client.get(f"/api/v1/onboardings/{ob_id}", headers=auth("requester")).json()["status"] == "COMPLETED"
    )
