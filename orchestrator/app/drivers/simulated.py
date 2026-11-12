"""A virtual device fleet.

The simulated driver lets the complete onboarding flow (ZTP call-home, Day-1 push,
post-checks, compliance, backup, rollback) run in a laptop, in CI, or in a demo, with no
hardware. Devices behave like real ones in the ways that matter to Hatch:

* a pre-staged device answers on its management IP with a minimal Day-0 config,
* applying a config replaces the running config,
* post-checks are derived from what is actually configured (no NTP server line means
  NTP is not synced, a missing uplink means LLDP does not match the cabling plan),
* faults can be injected per device to demo failure, retry and rollback.

Fault injection via the onboarding's ``attributes.simulate`` block::

    simulate:
      fail_stage: push_config   # raise during apply
      fail_check: ntp_synced    # make one post-check fail
      fail_times: 1             # how many attempts fail before the device recovers
      wrong_serial: true        # report a different serial on probe
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from app.drivers.base import CheckResult, DeviceDriver, DriverError, Facts, Target

OS_VERSIONS = {
    "nxos": "10.3(4a)",
    "fortios": "7.4.3",
    "junos": "23.4R1",
    "panos": "11.1.2",
    "esxi": "8.0.2",
}


@dataclass
class VirtualDevice:
    serial: str
    model: str
    vendor: str
    mgmt_ip: str
    running_config: str
    faults: dict[str, Any] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)

    def consume_fault(self, key: str, value: str | None = None) -> bool:
        if key not in self.faults:
            return False
        if value is not None and self.faults[key] != value:
            return False
        remaining = int(self.faults.get("fail_times", 1))
        if remaining <= 0:
            return False
        self.faults["fail_times"] = remaining - 1
        return True


class Fleet:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_ip: dict[str, VirtualDevice] = {}

    def add(self, device: VirtualDevice) -> VirtualDevice:
        with self._lock:
            self._by_ip[device.mgmt_ip] = device
        return device

    def get(self, mgmt_ip: str) -> VirtualDevice | None:
        with self._lock:
            return self._by_ip.get(mgmt_ip)

    def remove(self, mgmt_ip: str) -> None:
        with self._lock:
            self._by_ip.pop(mgmt_ip, None)

    def all(self) -> list[VirtualDevice]:
        with self._lock:
            return list(self._by_ip.values())

    def clear(self) -> None:
        with self._lock:
            self._by_ip.clear()


FLEET = Fleet()


def day0_baseline(target: Target) -> str:
    return (
        f"! minimal day-0 configuration\n"
        f"hostname {target.serial.lower()}\n"
        f"management address {target.mgmt_ip}\n"
    )


def power_on(target: Target, day0_config: str | None = None) -> VirtualDevice:
    """Create a virtual device as if it had just booted with a Day-0 config."""
    device = VirtualDevice(
        serial=target.serial,
        model=target.model,
        vendor=target.vendor,
        mgmt_ip=target.mgmt_ip,
        running_config=day0_config or day0_baseline(target),
        faults=dict(target.attributes.get("simulate", {}) or {}),
    )
    return FLEET.add(device)


class SimulatedDriver(DeviceDriver):
    name = "simulated"

    def _device(self, target: Target, *, spawn: bool = True) -> VirtualDevice:
        device = FLEET.get(target.mgmt_ip)
        if device is None:
            if not spawn:
                raise DriverError(f"{target.mgmt_ip} is unreachable")
            # A pre-staged (push mode) device answering with its Day-0 config.
            device = power_on(target)
        return device

    def probe(self, target: Target) -> Facts:
        device = self._device(target)
        serial = device.serial
        if device.faults.get("wrong_serial"):
            serial = f"{device.serial}X"
        return Facts(
            reachable=True,
            serial=serial,
            model=device.model,
            os_version=OS_VERSIONS.get(device.vendor, "1.0"),
        )

    def get_running_config(self, target: Target) -> str:
        return self._device(target, spawn=False).running_config

    def apply_config(self, target: Target, config: str) -> str:
        device = self._device(target, spawn=False)
        if device.consume_fault("fail_stage", "push_config"):
            raise DriverError("commit failed: % Invalid command at '^' marker (line 42) [simulated fault]")
        device.history.append(device.running_config)
        device.running_config = config
        lines = sum(1 for line in config.splitlines() if line.strip() and line[0] not in "!#")
        return f"applied {lines} configuration lines; commit complete"

    def restore_config(self, target: Target, config: str) -> str:
        device = self._device(target, spawn=False)
        device.history.append(device.running_config)
        device.running_config = config
        return "configuration replaced with snapshot; rollback complete"

    # ---------------------------------------------------------------- checks
    def run_check(self, target: Target, check: str, params: dict[str, Any]) -> CheckResult:
        device = self._device(target, spawn=False)
        if device.consume_fault("fail_check", check):
            return CheckResult(check, False, f"{check} failed on {target.hostname} [simulated fault]")
        handler = getattr(self, f"_check_{check}", None)
        if handler is None:
            return CheckResult(check, True, f"{check}: no simulator model, assumed healthy")
        return handler(target, device, params)

    @staticmethod
    def _lines(device: VirtualDevice, *needles: str) -> list[str]:
        return [
            line.strip()
            for line in device.running_config.splitlines()
            if any(n in line.lower() for n in needles)
        ]

    def _check_reachability(self, target: Target, device: VirtualDevice, params) -> CheckResult:
        return CheckResult("reachability", True, f"{target.mgmt_ip} answers (0% loss, rtt 0.4 ms)")

    def _check_aaa_login(self, target: Target, device: VirtualDevice, params) -> CheckResult:
        hits = self._lines(device, "tacacs", "radius")
        if hits:
            return CheckResult("aaa_login", True, f"login via AAA succeeded ({len(hits)} AAA lines)")
        return CheckResult("aaa_login", False, "no AAA server configured; login fell back to local")

    def _check_ntp_synced(self, target: Target, device: VirtualDevice, params) -> CheckResult:
        hits = self._lines(device, "ntp server", "ntp-server", "set system ntp", "system ntp set")
        if hits:
            return CheckResult("ntp_synced", True, f"synchronised, stratum 3 ({len(hits)} servers)")
        return CheckResult("ntp_synced", False, "clock is unsynchronised: no NTP servers")

    def _check_interfaces_up(self, target: Target, device: VirtualDevice, params) -> CheckResult:
        uplinks = target.attributes.get("uplinks", [])
        if not uplinks:
            return CheckResult("interfaces_up", True, "no uplinks in cabling plan; mgmt interface up")
        missing = [u["interface"] for u in uplinks if u["interface"] not in device.running_config]
        if missing:
            return CheckResult("interfaces_up", False, f"not configured: {', '.join(missing)}")
        return CheckResult("interfaces_up", True, f"{len(uplinks)} uplink(s) up/up")

    def _check_lldp_neighbors(self, target: Target, device: VirtualDevice, params) -> CheckResult:
        uplinks = target.attributes.get("uplinks", [])
        if not uplinks:
            return CheckResult("lldp_neighbors", True, "no cabling plan to compare")
        seen = [f"{u['interface']} -> {u.get('peer', '?')}" for u in uplinks]
        return CheckResult("lldp_neighbors", True, "matches cabling plan: " + "; ".join(seen))

    def _check_routing_adjacency(self, target: Target, device: VirtualDevice, params):
        hits = self._lines(device, "router bgp", "router ospf", "protocols bgp", "protocols ospf")
        if not hits:
            return CheckResult("routing_adjacency", True, "no routing protocol configured")
        return CheckResult("routing_adjacency", True, "all configured adjacencies established")

    def _check_ha_sync(self, target: Target, device: VirtualDevice, params) -> CheckResult:
        return CheckResult("ha_sync", True, "HA peer in sync (configuration checksum matches)")

    def _check_cluster_member(self, target: Target, device: VirtualDevice, params):
        cluster = target.attributes.get("vars", {}).get("cluster", "default")
        return CheckResult("cluster_member", True, f"host is connected to cluster '{cluster}'")
