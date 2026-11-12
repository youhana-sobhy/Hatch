"""``hatchctl``: template governance and developer tooling.

hatchctl templates lint            test-render every template and gate on the baseline
hatchctl templates render nxos/leaf [--vars extra.yaml]
hatchctl compliance check nxos running.cfg
hatchctl state-diagram             print the state machine as Mermaid
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from app.core import compliance
from app.core.content import Template, deep_merge, library
from app.core.rendering import DeviceFacts, RenderError, render
from app.core.secrets import Redactor, SecretResolver
from app.core.state_machine import mermaid

GATE = ("critical", "high")


def _facts(template: Template, extra: dict | None = None) -> DeviceFacts:
    ex = deep_merge(template.example, extra or {})
    return DeviceFacts(
        hostname=ex.get("hostname", f"lab-{template.role}-01"),
        serial=ex.get("serial", "LAB0000001"),
        vendor=template.vendor,
        model=ex["model"],
        role=template.role,
        site=ex["site"],
        region=library().sites[ex["site"]].region,
        mgmt_ip=ex["mgmt_ip"],
        mode=ex.get("mode", "push"),
        attributes={
            "uplinks": ex.get("uplinks", []),
            "vars": {
                **ex.get("vars", {}),
                "ztp": {
                    "callhome_url": "https://ztp.example/callhome",
                    "token": "T0KEN",
                    "serial": ex.get("serial", "LAB0000001"),
                },
            },
        },
    )


def _resolver(serial: str) -> SecretResolver:
    return SecretResolver(None, Redactor(), serial=serial, live=False, auto_create_shared=False)


def cmd_lint(args: argparse.Namespace) -> int:
    lib = library()
    failures = 0
    for template in sorted(lib.templates.values(), key=lambda t: t.key):
        problems: list[str] = []
        if not template.example:
            problems.append("template.yaml has no 'example' block for the test render")
        else:
            try:
                facts = _facts(template)
                result = render(lib, facts, _resolver(facts.serial))
                if template.has_day0:
                    render(lib, facts, _resolver(facts.serial), source="day0.j2")
                for item in compliance.scan(template.vendor, result.config):
                    if not item.passed and item.rule.severity in GATE:
                        problems.append(f"{item.rule.id} ({item.rule.severity}): {item.evidence}")
            except (RenderError, KeyError) as exc:
                problems.append(f"render failed: {exc}")
        status = "FAIL" if problems else "ok"
        print(f"[{status:>4}] {template.key:<22} {template.full_version:<20} {template.status}")
        for problem in problems:
            print(f"         - {problem}")
        failures += bool(problems)
    print(f"\n{len(lib.templates) - failures}/{len(lib.templates)} templates passed")
    return 1 if failures else 0


def cmd_render(args: argparse.Namespace) -> int:
    lib = library()
    template = lib.templates.get(args.template)
    if template is None:
        print(f"unknown template {args.template}", file=sys.stderr)
        return 2
    extra = yaml.safe_load(Path(args.vars).read_text()) if args.vars else None
    facts = _facts(template, extra)
    result = render(lib, facts, _resolver(facts.serial), source=args.source)
    sys.stdout.write(result.config)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    config = Path(args.config).read_text(encoding="utf-8")
    failed = 0
    for item in compliance.scan(args.vendor, config):
        mark = "PASS" if item.passed else "FAIL"
        print(f"[{mark}] {item.rule.id:<16} {item.rule.severity:<8} {item.rule.title}")
        if not item.passed:
            failed += 1
            print(f"       {item.evidence}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hatchctl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    templates = sub.add_parser("templates", help="golden template tooling")
    tsub = templates.add_subparsers(dest="action", required=True)
    tsub.add_parser("lint", help="test-render all templates").set_defaults(func=cmd_lint)
    render_p = tsub.add_parser("render", help="render one template with its example vars")
    render_p.add_argument("template")
    render_p.add_argument("--vars", help="YAML file merged over the example block")
    render_p.add_argument("--source", default="config.j2", choices=["config.j2", "day0.j2"])
    render_p.set_defaults(func=cmd_render)

    comp = sub.add_parser("compliance", help="baseline tooling")
    csub = comp.add_subparsers(dest="action", required=True)
    check = csub.add_parser("check", help="scan a config file against the baseline")
    check.add_argument("vendor")
    check.add_argument("config")
    check.set_defaults(func=cmd_check)

    sub.add_parser("state-diagram", help="print the state machine (Mermaid)").set_defaults(
        func=lambda _: print(mermaid()) or 0
    )

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
