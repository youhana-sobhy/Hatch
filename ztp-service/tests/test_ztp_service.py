"""The edge service against a mocked orchestrator."""

import httpx
from fastapi.testclient import TestClient

from ztp.main import create_app

calls: list[httpx.Request] = []


def orchestrator(request: httpx.Request) -> httpx.Response:
    calls.append(request)
    if request.url.path == "/api/v1/ztp/bootstrap/GOOD1234":
        return httpx.Response(200, text="hostname good1234\n", headers={"X-Hatch-Vendor": "nxos"})
    if request.url.path == "/api/v1/ztp/callhome":
        body = request.read().decode()
        if '"token":"ok"' in body.replace(" ", ""):
            return httpx.Response(200, json={"id": "onb_1", "hostname": "ams-dc1-leaf-01"})
        return httpx.Response(403, json={"detail": "invalid token"})
    return httpx.Response(404, json={"detail": "no"})


def client() -> TestClient:
    calls.clear()
    return TestClient(create_app(httpx.MockTransport(orchestrator)))


def test_serves_vendor_native_bootstrap_with_service_token():
    c = client()
    response = c.get("/poap/GOOD1234.py")
    assert response.status_code == 200
    assert response.text == "hostname good1234\n"
    assert response.headers["content-type"].startswith("text/x-python")
    assert calls[0].headers["Authorization"] == "Bearer dev-ztp-service"
    assert calls[0].headers["X-Client-IP"] == "testclient"


def test_vendor_mismatch_and_unknown_serials_are_opaque_404s():
    c = client()
    assert c.get("/junos/GOOD1234.conf").status_code == 404
    assert c.get("/bootstrap/NOPE0000").status_code == 404


def test_callhome_relay():
    c = client()
    ok = c.post("/callhome", json={"serial": "GOOD1234", "token": "ok"})
    assert ok.json() == {"status": "accepted", "onboarding": "onb_1", "hostname": "ams-dc1-leaf-01"}
    assert c.post("/callhome", json={"serial": "GOOD1234", "token": "bad"}).status_code == 403
    assert c.get("/callhome?serial=GOOD1234&token=ok").status_code == 200


def test_image_path_traversal_blocked():
    assert client().get("/images/..%2F..%2Fetc%2Fpasswd").status_code == 404
