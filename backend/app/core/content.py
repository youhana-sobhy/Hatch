"""Loads Hatch's governed content from disk: device catalog, sites, variable layers and the
golden template library.

Layout (see ``golden-templates/README.md``)::

    golden-templates/
      _catalog/models.yaml          vendor / model / allowed roles
      _layers/global.yaml           global baseline
      _layers/regions/<region>.yaml region overrides
      _layers/sites/<site>.yaml     site overrides (+ management prefix, naming)
      _layers/roles/<role>.yaml     role defaults
      <vendor>/<role>/template.yaml metadata (version, status, owner, example vars)
      <vendor>/<role>/config.j2     Day-1 golden configuration
      <vendor>/<role>/day0.j2       optional Day-0 bootstrap (ZTP)
"""

from __future__ import annotations

import copy
import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def deep_merge(*layers: dict[str, Any]) -> dict[str, Any]:
    """Merge mappings left to right. Nested dicts merge; lists and scalars are replaced."""
    result: dict[str, Any] = {}
    for layer in layers:
        for key, value in (layer or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
    return result


@dataclass(frozen=True)
class Template:
    vendor: str
    role: str
    version: str
    status: str
    owner: str
    description: str
    path: Path
    content_sha: str
    has_day0: bool
    example: dict[str, Any] = field(default_factory=dict)
    required_vars: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.vendor}/{self.role}"

    @property
    def full_version(self) -> str:
        """Semantic version plus a content hash, so any edit yields a new identity."""
        return f"{self.version}+{self.content_sha[:10]}"

    def source(self, name: str = "config.j2") -> str:
        return (self.path / name).read_text(encoding="utf-8")


@dataclass(frozen=True)
class Site:
    name: str
    region: str
    mgmt_prefix: str
    mgmt_gateway: str
    description: str = ""
    hostname_pattern: str = "{site}-{role}-{index:02d}"


@dataclass(frozen=True)
class Model:
    name: str
    vendor: str
    roles: tuple[str, ...]
    description: str = ""


class ContentLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.models: dict[str, Model] = {}
        self.sites: dict[str, Site] = {}
        self.templates: dict[str, Template] = {}
        self.layers: dict[str, dict[str, Any]] = {}
        self.load()

    # ------------------------------------------------------------------ loading
    def load(self) -> None:
        catalog = _load_yaml(self.root / "_catalog" / "models.yaml").get("models", {})
        self.models = {
            name: Model(
                name=name,
                vendor=spec["vendor"],
                roles=tuple(spec.get("roles", [])),
                description=spec.get("description", ""),
            )
            for name, spec in catalog.items()
        }

        layers_dir = self.root / "_layers"
        self.layers = {"global": _load_yaml(layers_dir / "global.yaml")}
        for kind in ("regions", "sites", "roles"):
            for file in sorted((layers_dir / kind).glob("*.yaml")):
                self.layers[f"{kind}/{file.stem}"] = _load_yaml(file)

        self.sites = {}
        for key, data in self.layers.items():
            if not key.startswith("sites/"):
                continue
            meta = data.get("site", {})
            name = key.split("/", 1)[1]
            self.sites[name] = Site(
                name=name,
                region=meta["region"],
                mgmt_prefix=meta["mgmt_prefix"],
                mgmt_gateway=meta["mgmt_gateway"],
                description=meta.get("description", ""),
                hostname_pattern=meta.get("hostname_pattern", "{site}-{role}-{index:02d}"),
            )

        self.templates = {}
        for meta_file in sorted(self.root.glob("*/*/template.yaml")):
            tdir = meta_file.parent
            if tdir.parent.name.startswith("_"):
                continue
            meta = _load_yaml(meta_file)
            digest = hashlib.sha256()
            for file in sorted(tdir.iterdir()):
                if file.is_file():
                    digest.update(file.name.encode())
                    digest.update(file.read_bytes())
            template = Template(
                vendor=tdir.parent.name,
                role=tdir.name,
                version=str(meta.get("version", "0.0.0")),
                status=meta.get("status", "draft"),
                owner=meta.get("owner", "unassigned"),
                description=meta.get("description", ""),
                path=tdir,
                content_sha=digest.hexdigest(),
                has_day0=(tdir / "day0.j2").exists(),
                example=meta.get("example", {}) or {},
                required_vars=tuple(meta.get("required_vars", []) or []),
            )
            self.templates[template.key] = template

    # ------------------------------------------------------------------ queries
    def template_for(self, vendor: str, role: str) -> Template | None:
        return self.templates.get(f"{vendor}/{role}")

    def layered_vars(self, region: str, site: str, role: str) -> dict[str, Any]:
        """global -> region -> site -> role (device-specific vars are merged by the caller)."""
        site_layer = {k: v for k, v in self.layers.get(f"sites/{site}", {}).items() if k != "site"}
        return deep_merge(
            self.layers.get("global", {}),
            self.layers.get(f"regions/{region}", {}),
            site_layer,
            self.layers.get(f"roles/{role}", {}),
        )

    def layer_names(self, region: str, site: str, role: str) -> list[str]:
        names = ["global", f"regions/{region}", f"sites/{site}", f"roles/{role}"]
        return [n for n in names if n in self.layers]


_lock = threading.Lock()
_library: ContentLibrary | None = None


def library() -> ContentLibrary:
    global _library
    with _lock:
        if _library is None or _library.root != get_settings().templates_dir:
            _library = ContentLibrary(get_settings().templates_dir)
        return _library


def reload_library() -> ContentLibrary:
    global _library
    with _lock:
        _library = ContentLibrary(get_settings().templates_dir)
        return _library
