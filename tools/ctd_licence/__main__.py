"""python -m ctd_licence  (run from the tools/ folder on a CTD PC)

  keygen                                         private key (encrypted with a passphrase) + public key
  config --approver x@ctdtechs.com [--support-email ...] [--support-phone ...] [--support-hours ...] [--out DIR]
                                                 ctd_config.json + ctd_config.json.sig for the zip / Settings > Licence
  approve <request | @file> [--modules a,b] [--valid-until 2027-12-31] [--yes]
                                                 shows the request, asks "Approve? [y/N]", prints the approval code
  inspect <code | request | @file> [--public-key PATH]
                                                 what it contains; for a code: is CTD's signature valid
Keys: CTD_LICENCE_HOME (default ~/.ctd_licence). Every approval is logged to approvals_log.csv there.
"""

import argparse
import json
import sys
from pathlib import Path

from ctd_licence import core


def _text(arg: str) -> str:
    if arg == "-":
        return sys.stdin.read()
    if arg.startswith("@"):
        return Path(arg[1:]).read_text(encoding="utf-8")
    return arg


def _show(title: str, data: dict) -> None:
    print(f"\n{title}")
    for k in ("number", "kind", "company", "slug", "admin_email", "modules", "adding", "app_version", "date", "issued_at", "valid_until",
              "install_id", "nonce"):
        if k in data:
            v = data[k]
            print(f"  {k:12} {', '.join(v) if isinstance(v, list) else v}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m ctd_licence", description="CTD Techs approvals (signed).")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--force", action="store_true")
    c = sub.add_parser("config")
    c.add_argument("--approver", required=True)
    c.add_argument("--support-email")
    c.add_argument("--support-phone")
    c.add_argument("--support-hours")
    c.add_argument("--out", type=Path)
    a = sub.add_parser("approve")
    a.add_argument("request")
    a.add_argument("--modules")
    a.add_argument("--valid-until")
    a.add_argument("--yes", action="store_true", help="do not ask (scripted use)")
    i = sub.add_parser("inspect")
    i.add_argument("text")
    i.add_argument("--public-key", type=Path)
    args = p.parse_args(argv)
    try:
        if args.cmd == "keygen":
            priv, pub = core.keygen(force=args.force)
            print(f"Private key (keep it OFF the server, back it up offline): {priv}\nPublic key (goes into the app): {pub}\n"
                  "Copy the public key to backend/app/platform/licence/ctd_public_key.pem before building the zip.")
        elif args.cmd == "config":
            cfg, sig = core.make_config(args.approver, support={"email": args.support_email, "phone": args.support_phone,
                                                                "hours": args.support_hours}, out=args.out)
            print(f"Signed CTD file: {cfg}\n                 {sig}")
        elif args.cmd == "approve":
            request = core.decode_request(_text(args.request))
            modules = [m.strip() for m in args.modules.split(",") if m.strip()] if args.modules else None
            payload = core.approval_payload(request, modules=modules, valid_until=args.valid_until)
            _show("Request", request)
            _show("Approval", payload)
            if not args.yes and input("\nApprove? [y/N] ").strip().lower() != "y":
                print("Not approved.")
                return 1
            code = core.sign_approval(payload, core.private_key())
            log = core.log_approval(request, payload)
            print(f"\nApproval code (email it back; logged in {log}):\n\n{code}\n")
        elif args.cmd == "inspect":
            text = _text(args.text).strip()
            if "".join(text.split()).startswith(core.REQUEST_PREFIX + "."):
                _show("Request (not signed - anyone can make one)", core.decode_request(text))
            else:
                key = None
                try:
                    key = core.public_key(path=args.public_key)
                except (OSError, core.ToolError):
                    pass
                payload, valid = core.read_approval(text, key)
                _show("Approval", payload)
                print("\n  signature   " + {True: "VALID (CTD Techs)", False: "NOT VALID - not made with CTD's key, or changed",
                                         None: "not checked (no public key)"}[valid])
                return 0 if valid is not False else 2
    except core.ToolError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError:
        print("Refused: that text is damaged.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
