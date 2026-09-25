"""hrctl superadmin create|disable (docs/HRMS_COMPLETE_SPEC.txt Part 13 section B:
"Super-Admin console ... MFA mandatory").

`create` sets the password (read from stdin, never argv) and ALWAYS enrols a TOTP secret,
stored in the control-plane SecretStore; the otpauth:// URI is printed once for the
authenticator app. There is no way to create a console admin without MFA.

    echo "<password>" | python -m hrctl.superadmin create --email <email>
    python -m hrctl.superadmin disable --email <email>
"""

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hrctl superadmin")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--email", required=True)
    disable = sub.add_parser("disable")
    disable.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    import pyotp

    from app.core.security import hash_password
    from app.platform.secrets.store import get_secret_store
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import ControlPlaneSecret, ControlPlaneSecretScope, PlatformAdmin
    from app.platform.tenancy.provisioning import CONTROL_PLANE_SECRET_SCOPE, put_or_rotate

    cp_db = ControlPlaneSessionLocal()
    try:
        admin = cp_db.query(PlatformAdmin).filter(PlatformAdmin.email == args.email.lower()).first()
        if args.command == "disable":
            if admin is None:
                print("error: no such admin", file=sys.stderr)
                return 2
            admin.is_active = False
            cp_db.commit()
            print(f"disabled {admin.email}")
            return 0
        password = sys.stdin.readline().rstrip("\n")
        if len(password) < 14:
            print("error: console passwords must be at least 14 characters", file=sys.stderr)
            return 2
        if admin is None:
            admin = PlatformAdmin(email=args.email.lower())
            cp_db.add(admin)
            cp_db.flush()
        secret = pyotp.random_base32()
        ref = f"platform-admin-{admin.id}-totp"
        put_or_rotate(get_secret_store(cp_db, ControlPlaneSecret, ControlPlaneSecretScope, CONTROL_PLANE_SECRET_SCOPE), ref, secret)
        admin.password_hash = hash_password(password)
        admin.mfa_secret_ref = ref
        admin.is_active = True
        cp_db.commit()
        print("Add this to your authenticator app (shown once):")
        print(pyotp.TOTP(secret).provisioning_uri(name=admin.email, issuer_name="HRMS Console"))
        return 0
    finally:
        cp_db.close()


if __name__ == "__main__":
    sys.exit(main())
