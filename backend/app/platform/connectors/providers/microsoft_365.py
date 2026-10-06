"""microsoft_365 provider (Part 20.2) -- MailboxAdmin through Microsoft Graph (Entra ID users).

Credentials: an app registration with the application permission `User.ReadWrite.All` (admin consent);
`client_id` + `client_secret` are secrets (SecretStore). A mailbox appears once the user has an Exchange
licence -- assign one by group-based licensing in Entra (`licence_group_id`, optional: the new user is
added to that group).

The first password is random, "change at next sign-in", returned ONCE to the caller (shown to HR on
screen) -- never stored, logged or emailed. NOTE: written against Microsoft's public Graph documentation;
not yet run against a live tenant (CTD Techs uses the TEST provider until one is connected).
"""

from typing import Optional

import httpx

from app.platform.connectors.capabilities import ProviderResult
from app.platform.connectors.providers.google_workspace import MailboxError, temp_password

PROVIDER_CODE = "microsoft_365"
CAPABILITIES = ("MailboxAdmin",)
CONFIG_SCHEMA = {"type": "object", "required": ["tenant_id", "domain"],
                 "properties": {"tenant_id": {"type": "string"}, "domain": {"type": "string"}, "usage_location": {"type": "string", "default": "IN"},
                                "licence_group_id": {"type": "string"}}}
SECRET_FIELDS = ("client_id", "client_secret")
GRAPH = "https://graph.microsoft.com/v1.0"


class Microsoft365Adapter:
    provider = "microsoft"

    def __init__(self, config: dict, secrets: dict):
        self.tenant_id = config.get("tenant_id") or ""
        self.domain = (config.get("domain") or "").lower()
        self.usage_location = config.get("usage_location") or "IN"
        self.licence_group_id = config.get("licence_group_id")
        self.client_id = secrets.get("client_id") or ""
        self.client_secret = secrets.get("client_secret") or ""

    def _token(self) -> str:
        r = httpx.post(f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token", timeout=20,
                       data={"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "client_credentials",
                             "scope": "https://graph.microsoft.com/.default"})
        if r.status_code >= 400:
            raise MailboxError(f"Microsoft sign-in failed ({r.status_code}): {r.text[:200]}")
        return r.json()["access_token"]

    def _call(self, method: str, path: str, body: Optional[dict] = None) -> httpx.Response:
        r = httpx.request(method, f"{GRAPH}{path}", headers={"Authorization": f"Bearer {self._token()}"}, json=body, timeout=20)
        if r.status_code >= 400 and r.status_code != 404:
            raise MailboxError(f"Microsoft said {r.status_code}: {r.text[:200]}")
        return r

    def is_free(self, address: str) -> bool:
        return self._call("GET", f"/users/{address}").status_code == 404

    def create_mailbox(self, *, address: str, first_name: str, last_name: str, display_name: str, employee_ref: str, actor: str) -> dict:
        pw = temp_password()
        r = self._call("POST", "/users", {
            "accountEnabled": True, "displayName": display_name, "givenName": first_name, "surname": last_name or None,
            "mailNickname": address.split("@")[0], "userPrincipalName": address, "usageLocation": self.usage_location, "employeeId": employee_ref,
            "passwordProfile": {"forceChangePasswordNextSignIn": True, "password": pw}})
        if self.licence_group_id:
            user_id = r.json().get("id")
            self._call("POST", f"/groups/{self.licence_group_id}/members/$ref", {"@odata.id": f"{GRAPH}/directoryObjects/{user_id}"})
        return {"address": address, "temp_password": pw, "note": "Microsoft asks them to choose a new password at first sign-in."}

    def suspend_mailbox(self, address: str, actor: str) -> dict:
        self._call("PATCH", f"/users/{address}", {"accountEnabled": False})
        return {"address": address, "status": "suspended"}

    def reactivate_mailbox(self, address: str, actor: str) -> dict:
        self._call("PATCH", f"/users/{address}", {"accountEnabled": True})
        return {"address": address, "status": "active"}

    def delete_mailbox(self, address: str, actor: str) -> dict:
        self._call("DELETE", f"/users/{address}")
        return {"address": address, "status": "deleted"}

    def test_connection(self) -> ProviderResult:
        try:
            self._call("GET", "/users?$top=1")
            return ProviderResult(success=True)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(success=False, error=str(exc)[:300])

    def health_check(self) -> ProviderResult:
        ok = bool(self.client_id and self.client_secret and self.tenant_id)
        return ProviderResult(success=ok, error=None if ok else "Client id / secret / tenant missing")
