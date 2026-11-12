"""Approval policy: which onboardings need a second pair of eyes.

``policies/approval.yaml`` holds an ordered list of rules; the first rule whose ``match``
block matches the onboarding wins. A match value can be a string, a list, or ``"*"``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings


@dataclass(frozen=True)
class PolicyDecision:
    require_approval: bool
    rule: str


def _matches(expected: Any, actual: str) -> bool:
    if expected in (None, "*"):
        return True
    if isinstance(expected, list):
        return actual in expected
    return str(expected) == actual


@lru_cache
def _load(path: Path, mtime: float) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_policies() -> dict[str, Any]:
    path = get_settings().policies_file
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return _load(path, mtime)


def approval_for(*, market: str, site: str, role: str, vendor: str, mode: str) -> PolicyDecision:
    policies = load_policies()
    facts = {"market": market, "site": site, "role": role, "vendor": vendor, "mode": mode}
    for rule in policies.get("rules", []):
        match = rule.get("match", {})
        if all(_matches(match.get(key), value) for key, value in facts.items()):
            return PolicyDecision(bool(rule.get("require_approval")), rule.get("name", "unnamed"))
    default = policies.get("default", {})
    return PolicyDecision(bool(default.get("require_approval", False)), "default")
