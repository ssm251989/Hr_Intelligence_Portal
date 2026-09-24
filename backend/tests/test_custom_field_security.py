"""Part 5's field_security (platform.iam.field_security) applied to a Part 6 custom
field's `code` -- proves the two parts interlock exactly as Part 6 section 1 says they
must ("Field-level security from Part 5 applies to custom fields too")."""

import uuid

from app.core.security import hash_password
from app.models.iam import FieldSecurity, Role, RoleAssignment
from app.models.metadata import CustomFieldDef
from app.models.user import User
from app.platform.iam.field_security import apply_field_security, filter_write_fields
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="t", isolation="dedicated_db")


def _make_user(db_session) -> User:
    user = User(email=f"cfs-{uuid.uuid4().hex[:8]}@example.com", hashed_password=hash_password("x"), full_name="T", role="recruiter")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_a_custom_field_marked_sensitive_can_still_be_masked_by_field_security(db_session):
    db_session.add(CustomFieldDef(tenant_id=TENANT_1_ID, entity="candidate", code="passport_number", type="text", label_i18n={"en": "Passport #"}, sensitive=True))
    db_session.commit()

    user = _make_user(db_session)
    role = Role(tenant_id=TENANT_1_ID, name="NoPassportView", permissions=[])
    db_session.add(role)
    db_session.commit()
    db_session.refresh(role)
    db_session.add(RoleAssignment(tenant_id=TENANT_1_ID, user_id=user.id, role_id=role.id, scope_type="all"))
    db_session.add(FieldSecurity(tenant_id=TENANT_1_ID, entity="candidate", field="passport_number", role_id=role.id, access="masked"))
    db_session.commit()

    # candidates.custom_fields is itself a flat dict {code: value} -- field_security's own
    # "field" name is the custom field's `code`, applied the identical way it already
    # applies to a standard column.
    obj = {"full_name": "Jane Doe", "passport_number": "X1234567"}
    result = apply_field_security(db_session, TENANT, user, "candidate", obj)
    assert result["full_name"] == "Jane Doe"
    assert result["passport_number"] != "X1234567"


def test_a_custom_field_with_no_field_security_rule_is_unrestricted(db_session):
    db_session.add(CustomFieldDef(tenant_id=TENANT_1_ID, entity="candidate", code="referral_source", type="text", label_i18n={"en": "Referral"}))
    db_session.commit()
    user = _make_user(db_session)

    result = apply_field_security(db_session, TENANT, user, "candidate", {"referral_source": "LinkedIn"})
    assert result["referral_source"] == "LinkedIn"


def test_write_to_a_hidden_custom_field_is_stripped(db_session):
    user = _make_user(db_session)
    role = Role(tenant_id=TENANT_1_ID, name="NoBankWrite", permissions=[])
    db_session.add(role)
    db_session.commit()
    db_session.refresh(role)
    db_session.add(RoleAssignment(tenant_id=TENANT_1_ID, user_id=user.id, role_id=role.id, scope_type="all"))
    db_session.add(FieldSecurity(tenant_id=TENANT_1_ID, entity="candidate", field="bank_account", role_id=role.id, access="read"))
    db_session.commit()

    filtered = filter_write_fields(db_session, TENANT, user, "candidate", {"full_name": "Jane", "bank_account": "12345"})
    assert filtered == {"full_name": "Jane"}
