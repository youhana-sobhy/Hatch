from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core import content
from app.drivers.simulated import FLEET

TOKENS = {
    "requester": "dev-requester",
    "approver": "dev-approver",
    "maintainer": "dev-maintainer",
    "admin": "dev-admin",
    "service": "dev-ztp-service",
}


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("HATCH_ENV", "test")
    monkeypatch.setenv("HATCH_DATABASE_URL", f"sqlite:///{tmp_path / 'hatch.db'}")
    monkeypatch.setenv("HATCH_EXECUTOR", "inline")
    monkeypatch.setenv("HATCH_BACKUP_DIR", str(tmp_path / "backups"))
    for name in ("HATCH_NOTIFY_WEBHOOK_URL", "HATCH_MONITORING_WEBHOOK_URL", "HATCH_API_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    content._library = None
    FLEET.clear()
    yield
    FLEET.clear()
    get_settings.cache_clear()


@pytest.fixture
def client():
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def auth(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[role]}"}


@pytest.fixture
def leaf_request() -> dict:
    return {
        "hostname": "ams-dc1-leaf-01",
        "serial": "FDO2401A1BC",
        "model": "N9K-C93180YC-FX3",
        "role": "leaf",
        "site": "ams-dc1",
        "mgmt_ip": "10.201.10.21",
        "mode": "push",
        "ticket_ref": "CHG-1001",
        "uplinks": [
            {"interface": "Ethernet1/49", "peer": "ams-dc1-spine-01", "peer_interface": "Ethernet1/1"},
            {"interface": "Ethernet1/50", "peer": "ams-dc1-spine-02", "peer_interface": "Ethernet1/1"},
        ],
        "vars": {"bgp_asn": 65101, "loopback0": "10.250.1.21"},
    }


@pytest.fixture
def firewall_request() -> dict:
    return {
        "hostname": "cai-dc2-dc-fw-01",
        "serial": "013201009999",
        "model": "PA-5410",
        "role": "dc-fw",
        "site": "cai-dc2",
        "mgmt_ip": "10.202.20.51",
        "mode": "push",
        "vars": {"ha_peer_ip": "10.202.20.52", "ha_priority": 100},
    }
