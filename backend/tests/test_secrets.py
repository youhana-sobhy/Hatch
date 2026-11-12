"""Secret store behaviour, including concurrent first use of a shared secret."""

from app.config import get_settings
from app.core.secrets import LocalSecretStore
from app.db import create_all, init_engine, session_scope
from app.models import SecretRecord


def test_round_trip_is_encrypted_at_rest():
    init_engine(get_settings().database_url)
    create_all()
    with session_scope() as session:
        LocalSecretStore(session).put("aaa/tacacs_key", "s3cr3t-value")
    with session_scope() as session:
        record = session.get(SecretRecord, "aaa/tacacs_key")
        assert record is not None and "s3cr3t-value" not in record.ciphertext
        assert LocalSecretStore(session).get("aaa/tacacs_key") == "s3cr3t-value"


def test_get_or_create_loses_the_race_gracefully():
    """Two pipelines create the same shared secret at once: both must end up with one value."""
    init_engine(get_settings().database_url)
    create_all()

    def competing_factory() -> str:
        # Another worker commits the secret between our existence check and our insert.
        with session_scope() as other:
            LocalSecretStore(other).put("snmp/v3_auth", "winner-value")
        return "loser-value"

    with session_scope() as session:
        value = LocalSecretStore(session).get_or_create("snmp/v3_auth", competing_factory)
    assert value == "winner-value"
