"""hrctl user check|unlock|reset-password -- tenant portal login recovery for local/UAT.

`check` prints every server-side gate /auth/login applies to one user (tenant resolved,
row visible through the RLS-bound APP_DATABASE_URL role, lockout, MFA requirement) and,
if a password is piped on stdin, whether it matches. `unlock` clears the failed-attempt
counter and lockout. `reset-password` sets a new password (stdin, never argv) and unlocks.
None of them touch MFA enrolment or the tenant's mfa_required setting.

    python -m hrctl.user check --email <email>            # gates only
    echo "<password>" | python -m hrctl.user check --email <email> --password-stdin
    python -m hrctl.user unlock --email <email>
    echo "<new password>" | python -m hrctl.user reset-password --email <email>
"""

import argparse
import sys
from datetime import datetime, timezone


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hrctl user")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--email", required=True)
    check.add_argument("--password-stdin", action="store_true")
    for name in ("unlock", "reset-password"):
        sub.add_parser(name).add_argument("--email", required=True)
    args = parser.parse_args(argv)

    import app.main  # noqa: F401 -- registers the settings registry the MFA check reads
    from app.core.database import SessionLocal
    from app.core.security import hash_password, verify_password
    from app.models.user import User
    from app.platform.iam import mfa, sessions
    from app.platform.tenancy.context import reset_current_tenant, set_current_tenant
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.middleware import _to_context
    from app.platform.tenancy.models_cp import Tenant

    cp_db = ControlPlaneSessionLocal()
    try:
        tenant = cp_db.query(Tenant).order_by(Tenant.created_at.asc()).first()
    finally:
        cp_db.close()
    if tenant is None:
        print("error: no tenant row in the control plane -- run hrctl.tenant bootstrap-existing", file=sys.stderr)
        return 2
    ctx = _to_context(tenant)
    token = set_current_tenant(ctx)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email).first()
        if user is None:
            print(f"error: {args.email} not visible in tenant {tenant.slug} (wrong email, or users.tenant_id != {tenant.id})", file=sys.stderr)
            return 2

        if args.command == "check":
            print(f"tenant: {tenant.slug} ({tenant.status})  user: {user.email} role={user.role} tenant_id={user.tenant_id}")
            print(f"locked: {sessions.is_locked_out(user)}  failed_attempts: {user.failed_login_attempts}")
            print(f"mfa_required: {mfa.is_mfa_required(db, ctx)}  mfa_enrolled: {mfa.is_mfa_enrolled(user)}")
            if args.password_stdin:
                ok = verify_password(sys.stdin.readline().rstrip("\n"), user.hashed_password)
                print(f"password matches: {ok}")
            return 0

        if args.command == "reset-password":
            password = sys.stdin.readline().rstrip("\n")
            if len(password) < 8:
                print("error: password must be at least 8 characters", file=sys.stderr)
                return 2
            user.hashed_password = hash_password(password)
            user.password_changed_at = datetime.now(timezone.utc)
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()
        print(f"{args.command}: {user.email} done")
        return 0
    finally:
        db.close()
        reset_current_tenant(token)


if __name__ == "__main__":
    sys.exit(main())
