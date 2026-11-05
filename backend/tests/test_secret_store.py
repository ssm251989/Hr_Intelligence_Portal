"""platform/secrets/store.py -- roundtrip, rotation, no plaintext in API (Part 2 CHECKS)."""

import pytest

from app.models.secret import Secret, SecretScope
from app.platform.secrets.store import (
    DbEncryptedSecretStore,
    SecretAlreadyExistsError,
    SecretNotFoundError,
    get_secret_store,
)


def _store(db_session, scope="test-scope"):
    return get_secret_store(db_session, Secret, SecretScope, scope)


def test_put_then_get_roundtrips_the_plaintext(db_session):
    store = _store(db_session)
    store.put("smtp-password", "hunter2", created_by="admin@example.com")
    assert store.get("smtp-password") == "hunter2"


def test_ciphertext_never_equals_the_plaintext_in_the_db(db_session):
    store = _store(db_session)
    store.put("smtp-password", "hunter2", created_by="admin@example.com")
    row = db_session.query(Secret).filter(Secret.ref == "smtp-password").first()
    assert row.ciphertext != "hunter2"
    assert "hunter2" not in row.ciphertext


def test_put_raises_if_the_ref_already_exists(db_session):
    store = _store(db_session)
    store.put("smtp-password", "hunter2", created_by="admin@example.com")
    with pytest.raises(SecretAlreadyExistsError):
        store.put("smtp-password", "different", created_by="admin@example.com")


def test_get_raises_for_an_unknown_ref(db_session):
    store = _store(db_session)
    with pytest.raises(SecretNotFoundError):
        store.get("does-not-exist")


def test_rotate_changes_the_value_and_bumps_key_version(db_session):
    store = _store(db_session)
    store.put("smtp-password", "hunter2", created_by="admin@example.com")
    store.rotate("smtp-password", "hunter3", created_by="admin@example.com")
    assert store.get("smtp-password") == "hunter3"
    row = db_session.query(Secret).filter(Secret.ref == "smtp-password").first()
    assert row.key_version == 2


def test_rotate_raises_for_an_unknown_ref(db_session):
    store = _store(db_session)
    with pytest.raises(SecretNotFoundError):
        store.rotate("does-not-exist", "x", created_by="admin@example.com")


def test_delete_is_a_no_op_for_an_unknown_ref(db_session):
    store = _store(db_session)
    store.delete("does-not-exist")  # must not raise


def test_delete_removes_the_row(db_session):
    store = _store(db_session)
    store.put("smtp-password", "hunter2", created_by="admin@example.com")
    store.delete("smtp-password")
    with pytest.raises(SecretNotFoundError):
        store.get("smtp-password")


def test_different_scopes_get_different_data_encryption_keys(db_session):
    """Envelope encryption (see store.py's own module docstring): two scopes must not
    share a DEK -- confirmed here by each scope getting its own secret_scopes row with a
    genuinely different wrapped_dek, not just different ciphertext."""
    store_a = _store(db_session, scope="scope-a")
    store_b = _store(db_session, scope="scope-b")
    store_a.put("same-ref", "value-a", created_by="admin@example.com")
    store_b.put("same-ref", "value-b", created_by="admin@example.com")

    scope_a_row = db_session.query(SecretScope).filter(SecretScope.scope == "scope-a").first()
    scope_b_row = db_session.query(SecretScope).filter(SecretScope.scope == "scope-b").first()
    assert scope_a_row.wrapped_dek != scope_b_row.wrapped_dek
    assert store_a.get("same-ref") == "value-a"
    assert store_b.get("same-ref") == "value-b"


def test_master_key_required(db_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MASTER_KEY", "")
    with pytest.raises(RuntimeError):
        DbEncryptedSecretStore(db_session, Secret, SecretScope, "test-scope")
