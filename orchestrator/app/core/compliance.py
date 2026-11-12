"""Security-baseline compliance engine.

Rules live in ``compliance/rules/*.yaml``. ``common.yaml`` applies to every vendor; a file
named after a vendor (``nxos.yaml``) applies to that vendor only. Each rule declares one
or more checks evaluated line by line against the running configuration:

* ``must_match``      at least one line matches the regex
* ``must_not_match``  no line matches the regex
* ``must_match_all``  every regex in the list matches at least one line
* ``count_at_least``  ``{regex, min}``: at least ``min`` lines match
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings

SEVERITIES = ("critical", "high", "medium", "low")


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    severity: str
    vendors: tuple[str, ...]
    spec: dict[str, Any]
    remediation: str = ""


@dataclass(frozen=True)
class RuleResult:
    rule: Rule
    passed: bool
    evidence: str


def load_rules(directory: Path | None = None) -> list[Rule]:
    directory = directory or get_settings().compliance_dir
    rules: list[Rule] = []
    seen: set[str] = set()
    for file in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        vendors = tuple(data.get("vendors", [] if file.stem == "common" else [file.stem]))
        for raw in data.get("rules", []):
            rule_id = raw["id"]
            if rule_id in seen:
                raise ValueError(f"duplicate compliance rule id {rule_id} in {file.name}")
            seen.add(rule_id)
            severity = raw.get("severity", "medium")
            if severity not in SEVERITIES:
                raise ValueError(f"rule {rule_id}: unknown severity {severity}")
            spec = {
                k: v
                for k, v in raw.items()
                if k in ("must_match", "must_not_match", "must_match_all", "count_at_least")
            }
            if not spec:
                raise ValueError(f"rule {rule_id} declares no check")
            rules.append(
                Rule(
                    id=rule_id,
                    title=raw["title"],
                    severity=severity,
                    vendors=tuple(raw.get("vendors", vendors)),
                    spec=spec,
                    remediation=raw.get("remediation", ""),
                )
            )
    return rules


def rules_for(vendor: str, rules: list[Rule] | None = None) -> list[Rule]:
    rules = rules if rules is not None else load_rules()
    return [r for r in rules if not r.vendors or vendor in r.vendors]


def _matching(regex: str, lines: list[str]) -> list[str]:
    pattern = re.compile(regex)
    return [line for line in lines if pattern.search(line)]


def evaluate(rule: Rule, config: str) -> RuleResult:
    lines = config.splitlines()
    evidence: list[str] = []
    passed = True
    spec = rule.spec

    if "must_match" in spec:
        hits = _matching(spec["must_match"], lines)
        passed &= bool(hits)
        evidence.append(
            f"found: {hits[0].strip()}" if hits else f"missing line matching /{spec['must_match']}/"
        )
    if "must_not_match" in spec:
        hits = _matching(spec["must_not_match"], lines)
        passed &= not hits
        evidence.append(
            f"forbidden line present: {hits[0].strip()}"
            if hits
            else f"no line matches /{spec['must_not_match']}/"
        )
    if "must_match_all" in spec:
        for regex in spec["must_match_all"]:
            hits = _matching(regex, lines)
            passed &= bool(hits)
            evidence.append(f"found: {hits[0].strip()}" if hits else f"missing /{regex}/")
    if "count_at_least" in spec:
        cfg = spec["count_at_least"]
        hits = _matching(cfg["regex"], lines)
        ok = len(hits) >= int(cfg["min"])
        passed &= ok
        evidence.append(f"{len(hits)} line(s) match /{cfg['regex']}/ (need {cfg['min']})")

    return RuleResult(rule=rule, passed=passed, evidence="; ".join(evidence))


def scan(vendor: str, config: str, rules: list[Rule] | None = None) -> list[RuleResult]:
    return [evaluate(rule, config) for rule in rules_for(vendor, rules)]
