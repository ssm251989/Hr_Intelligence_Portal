"""hrctl setup -- internals of the one-step installation (Part 27).

Start an installation with `python -m app.platform.install` (it works before backend/.env
exists). This module holds the two steps that need the app's database settings, run by the
installer as subprocesses with JSON on stdin (passwords never on a command line):

    python -m hrctl.setup _admin      create / update the first administrator
    python -m hrctl.setup _modules    request module activation (or switch modules on for dev)
"""

import json
import sys

def _admin() -> int:
    """Internal (stdin JSON): create or update the first administrator."""
    from datetime import datetime, timezone

    import hrctl  # noqa: F401 -- models + tenant hooks
    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.models.user import User
    from app.platform.iam.roles import bridge_single_user
    from app.platform.tenancy.context import TENANT_1_ID, TenantContext, tenant_context

    data = json.loads(sys.stdin.read())
    tenant = TenantContext(tenant_id=TENANT_1_ID, slug=data["slug"], isolation="dedicated_db")
    with tenant_context(TENANT_1_ID):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == data["email"]).first()
            created = user is None
            if created:
                user = User(email=data["email"], role="admin")
                db.add(user)
            user.full_name, user.role = data["name"], "admin"
            user.hashed_password = hash_password(data["password"])
            now = datetime.now(timezone.utc)
            user.password_set_at = user.password_changed_at = now
            user.failed_login_attempts, user.locked_until, user.deactivated_at = 0, None, None
            db.commit()
            bridge_single_user(db, tenant, user)
            # M1 (Part 27): the first admin also gets an employee record, so My profile / Exits work from day one
            from app.employees import self_service

            if self_service.me(db, tenant, user) is None:
                self_service.link_own_record(db, tenant, user, mode="create")
        finally:
            db.close()
    print(json.dumps({"admin": data["email"], "created": created}))
    return 0


def _modules() -> int:
    """Internal (stdin JSON): request activation (normal) or switch modules on (dev)."""
    import hrctl  # noqa: F401
    from app.core.database import SessionLocal
    from app.models.user import User
    from app.platform import module_registry as reg, module_status
    from app.platform.settings.bootstrap_definitions import register_all
    from app.platform.tenancy.context import TENANT_1_ID, TenantContext, tenant_context

    data = json.loads(sys.stdin.read())
    register_all()
    keys = sorted(data.get("modules") or reg.CHOOSABLE)
    tenant = TenantContext(tenant_id=TENANT_1_ID, slug=data["slug"], isolation="dedicated_db")
    with tenant_context(TENANT_1_ID):
        db = SessionLocal()
        try:
            # Part 32: the install ends LOCKED with the company, admin and modules REQUESTED from CTD Techs; nothing opens
            # until CTD's signed approval code is entered on the waiting page. ("activate" only marks the rows - without
            # a CTD signature that switches nothing on.)
            user = db.query(User).filter(User.email == data["email"]).first()
            try:
                from app.platform import activation

                info = activation.request_access(db, tenant, keys, user)
                out = {"modules": "requested", "keys": keys, "request": info["number"], "sent": info["email_sent"]}
            except Exception as exc:  # noqa: BLE001 -- e.g. no signed CTD file yet: the waiting page offers "Load CTD file"
                db.rollback()
                module_status.mark_pending(db, tenant, keys, actor="setup")
                db.commit()
                out = {"modules": "pending", "keys": keys, "note": f"Access request not made yet ({exc}); the administrator does it on the "
                                                                   "waiting page after signing in."}
        finally:
            db.close()
    print(json.dumps(out))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_admin"]:
        return _admin()
    if argv[:1] == ["_modules"]:
        return _modules()
    from app.platform.install.__main__ import main as install_main

    return install_main(argv)


if __name__ == "__main__":
    sys.exit(main())
