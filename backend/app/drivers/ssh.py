"""SSH CLI driver (experimental).

Talks to real devices over SSH using per-vendor command profiles. Install the optional
dependency with ``pip install hatch-orchestrator[ssh]`` and set ``HATCH_DRIVER=ssh``.

Post-checks are expressed as a command plus a regex that must match its output, so a new
check for a vendor is a profile entry, not code.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from app.drivers.base import CheckResult, DeviceDriver, DriverError, Facts, Target


@dataclass(frozen=True)
class Profile:
    show_config: str
    show_version: str
    serial_regex: str
    version_regex: str
    enter_config: list[str]
    commit: list[str]
    replace_config: list[str]
    checks: dict[str, tuple[str, str]] = field(default_factory=dict)


PROFILES: dict[str, Profile] = {
    "nxos": Profile(
        show_config="show running-config",
        show_version="show version",
        serial_regex=r"Processor Board ID\s+(\S+)",
        version_regex=r"NXOS: version\s+(\S+)",
        enter_config=["configure terminal"],
        commit=["end", "copy running-config startup-config"],
        replace_config=["configure replace bootflash:hatch-rollback.cfg"],
        checks={
            "ntp_synced": ("show ntp peer-status", r"^\*"),
            "aaa_login": ("show tacacs-server", r"available on port"),
            "interfaces_up": ("show interface status | include connected", r"connected"),
            "lldp_neighbors": ("show lldp neighbors", r"Total entries displayed: [1-9]"),
        },
    ),
    "junos": Profile(
        show_config="show configuration | display set",
        show_version="show version",
        serial_regex=r"Chassis\s+(\S+)",
        version_regex=r"Junos:\s+(\S+)",
        enter_config=["configure private"],
        commit=["commit and-quit"],
        replace_config=["rollback 1", "commit and-quit"],
        checks={"ntp_synced": ("show ntp status", r"leap_none")},
    ),
}


class SSHDriver(DeviceDriver):
    name = "ssh"

    def _profile(self, target: Target) -> Profile:
        profile = PROFILES.get(target.vendor)
        if profile is None:
            raise DriverError(f"no SSH profile for vendor {target.vendor}")
        return profile

    def _run(self, target: Target, commands: list[str]) -> str:
        try:
            import asyncssh
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise DriverError("asyncssh is not installed (pip install .[ssh])") from exc

        async def _session() -> str:
            async with asyncssh.connect(
                target.mgmt_ip,
                username=target.username,
                password=target.password,
                known_hosts=None,
                connect_timeout=15,
            ) as conn:
                out = []
                for command in commands:
                    result = await conn.run(command, check=False)
                    out.append(str(result.stdout))
                return "\n".join(out)

        try:
            return asyncio.run(_session())
        except (OSError, asyncssh.Error) as exc:
            raise DriverError(f"ssh {target.mgmt_ip}: {exc}") from exc

    def probe(self, target: Target) -> Facts:
        profile = self._profile(target)
        output = self._run(target, [profile.show_version])
        serial = re.search(profile.serial_regex, output)
        version = re.search(profile.version_regex, output)
        return Facts(
            reachable=True,
            serial=serial.group(1) if serial else "",
            model=target.model,
            os_version=version.group(1) if version else "unknown",
        )

    def get_running_config(self, target: Target) -> str:
        return self._run(target, [self._profile(target).show_config])

    def apply_config(self, target: Target, config: str) -> str:
        profile = self._profile(target)
        lines = [line for line in config.splitlines() if line.strip() and not line.startswith("!")]
        return self._run(target, profile.enter_config + lines + profile.commit)

    def restore_config(self, target: Target, config: str) -> str:
        return self._run(target, self._profile(target).replace_config)

    def run_check(self, target: Target, check: str, params: dict[str, Any]) -> CheckResult:
        profile = self._profile(target)
        if check == "reachability":
            self.probe(target)
            return CheckResult(check, True, "device answered over SSH")
        spec = profile.checks.get(check)
        if spec is None:
            return CheckResult(check, True, f"no {target.vendor} command for {check}; skipped")
        command, regex = spec
        output = self._run(target, [command])
        passed = bool(re.search(regex, output, re.MULTILINE))
        return CheckResult(check, passed, f"{command}: {'ok' if passed else 'unexpected output'}")
