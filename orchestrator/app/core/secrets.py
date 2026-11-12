"""Secret storage and redaction.

Secrets are only ever resolved at render time inside a pipeline run. Every value that is
resolved is registered with a :class:`Redactor`, and every piece of text that leaves the
pipeline (stage output, evidence, backups shown in the UI, reports, logs) is passed
through it, so no secret is visible anywhere outside the device itself.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets as pysecrets
import string
from abc import ABC, abstractmethod
from collections.abc import Callable

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import SecretRecord

log = logging.getLogger(__name__)

MASK = "********"
_DEV_KEY_SEED = b"hatch-insecure-development-key"


class SecretNotFound(KeyError):
    pass


class SecretStore(ABC):
    @abstractmethod
    def get(self, path: str) -> str: ...

    @abstractmethod
    def put(self, path: str, value: str) -> None: ...

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    def get_or_create(self, path: str, factory: Callable[[], str]) -> str:
        """Return the secret at ``path``, creating it with ``factory()`` if it is missing."""
        if not self.exists(path):
            self.put(path, factory())
        return self.get(path)


def _fernet(settings: Settings) -> Fernet:
    if settings.secret_key:
        return Fernet(settings.secret_key.encode())
    if settings.env == "prod":
        raise RuntimeError("HATCH_SECRET_KEY must be set in production")
    key = base64.urlsafe_b64encode(hashlib.sha256(_DEV_KEY_SEED).digest())
    return Fernet(key)


class LocalSecretStore(SecretStore):
    """Secrets encrypted with Fernet (AES-128-CBC + HMAC) in Hatch's own database."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.fernet = _fernet(settings or get_settings())

    def get(self, path: str) -> str:
        record = self.session.get(SecretRecord, path)
        if record is None:
            raise SecretNotFound(path)
        try:
            return self.fernet.decrypt(record.ciphertext.encode()).decode()
        except InvalidToken as exc:  # wrong key
            raise RuntimeError(f"cannot decrypt secret {path}: wrong HATCH_SECRET_KEY") from exc

    def put(self, path: str, value: str) -> None:
        ciphertext = self.fernet.encrypt(value.encode()).decode()
        record = self.session.get(SecretRecord, path)
        if record is None:
            self.session.add(SecretRecord(path=path, ciphertext=ciphertext))
        else:
            record.ciphertext = ciphertext
        self.session.flush()

    def exists(self, path: str) -> bool:
        return self.session.get(SecretRecord, path) is not None

    def get_or_create(self, path: str, factory: Callable[[], str]) -> str:
        """Race-safe: concurrent pipelines may both try to create the same shared secret.
        The insert runs in a SAVEPOINT; the loser rolls back and reads the winner's value."""
        if self.session.get(SecretRecord, path) is None:
            ciphertext = self.fernet.encrypt(factory().encode()).decode()
            try:
                with self.session.begin_nested():
                    self.session.add(SecretRecord(path=path, ciphertext=ciphertext))
            except IntegrityError:
                self.session.expire_all()
        return self.get(path)


def get_store(session: Session) -> SecretStore:
    settings = get_settings()
    if settings.secret_backend == "vault":
        from app.integrations.vault import VaultSecretStore

        return VaultSecretStore(settings)
    return LocalSecretStore(session, settings)


def generate_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!#%+-=?@^_"
    while True:
        value = "".join(pysecrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in value)
            and any(c.isupper() for c in value)
            and any(c.isdigit() for c in value)
            and any(c in "!#%+-=?@^_" for c in value)
        ):
            return value


class Redactor:
    """Replaces every registered secret value with a mask."""

    def __init__(self) -> None:
        self._values: set[str] = set()

    def register(self, value: str) -> str:
        if value and len(value) >= 4:
            self._values.add(value)
        return value

    def __call__(self, text: str) -> str:
        if not text:
            return text
        for value in sorted(self._values, key=len, reverse=True):
            text = text.replace(value, MASK)
        return text

    def __len__(self) -> int:
        return len(self._values)


class SecretResolver:
    """Resolves ``secret()`` / ``device_secret()`` calls made from templates.

    * ``preview`` mode never touches the store and returns a visible placeholder.
    * ``live`` mode fetches (or, for per-device credentials, generates) real values and
      registers them with the redactor.
    """

    def __init__(
        self,
        store: SecretStore | None,
        redactor: Redactor,
        *,
        serial: str,
        live: bool,
        auto_create_shared: bool,
    ) -> None:
        self.store = store
        self.redactor = redactor
        self.serial = serial
        self.live = live
        self.auto_create_shared = auto_create_shared
        self.used: list[str] = []

    def shared(self, path: str) -> str:
        self.used.append(path)
        if not self.live:
            return f"{{{{ secret:{path} }}}}"
        assert self.store is not None
        if not self.store.exists(path):
            if not self.auto_create_shared:
                raise SecretNotFound(path)
            log.warning("secret %s missing; generating a development value", path)
        return self.redactor.register(self.store.get_or_create(path, generate_password))

    def device(self, name: str) -> str:
        path = f"devices/{self.serial}/{name}"
        self.used.append(path)
        if not self.live:
            return f"{{{{ device_secret:{name} }}}}"
        assert self.store is not None
        return self.redactor.register(self.store.get_or_create(path, generate_password))


_PLACEHOLDER = re.compile(r"\{\{ (device_)?secret:[^}]+ \}\}")


def is_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER.search(text))
