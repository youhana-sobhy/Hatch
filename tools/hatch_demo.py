#!/usr/bin/env python3
"""Hatch demo driver: seed realistic onboardings and boot virtual ZTP devices.

    python tools/hatch_demo.py seed                 # a mix of push, ZTP, approval and failure cases
    python tools/hatch_demo.py boot FDO2401ZTP1     # a virtual device powers on and calls home
    python tools/hatch_demo.py boot-all             # boot every device waiting for ZTP

Talks only to the public API and the ZTP edge service, exactly like real clients and devices.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time

import httpx

API = os.getenv("HATCH_API", "http://localhost:8000")
ZTP = os.getenv("HATCH_ZTP", "http://localhost:8081")
REQUESTER = os.getenv("HATCH_TOKEN", "dev-requester")
APPROVER = os.getenv("HATCH_APPROVER_TOKEN", "dev-approver")

TOKEN_RE = re.compile(r"""(?:"token"\s*:\s*"|token=|hatch-token=|\\"token\\":\\")([A-Za-z0-9_\-]+)""")

DEVICES = [
    # push mode, auto-approved, completes
    dict(hostname="ams-dc1-leaf-01", serial="FDO2401A1BC", model="N9K-C93180YC-FX3", role="leaf",
         site="ams-dc1", mgmt_ip="10.201.10.21", mode="push", ticket_ref="CHG-20431",
         uplinks=[{"interface": "Ethernet1/49", "peer": "ams-dc1-spine-01", "peer_interface": "Ethernet1/1"},
                  {"interface": "Ethernet1/50", "peer": "ams-dc1-spine-02", "peer_interface": "Ethernet1/1"}],
         vars={"bgp_asn": 65101, "loopback0": "10.250.1.21"}),
    dict(hostname="ams-dc1-compute-host-01", serial="CZ2401ABCD", model="PowerEdge-R760",
         role="compute-host", site="ams-dc1", mgmt_ip="10.201.10.61", mode="push",
         uplinks=[{"interface": "vmnic0", "peer": "ams-dc1-leaf-01", "peer_interface": "Ethernet1/1"}],
         vars={"cluster": "compute-01"}),
    # ZTP: waits for the device to power on
    dict(hostname="ams-dc1-leaf-02", serial="FDO2401ZTP1", model="N9K-C93180YC-FX3", role="leaf",
         site="ams-dc1", mgmt_ip="10.201.10.22", mode="ztp", ticket_ref="CHG-20431",
         uplinks=[{"interface": "Ethernet1/49", "peer": "ams-dc1-spine-01", "peer_interface": "Ethernet1/2"}],
         vars={"bgp_asn": 65102, "loopback0": "10.250.1.22"}),
    dict(hostname="ams-dc1-edge-fw-01", serial="FG200FTK23000001", model="FG-200F", role="edge-fw",
         site="ams-dc1", mgmt_ip="10.201.10.41", mode="ztp", vars={"ha_priority": 200}),
    # needs approval (core role)
    dict(hostname="cai-dc2-dc-fw-01", serial="013201009999", model="PA-5410", role="dc-fw",
         site="cai-dc2", mgmt_ip="10.202.20.51", mode="push", ticket_ref="CHG-20502",
         vars={"ha_peer_ip": "10.202.20.52", "ha_priority": 100}),
    dict(hostname="fra-pop1-pe-router-01", serial="JN12AB34CDEF", model="MX204", role="pe-router",
         site="fra-pop1", mgmt_ip="10.203.30.11", mode="push",
         uplinks=[{"interface": "et-0/0/0", "peer": "fra-pop1-pe-router-02"}],
         vars={"loopback0": "10.250.30.11", "isis_net": "49.0001.0102.5003.0011.00", "bgp_asn": 64500}),
    # fails a post-check once: demo retry
    dict(hostname="ams-dc1-leaf-03", serial="FDO2401A1BE", model="N9K-C93180YC-FX3", role="leaf",
         site="ams-dc1", mgmt_ip="10.201.10.23", mode="push",
         uplinks=[{"interface": "Ethernet1/49", "peer": "ams-dc1-spine-01", "peer_interface": "Ethernet1/3"}],
         vars={"bgp_asn": 65103, "loopback0": "10.250.1.23"},
         simulate={"fail_check": "lldp_neighbors", "fail_times": 1}),
    # blocked by the compliance gate: demo the baseline catching a bad override
    dict(hostname="ams-dc1-leaf-04", serial="FDO2401A1BF", model="N9K-C93180YC-FX3", role="leaf",
         site="ams-dc1", mgmt_ip="10.201.10.24", mode="push",
         vars={"bgp_asn": 65104, "loopback0": "10.250.1.24", "legacy_snmp_community": "public"}),
]


def api(token: str) -> httpx.Client:
    return httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=30)


def seed(_: argparse.Namespace) -> int:
    with api(REQUESTER) as client:
        response = client.post("/api/v1/onboardings", json={"devices": DEVICES})
        response.raise_for_status()
        body = response.json()
    for ob in body["created"]:
        print(f"  created {ob['id']}  {ob['hostname']:<26} {ob['mode']:<4} -> {ob['status']}")
    for rejected in body["rejected"]:
        print(f"  rejected {rejected['hostname']}: {rejected['errors'][0]['message']}")
    pending = [ob for ob in body["created"] if ob["status"] == "PENDING_APPROVAL"]
    if pending:
        time.sleep(1)
        with api(APPROVER) as client:
            first = pending[0]
            client.post(f"/api/v1/onboardings/{first['id']}/approve",
                        json={"comment": "Reviewed rendered config and diff"}).raise_for_status()
            print(f"  approved {first['hostname']} as the approver (others left pending)")
    print("\nNext: python tools/hatch_demo.py boot-all   # power on the ZTP devices")
    return 0


def boot_serial(serial: str) -> bool:
    with httpx.Client(base_url=ZTP, timeout=30) as ztp:
        response = ztp.get(f"/bootstrap/{serial}")
        if response.status_code != 200:
            print(f"  {serial}: no bootstrap ({response.status_code}); is it registered and approved?")
            return False
        match = TOKEN_RE.search(response.text)
        if not match:
            print(f"  {serial}: no call-home token found in Day-0")
            return False
        print(f"  {serial}: Day-0 received ({len(response.text.splitlines())} lines), calling home")
        reply = ztp.post("/callhome", json={"serial": serial, "token": match.group(1)})
        print(f"  {serial}: {reply.status_code} {reply.json()}")
        return reply.status_code == 200


def boot(args: argparse.Namespace) -> int:
    return 0 if boot_serial(args.serial) else 1


def boot_all(_: argparse.Namespace) -> int:
    with api(REQUESTER) as client:
        waiting = client.get("/api/v1/onboardings", params={"status": "WAITING_FOR_DEVICE"}).json()
    if not waiting["items"]:
        print("no devices are waiting for ZTP")
    ok = all(boot_serial(ob["serial"]) for ob in waiting["items"])
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed").set_defaults(func=seed)
    boot_p = sub.add_parser("boot")
    boot_p.add_argument("serial")
    boot_p.set_defaults(func=boot)
    sub.add_parser("boot-all").set_defaults(func=boot_all)
    args = parser.parse_args()
    try:
        return args.func(args)
    except httpx.HTTPError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
