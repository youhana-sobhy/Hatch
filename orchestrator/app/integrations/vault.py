"""Secret backend for any HTTP secret engine that speaks the KV v2 protocol."""

from __future__ import annotations

import httpx

from app.config import Settings
from app.core.secrets import SecretNotFound, SecretStore


class VaultSecretStore(SecretStore):
    def __init__(self, settings: Settings) -> None:
        self.client = httpx.Client(
            base_url=settings.vault_addr.rstrip("/"),
            headers={"X-Vault-Token": settings.vault_token},
            timeout=10,
        )
        self.mount = settings.vault_mount

    def _url(self, path: str) -> str:
        return f"/v1/{self.mount}/data/hatch/{path}"

    def get(self, path: str) -> str:
        response = self.client.get(self._url(path))
        if response.status_code == 404:
            raise SecretNotFound(path)
        response.raise_for_status()
        return response.json()["data"]["data"]["value"]

    def put(self, path: str, value: str) -> None:
        response = self.client.post(self._url(path), json={"data": {"value": value}})
        response.raise_for_status()

    def exists(self, path: str) -> bool:
        try:
            self.get(path)
        except SecretNotFound:
            return False
        return True
