"""local_disk provider (docs/HRMS_COMPLETE_SPEC.txt Part 3 section 2, marked "(dev only)")
-- StorageProvider backed by a plain directory on the server's own filesystem. Matches
this app's actual current storage behavior (candidates/storage.py's UPLOAD_DIR) -- a real,
useful default for a single-installation deployment, not just a placeholder; s3_compatible
is the production-shaped alternative once a client needs object storage that isn't tied to
one server's own disk.
"""

from pathlib import Path

from app.platform.connectors.capabilities import ProviderResult

PROVIDER_CODE = "local_disk"
CAPABILITIES = ("StorageProvider",)
CONFIG_SCHEMA = {"type": "object", "required": ["root_path"], "properties": {"root_path": {"type": "string"}}}
SECRET_FIELDS = ()


class LocalDiskAdapter:
    def __init__(self, config: dict, secrets: dict):
        self.root = Path(config["root_path"])

    def _resolve(self, key: str) -> Path:
        # Rejects a key that would escape root via ".." -- the one thing a local
        # filesystem backend must guard against that a real object store's flat key
        # namespace makes structurally impossible.
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError(f"Invalid storage key (escapes root): {key}")
        return target

    def put(self, key: str, content: bytes, content_type: str) -> ProviderResult:
        try:
            target = self._resolve(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            return ProviderResult(success=True)
        except (OSError, ValueError) as exc:
            return ProviderResult(success=False, error=str(exc))

    def get(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def signed_url(self, key: str, expires_in_seconds: int) -> str:
        # No real signing on a local filesystem -- this app's own auth already gates
        # every file-serving endpoint (see api/client.ts's own comment on why images are
        # fetched as authenticated blobs, not bare <img src>). Returned for interface
        # parity with a real object store; callers on this backend don't need it.
        return f"file://{self._resolve(key)}"

    def delete(self, key: str) -> ProviderResult:
        try:
            self._resolve(key).unlink(missing_ok=True)
            return ProviderResult(success=True)
        except (OSError, ValueError) as exc:
            return ProviderResult(success=False, error=str(exc))

    def test_connection(self) -> ProviderResult:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".connection_test"
            probe.write_bytes(b"ok")
            probe.unlink()
            return ProviderResult(success=True)
        except OSError as exc:
            return ProviderResult(success=False, error=str(exc))

    def health_check(self) -> ProviderResult:
        return ProviderResult(success=self.root.exists())
