"""SecretStore (docs/HRMS_COMPLETE_SPEC.txt Part 2 section 5): interface + the one real
backend built so far, DbEncryptedSecretStore. VaultSecretStore / AwsSecretsManagerStore /
AzureKeyVaultStore are Part 13 deployment concerns this app doesn't yet have infrastructure
to actually exercise -- stubs only, selected (like DbEncryptedSecretStore) by the deployment
env var SECRET_BACKEND, so swapping backends later never touches calling code.

Envelope encryption: MASTER_KEY (env, this installation's own deployment secret -- allowed
in code per section A's "definitions, not tenant values" carve-out) wraps a per-scope,
randomly generated data-encryption key (DEK); the DEK -- never MASTER_KEY directly --
encrypts each secret's plaintext. A "scope" is whatever partition the caller wants a
separate DEK for. Today: "control_plane" for the tenant-DSN bootstrapping secrets a tenant
needs before its own database is even reachable (see platform/tenancy/engines.py). Once
Part 3 adds tenant-scoped connection secrets, each tenant_id becomes its own scope, backed
by the same mechanism against the tenant's own `secrets`/`secret_scopes` tables. Rotating
MASTER_KEY only means re-wrapping each scope's small DEK, never re-encrypting every secret.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.core.config import settings


class SecretNotFoundError(Exception):
    pass


class SecretAlreadyExistsError(Exception):
    pass


class SecretStore(ABC):
    @abstractmethod
    def put(self, ref: str, plaintext: str, *, created_by: str) -> None:
        """Creates a new secret at `ref`. Raises SecretAlreadyExistsError if one exists --
        use rotate() to change an existing secret's value."""

    @abstractmethod
    def get(self, ref: str) -> str:
        """Raises SecretNotFoundError if `ref` doesn't exist."""

    @abstractmethod
    def rotate(self, ref: str, plaintext: str, *, created_by: str) -> None:
        """Raises SecretNotFoundError if `ref` doesn't exist -- use put() to create one."""

    @abstractmethod
    def delete(self, ref: str) -> None:
        """A no-op, never an error, if `ref` doesn't exist."""


class DbEncryptedSecretStore(SecretStore):
    """`secret_model`/`scope_model` are the two ORM classes (from whichever database this
    scope's secrets actually live in -- the control-plane DB for scope="control_plane",
    or a tenant's own DB once Part 3 exists) with the shape:
      secret_model:  scope, ref, backend, ciphertext, key_version, created_by, rotated_at
                     (unique on (scope, ref))
      scope_model:   scope (PK), wrapped_dek
    """

    def __init__(self, db: Session, secret_model, scope_model, scope: str):
        self.db = db
        self.secret_model = secret_model
        self.scope_model = scope_model
        self.scope = scope
        if not settings.MASTER_KEY:
            raise RuntimeError("MASTER_KEY is not configured -- cannot encrypt/decrypt secrets")
        self._master_fernet = Fernet(settings.MASTER_KEY.encode())

    def _dek_fernet(self) -> Fernet:
        scope_row = self.db.query(self.scope_model).filter(self.scope_model.scope == self.scope).first()
        if scope_row is None:
            dek = Fernet.generate_key()
            scope_row = self.scope_model(scope=self.scope, wrapped_dek=self._master_fernet.encrypt(dek).decode())
            self.db.add(scope_row)
            self.db.commit()
        else:
            dek = self._master_fernet.decrypt(scope_row.wrapped_dek.encode())
        return Fernet(dek)

    def _find(self, ref: str):
        return (
            self.db.query(self.secret_model)
            .filter(self.secret_model.scope == self.scope, self.secret_model.ref == ref)
            .first()
        )

    def put(self, ref: str, plaintext: str, *, created_by: str) -> None:
        if self._find(ref) is not None:
            raise SecretAlreadyExistsError(ref)
        ciphertext = self._dek_fernet().encrypt(plaintext.encode()).decode()
        row = self.secret_model(
            scope=self.scope, ref=ref, backend="db_encrypted", ciphertext=ciphertext,
            key_version=1, created_by=created_by,
        )
        self.db.add(row)
        self.db.commit()

    def get(self, ref: str) -> str:
        row = self._find(ref)
        if row is None:
            raise SecretNotFoundError(ref)
        return self._dek_fernet().decrypt(row.ciphertext.encode()).decode()

    def rotate(self, ref: str, plaintext: str, *, created_by: str) -> None:
        row = self._find(ref)
        if row is None:
            raise SecretNotFoundError(ref)
        row.ciphertext = self._dek_fernet().encrypt(plaintext.encode()).decode()
        row.key_version += 1
        row.rotated_at = datetime.now(timezone.utc)
        row.created_by = created_by
        self.db.commit()

    def delete(self, ref: str) -> None:
        row = self._find(ref)
        if row is not None:
            self.db.delete(row)
            self.db.commit()


class _NotYetImplementedSecretStore(SecretStore):
    """Common base for the three deployment backends this app declares a config surface
    for (SECRET_BACKEND) but has no real infrastructure to exercise yet -- see Part 13."""

    backend_name = "override-me"

    def _unavailable(self):
        raise NotImplementedError(
            f"SECRET_BACKEND={self.backend_name!r} is not implemented yet (see "
            "docs/HRMS_COMPLETE_SPEC.txt Part 13) -- use SECRET_BACKEND=db_encrypted."
        )

    def put(self, ref: str, plaintext: str, *, created_by: str) -> None:
        self._unavailable()

    def get(self, ref: str) -> str:
        self._unavailable()

    def rotate(self, ref: str, plaintext: str, *, created_by: str) -> None:
        self._unavailable()

    def delete(self, ref: str) -> None:
        self._unavailable()


class VaultSecretStore(_NotYetImplementedSecretStore):
    backend_name = "vault"


class AwsSecretsManagerStore(_NotYetImplementedSecretStore):
    backend_name = "aws_secrets_manager"


class AzureKeyVaultStore(_NotYetImplementedSecretStore):
    backend_name = "azure_key_vault"


_BACKENDS = {
    "vault": VaultSecretStore,
    "aws_secrets_manager": AwsSecretsManagerStore,
    "azure_key_vault": AzureKeyVaultStore,
}


def get_secret_store(db: Session, secret_model, scope_model, scope: str) -> SecretStore:
    """Dispatches on settings.SECRET_BACKEND. db_encrypted (the default, and the only
    backend actually implemented) needs `secret_model`/`scope_model` from whichever
    database `scope` belongs to; the stub backends ignore them."""
    backend = settings.SECRET_BACKEND
    if backend == "db_encrypted":
        return DbEncryptedSecretStore(db, secret_model, scope_model, scope)
    stub_cls = _BACKENDS.get(backend)
    if stub_cls is None:
        raise ValueError(f"Unknown SECRET_BACKEND: {backend!r}")
    return stub_cls()
