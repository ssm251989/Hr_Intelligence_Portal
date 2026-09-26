"""Part 17 proof helper: call one API endpoint in-process and print the status + a trimmed body.

Goes through the real app (routing, validation, tenant middleware, permissions) with
FastAPI's TestClient. The signed-in user is supplied by overriding `get_current_user` with
an existing user picked by email or flat role -- no password, no token is created or read.
For local proof of Part 17 fixes only (docs/ui/FIXES_17.md); never used by the app.

    .venv/Scripts/python.exe scripts/probe.py GET /api/v1/home/funnel?period=90d --role admin
    .venv/Scripts/python.exe scripts/probe.py POST /api/v1/agencies --role admin --json '{"name": "Demo - X"}'
    ... [--email someone@x] [--host tenant.domain] [--max 1500]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("method")
    parser.add_argument("path")
    parser.add_argument("--role", default="admin")
    parser.add_argument("--email")
    parser.add_argument("--json")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--max", type=int, default=1500)
    parser.add_argument("--anon", action="store_true", help="call without a signed-in user")
    args = parser.parse_args()

    from fastapi.testclient import TestClient

    from app.auth import dependencies as deps
    from app.main import app
    from app.models.user import User
    from app.platform.tenancy.context import get_current_tenant

    def as_user(request: deps.Request, db=deps.Depends(deps.get_db)):
        tenant = get_current_tenant()
        q = db.query(User)
        if tenant is not None:
            q = q.filter(User.tenant_id == tenant.tenant_id)
        user = (q.filter(User.email == args.email) if args.email else q.filter(User.role == args.role)).order_by(User.created_at).first()
        if user is None:
            raise deps.HTTPException(status_code=401, detail="probe: no such user")
        if user.role == "agency" and not request.url.path.startswith(deps.AGENCY_ALLOWED_PREFIXES):
            raise deps.HTTPException(status_code=403, detail="Agency accounts can only use the agency portal")
        return user

    if not args.anon:
        app.dependency_overrides[deps.get_current_user] = as_user
    client = TestClient(app, base_url=f"http://{args.host}")
    body = json.loads(args.json) if args.json else None
    resp = client.request(args.method.upper(), args.path, json=body)
    text = resp.text
    try:
        text = json.dumps(resp.json(), indent=1, ensure_ascii=False, default=str)
    except Exception:
        pass
    print(f"{args.method.upper()} {args.path} -> {resp.status_code}")
    print(text[: args.max] + ("\n…(trimmed)" if len(text) > args.max else ""))
    return 0 if resp.status_code < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
