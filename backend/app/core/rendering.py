"""Golden-configuration rendering.

Variables are layered ``global -> region -> site -> role -> device`` so every setting lives
in exactly one place. Templates are rendered with ``StrictUndefined``: a missing variable
is a hard error, never a silently empty line in a production config.
"""

from __future__ import annotations

import difflib
import hashlib
import ipaddress
from dataclasses import dataclass, field
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateError

from app.core.content import ContentLibrary, Template, deep_merge
from app.core.secrets import SecretResolver


class RenderError(Exception):
    pass


def _netmask(prefix: str) -> str:
    return str(ipaddress.ip_network(prefix, strict=False).netmask)


def _prefixlen(prefix: str) -> int:
    return ipaddress.ip_network(prefix, strict=False).prefixlen


def _wildcard(prefix: str) -> str:
    return str(ipaddress.ip_network(prefix, strict=False).hostmask)


def _network(prefix: str) -> str:
    return str(ipaddress.ip_network(prefix, strict=False).network_address)


def _environment() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,  # device configs, not HTML
    )
    env.filters.update(netmask=_netmask, prefixlen=_prefixlen, wildcard=_wildcard, network=_network)
    return env


@dataclass
class DeviceFacts:
    hostname: str
    serial: str
    vendor: str
    model: str
    role: str
    site: str
    region: str
    mgmt_ip: str
    mode: str = "push"
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class RenderResult:
    config: str
    template: Template
    layers: list[str]
    variables: dict[str, Any]
    secrets_used: list[str]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.config.encode()).hexdigest()


def build_context(lib: ContentLibrary, facts: DeviceFacts, template: Template) -> dict[str, Any]:
    site = lib.sites[facts.site]
    net = ipaddress.ip_network(site.mgmt_prefix, strict=False)
    layered = lib.layered_vars(facts.region, facts.site, facts.role)
    variables = deep_merge(layered, facts.attributes.get("vars", {}))
    device = {
        "hostname": facts.hostname,
        "serial": facts.serial,
        "vendor": facts.vendor,
        "model": facts.model,
        "role": facts.role,
        "site": facts.site,
        "region": facts.region,
        "mode": facts.mode,
        "mgmt_ip": facts.mgmt_ip,
        "mgmt_prefix": str(net),
        "mgmt_prefixlen": net.prefixlen,
        "mgmt_netmask": str(net.netmask),
        "mgmt_gateway": site.mgmt_gateway,
        "uplinks": facts.attributes.get("uplinks", []),
    }
    return {
        **variables,
        "device": device,
        "template": {"key": template.key, "version": template.full_version},
    }


def render(
    lib: ContentLibrary,
    facts: DeviceFacts,
    resolver: SecretResolver,
    *,
    source: str = "config.j2",
) -> RenderResult:
    template = lib.template_for(facts.vendor, facts.role)
    if template is None:
        raise RenderError(f"no golden template for {facts.vendor}/{facts.role}")
    context = build_context(lib, facts, template)
    missing = [name for name in template.required_vars if name not in context]
    if missing:
        raise RenderError(f"template {template.key} requires variables: {', '.join(missing)}")

    env = _environment()
    env.globals.update(secret=resolver.shared, device_secret=resolver.device)
    try:
        config = env.from_string(template.source(source)).render(**context)
    except TemplateError as exc:
        raise RenderError(f"{template.key}/{source}: {exc}") from exc
    except KeyError as exc:  # secret not found
        raise RenderError(f"{template.key}/{source}: missing secret {exc}") from exc

    config = "\n".join(line.rstrip() for line in config.splitlines()).strip() + "\n"
    return RenderResult(
        config=config,
        template=template,
        layers=lib.layer_names(facts.region, facts.site, facts.role) + ["device"],
        variables={k: v for k, v in context.items() if k not in ("device", "template")},
        secrets_used=sorted(set(resolver.used)),
    )


def unified_diff(before: str, after: str, *, before_name: str, after_name: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=before_name,
            tofile=after_name,
        )
    )
