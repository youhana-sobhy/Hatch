"""Pre-flight validation and IPAM / naming suggestions.

Nothing is created until a request passes every check: site and model exist, the role is
allowed for the model, an approved golden template exists, the hostname follows the naming
convention and is unique, the management IP is inside the site prefix and free, and the
serial number is not already registered.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.content import ContentLibrary
from app.models import Device

SERIAL_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{3,31}$")


@dataclass
class ValidationReport:
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, fld: str, message: str) -> None:
        self.errors.append({"field": fld, "message": message})

    def warn(self, fld: str, message: str) -> None:
        self.warnings.append({"field": fld, "message": message})


@dataclass
class Claims:
    """Identifiers already taken, by the inventory or by other rows in the same batch."""

    hostnames: set[str] = field(default_factory=set)
    serials: set[str] = field(default_factory=set)
    ips: set[str] = field(default_factory=set)

    @classmethod
    def from_inventory(cls, session: Session) -> Claims:
        rows = session.execute(select(Device.hostname, Device.serial, Device.mgmt_ip)).all()
        return cls(
            hostnames={r.hostname for r in rows},
            serials={r.serial for r in rows},
            ips={r.mgmt_ip for r in rows},
        )


def hostname_regex(lib: ContentLibrary) -> re.Pattern[str]:
    pattern = (
        lib.layers.get("global", {}).get("naming", {}).get("hostname_regex", r"^[a-z0-9]+(-[a-z0-9]+)+$")
    )
    return re.compile(pattern)


def validate_request(
    lib: ContentLibrary,
    claims: Claims,
    *,
    hostname: str,
    serial: str,
    model: str,
    role: str,
    site: str,
    mgmt_ip: str,
    mode: str,
) -> tuple[ValidationReport, str | None]:
    """Returns the report and the vendor resolved from the model catalog."""
    report = ValidationReport()
    vendor: str | None = None

    site_info = lib.sites.get(site)
    if site_info is None:
        report.error("site", f"unknown site '{site}'")

    model_info = lib.models.get(model)
    if model_info is None:
        report.error("model", f"model '{model}' is not in the device catalog")
    else:
        vendor = model_info.vendor
        if role not in model_info.roles:
            report.error(
                "role",
                f"role '{role}' is not allowed for {model} (allowed: {', '.join(model_info.roles)})",
            )

    if vendor:
        template = lib.template_for(vendor, role)
        if template is None:
            report.error("role", f"no golden template exists for {vendor}/{role}")
        else:
            if template.status != "approved" and not get_settings().allow_draft_templates:
                report.error("role", f"template {template.key} is '{template.status}', not approved")
            if mode == "ztp" and not template.has_day0:
                report.error("mode", f"template {template.key} has no Day-0 bootstrap for ZTP")

    if not hostname_regex(lib).match(hostname):
        report.error("hostname", f"'{hostname}' does not follow the naming convention")
    elif site_info and not hostname.startswith(site.lower()):
        report.error("hostname", f"hostname must start with the site code '{site.lower()}'")
    if hostname in claims.hostnames:
        report.error("hostname", f"hostname '{hostname}' is already in use")

    if not SERIAL_RE.match(serial):
        report.error("serial", f"'{serial}' is not a valid serial number")
    if serial in claims.serials:
        report.error("serial", f"serial '{serial}' is already registered")

    try:
        ip = ipaddress.ip_address(mgmt_ip)
    except ValueError:
        report.error("mgmt_ip", f"'{mgmt_ip}' is not an IP address")
    else:
        if site_info:
            net = ipaddress.ip_network(site_info.mgmt_prefix, strict=False)
            if ip not in net:
                report.error("mgmt_ip", f"{mgmt_ip} is outside the site prefix {net}")
            elif ip in (net.network_address, net.broadcast_address):
                report.error("mgmt_ip", f"{mgmt_ip} is the network or broadcast address")
            elif str(ip) == site_info.mgmt_gateway:
                report.error("mgmt_ip", f"{mgmt_ip} is the site gateway")
        if mgmt_ip in claims.ips:
            report.error("mgmt_ip", f"{mgmt_ip} is already allocated")

    if mode not in ("ztp", "push"):
        report.error("mode", "mode must be 'ztp' or 'push'")

    return report, vendor


def suggest(
    lib: ContentLibrary,
    claims: Claims,
    *,
    site: str,
    role: str,
    count: int,
) -> list[dict[str, str]]:
    """Next free hostnames (site naming pattern) and management IPs (site prefix)."""
    site_info = lib.sites[site]
    reserved = int(lib.layers.get(f"sites/{site}", {}).get("site", {}).get("reserved_hosts", 9))
    net = ipaddress.ip_network(site_info.mgmt_prefix, strict=False)

    def free_ips() -> Iterator[str]:
        for index, host in enumerate(net.hosts()):
            candidate = str(host)
            if index < reserved or candidate == site_info.mgmt_gateway:
                continue
            if candidate not in claims.ips:
                yield candidate

    ips = free_ips()
    out: list[dict[str, str]] = []
    index = 1
    taken_hosts = set(claims.hostnames)
    while len(out) < count:
        hostname = site_info.hostname_pattern.format(site=site.lower(), role=role, index=index)
        index += 1
        if hostname in taken_hosts:
            continue
        ip = next(ips, None)
        if ip is None:
            break
        taken_hosts.add(hostname)
        out.append({"hostname": hostname, "mgmt_ip": ip})
    return out
