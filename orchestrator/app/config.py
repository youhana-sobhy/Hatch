"""Runtime configuration, loaded from environment variables prefixed with ``HATCH_``."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class ApiToken(BaseModel):
    """A static API token bound to a user, a role and an optional site scope."""

    token: str
    user: str
    role: Literal["requester", "approver", "maintainer", "admin", "service"]
    sites: list[str] = Field(default_factory=lambda: ["*"])


DEV_TOKENS: list[ApiToken] = [
    ApiToken(token="dev-requester", user="rana.requester", role="requester"),
    ApiToken(token="dev-approver", user="adam.approver", role="approver"),
    ApiToken(token="dev-maintainer", user="mona.maintainer", role="maintainer"),
    ApiToken(token="dev-admin", user="omar.admin", role="admin"),
    ApiToken(token="dev-ztp-service", user="ztp-service", role="service"),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HATCH_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "sqlite:///./hatch.db"

    # Content directories (golden templates, compliance rules, pipelines, policies).
    templates_dir: Path = REPO_ROOT / "templates"
    compliance_dir: Path = REPO_ROOT / "compliance" / "rules"
    pipelines_dir: Path = REPO_ROOT / "pipelines"
    policies_file: Path = REPO_ROOT / "policies" / "approval.yaml"
    backup_dir: Path = Path("./var/backups")

    # Execution: "thread" runs pipelines on a background worker pool, "inline" runs them in
    # the calling request (deterministic, used by the test-suite).
    executor: Literal["thread", "inline"] = "thread"
    workers: int = 4

    # Device driver used to talk to real devices. "simulated" ships an in-memory virtual
    # device fleet so the full flow can be demoed and tested without hardware.
    driver: Literal["simulated", "ssh"] = "simulated"

    # Secrets: "local" keeps secrets encrypted in Hatch's own database, "vault" uses a
    # KV v2 compatible HTTP secret engine.
    secret_backend: Literal["local", "vault"] = "local"
    secret_key: str = ""  # Fernet key; generated per process in dev when empty.
    vault_addr: str = "http://127.0.0.1:8200"
    vault_token: str = ""
    vault_mount: str = "secret"

    # Auth
    api_tokens: str = ""  # JSON list of ApiToken objects; dev tokens are used when empty.
    allow_self_approval: bool = False

    # Outbound integrations (all optional, generic webhooks)
    notify_webhook_url: str = ""
    monitoring_webhook_url: str = ""
    itsm_webhook_url: str = ""

    # ZTP
    public_ztp_url: str = "http://localhost:8081"
    ztp_token_ttl_minutes: int = 240

    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    allow_draft_templates: bool = False

    def tokens(self) -> list[ApiToken]:
        if self.api_tokens:
            return [ApiToken(**item) for item in json.loads(self.api_tokens)]
        if self.env == "prod":
            return []
        return DEV_TOKENS


@lru_cache
def get_settings() -> Settings:
    return Settings()
