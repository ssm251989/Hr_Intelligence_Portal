"""google_workspace provider (Part 20.2) -- MailboxAdmin through the Google Admin SDK Directory API.

Credentials: a service account with domain-wide delegation for the scope
`https://www.googleapis.com/auth/admin.directory.user`, acting as a Workspace admin (`admin_email`). The
service-account JSON is a secret (SecretStore), never in config, code or git.

Google needs a password when a user is created: a random one is made, the account is set to "change
password at next sign-in", and the password is returned ONCE to the caller (shown to HR on screen) --
never stored, logged or emailed. NOTE: written against Google's public API documentation; not yet run
against a live Workspace (CTD Techs uses the TEST provider until one is connected).
"""

import json
import secrets as _secrets
from typing import Optional

import httpx

from app.platform.connectors.capabilities import ProviderResult

PROVIDER_CODE = "google_workspace"
CAPABILITIES = ("MailboxAdmin",)
CONFIG_SCHEMA = {"type": "object", "required": ["domain", "admin_email"],
                 "properties": {"domain": {"type": "string"}, "admin_email": {"type": "string"}}}
SECRET_FIELDS = ("service_account_json",)
SCOPE = "https://www.googleapis.com/auth/admin.directory.user"
API = "https://admin.googleapis.com/admin/directory/v1"


class MailboxError(Exception):
    pass


def temp_password() -> str:
    return _secrets.token_urlsafe(12) + "aA1!"


class GoogleWorkspaceAdapter:
    provider = "google"

    def __init__(self, config: dict, secrets: dict):
        self.domain = (config.get("domain") or "").lower()
        self.admin_email = config.get("admin_email") or ""
        self.sa_json = secrets.get("service_account_json") or ""

    def _headers(self) -> dict:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        if not self.sa_json:
            raise MailboxError("The service-account key is missing.")
        info = json.loads(self.sa_json) if isinstance(self.sa_json, str) else self.sa_json
        creds = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE]).with_subject(self.admin_email)
        creds.refresh(Request())
        return {"Authorization": f"Bearer {creds.token}"}

    def _call(self, method: str, path: str, body: Optional[dict] = None) -> httpx.Response:
        r = httpx.request(method, f"{API}{path}", headers=self._headers(), json=body, timeout=20)
        if r.status_code >= 400 and r.status_code != 404:
            raise MailboxError(f"Google said {r.status_code}: {r.text[:200]}")
        return r

    def is_free(self, address: str) -> bool:
        return self._call("GET", f"/users/{address}").status_code == 404

    def create_mailbox(self, *, address: str, first_name: str, last_name: str, display_name: str, employee_ref: str, actor: str) -> dict:
        pw = temp_password()
        self._call("POST", "/users", {"primaryEmail": address, "name": {"givenName": first_name, "familyName": last_name or first_name},
                                      "password": pw, "changePasswordAtNextLogin": True, "externalIds": [{"value": employee_ref, "type": "organization"}]})
        return {"address": address, "temp_password": pw, "note": "Google asks them to choose a new password at first sign-in."}

    def suspend_mailbox(self, address: str, actor: str) -> dict:
        self._call("PUT", f"/users/{address}", {"suspended": True})
        return {"address": address, "status": "suspended"}

    def reactivate_mailbox(self, address: str, actor: str) -> dict:
        self._call("PUT", f"/users/{address}", {"suspended": False})
        return {"address": address, "status": "active"}

    def delete_mailbox(self, address: str, actor: str) -> dict:
        self._call("DELETE", f"/users/{address}")
        return {"address": address, "status": "deleted"}

    def test_connection(self) -> ProviderResult:
        try:
            self._call("GET", f"/users?domain={self.domain}&maxResults=1")
            return ProviderResult(success=True)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(success=False, error=str(exc)[:300])

    def health_check(self) -> ProviderResult:
        return ProviderResult(success=bool(self.sa_json and self.admin_email), error=None if self.sa_json else "No service-account key")
