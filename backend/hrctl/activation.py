"""Part 19.2: who gets module activation codes (CTD Techs only -- run on the server).

    .venv/Scripts/python.exe -m hrctl.activation show
    .venv/Scripts/python.exe -m hrctl.activation set-approver kg@ctdtechs.com [other@ctdtechs.com ...]
    .venv/Scripts/python.exe -m hrctl.activation requests [--status pending]

Every approver must be a ctdtechs.com address (ACTIVATION_ALLOWED_DOMAIN); anything else is refused.
"""

import argparse
import json
import sys


def main(argv=None) -> int:
    import hrctl  # noqa: F401 -- registers models
    from app.platform import activation

    parser = argparse.ArgumentParser(prog="hrctl activation")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="the approvers activation codes go to")
    s = sub.add_parser("set-approver", help="replace the approver list (ctdtechs.com only)")
    s.add_argument("emails", nargs="+")
    r = sub.add_parser("requests", help="activation requests across companies")
    r.add_argument("--status")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "show":
            print(json.dumps({"approvers": activation.approvers(), "allowed_domain": activation.settings.ACTIVATION_ALLOWED_DOMAIN}, indent=1))
        elif args.cmd == "set-approver":
            print(json.dumps({"approvers": activation.set_approvers(args.emails, actor="hrctl (server)")}, indent=1))
        else:
            print(json.dumps(activation.list_requests(args.status), indent=1, default=str))
    except activation.ActivationError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
