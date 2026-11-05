"""test_mailbox provider (Part 20.2b) -- "Test email provider (dummy)".

Behaves exactly like a real MailboxAdmin provider to the rest of the app (create, is the address free,
suspend, reactivate, delete), but only writes rows in `test_mailboxes`: no real mailbox is created
anywhere. There is no password -- the dummy mailbox says "Password: managed by app invite" and the app's
own "Set your password" link is the only credential. Emails the app sends to these addresses are kept in
`test_mailbox_messages` and, in development, also delivered to mailpit (app/employees/test_inbox.py).
"""

from datetime import datetime, timezone

from app.platform.connectors.capabilities import ProviderResult

PROVIDER_CODE = "test_mailbox"
CAPABILITIES = ("MailboxAdmin",)
CONFIG_SCHEMA = {"type": "object", "properties": {"note": {"type": "string"}}}
SECRET_FIELDS = ()


class TestMailboxAdapter:
    __test__ = False  # not a pytest class
    provider = "test"

    def __init__(self, config: dict, secrets: dict):
        self.config = config

    def _db(self):
        from app.core.database import SessionLocal

        return SessionLocal()

    def _tenant_id(self):
        from app.platform.tenancy.context import get_current_tenant

        return get_current_tenant().tenant_id

    def _row(self, db, address: str):
        from app.models.test_mailbox import TestMailbox

        return db.query(TestMailbox).filter(TestMailbox.tenant_id == self._tenant_id(), TestMailbox.address == address.lower()).first()

    def is_free(self, address: str) -> bool:
        db = self._db()
        try:
            row = self._row(db, address)
            return row is None or row.status == "deleted"
        finally:
            db.close()

    def create_mailbox(self, *, address: str, first_name: str, last_name: str, display_name: str, employee_ref: str, actor: str) -> dict:
        from app.models.core_hr import Employee
        from app.models.test_mailbox import TestMailbox

        db = self._db()
        try:
            row = self._row(db, address)
            emp = db.query(Employee).filter(Employee.tenant_id == self._tenant_id(), Employee.employee_code == employee_ref).first()
            if row is None:
                row = TestMailbox(tenant_id=self._tenant_id(), address=address.lower(), created_by=actor[:120])
                db.add(row)
            elif row.status != "deleted":
                raise ValueError(f"{address} already exists in the test provider.")
            row.display_name, row.employee_code, row.status = display_name, employee_ref, "active"
            row.employee_id = emp.id if emp is not None else None
            row.updated_at = datetime.now(timezone.utc)
            db.commit()
            return {"address": address.lower(), "temp_password": None, "note": "Password: managed by app invite"}
        finally:
            db.close()

    def _set(self, address: str, status: str) -> dict:
        db = self._db()
        try:
            row = self._row(db, address)
            if row is None:
                raise ValueError(f"{address} isn't in the test provider.")
            row.status, row.updated_at = status, datetime.now(timezone.utc)
            db.commit()
            return {"address": address, "status": status}
        finally:
            db.close()

    def suspend_mailbox(self, address: str, actor: str) -> dict:
        return self._set(address, "suspended")

    def reactivate_mailbox(self, address: str, actor: str) -> dict:
        return self._set(address, "active")

    def delete_mailbox(self, address: str, actor: str) -> dict:
        return self._set(address, "deleted")

    def test_connection(self) -> ProviderResult:
        return ProviderResult(success=True)

    def health_check(self) -> ProviderResult:
        return ProviderResult(success=True)
