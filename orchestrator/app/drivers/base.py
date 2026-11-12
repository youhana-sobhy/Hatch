"""Device driver contract.

A driver is the only component that talks to a device. Pipelines are written against this
interface, so adding a vendor or a transport (SSH, NETCONF, REST, a controller API) means
adding a driver, not changing the pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class DriverError(Exception):
    """Raised for any device-side failure; the message is shown to the engineer."""


@dataclass
class Target:
    hostname: str
    serial: str
    vendor: str
    model: str
    mgmt_ip: str
    username: str = "hatch"
    password: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Facts:
    reachable: bool
    serial: str
    model: str
    os_version: str


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


class DeviceDriver(ABC):
    name: str = "base"

    @abstractmethod
    def probe(self, target: Target) -> Facts:
        """Reachability plus identity (serial, model, OS) of the device."""

    @abstractmethod
    def get_running_config(self, target: Target) -> str: ...

    @abstractmethod
    def apply_config(self, target: Target, config: str) -> str:
        """Apply a full configuration; returns the device output."""

    @abstractmethod
    def restore_config(self, target: Target, config: str) -> str:
        """Replace the running configuration with a previous snapshot (rollback)."""

    @abstractmethod
    def run_check(self, target: Target, check: str, params: dict[str, Any]) -> CheckResult: ...


def get_driver(name: str) -> DeviceDriver:
    if name == "simulated":
        from app.drivers.simulated import SimulatedDriver

        return SimulatedDriver()
    if name == "ssh":
        from app.drivers.ssh import SSHDriver

        return SSHDriver()
    raise ValueError(f"unknown driver {name}")
