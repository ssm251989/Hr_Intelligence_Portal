"""Part 19.2 / 19.2b: who gets module activation codes (CTD Techs only -- run on the server).

    .venv/Scripts/python.exe -m hrctl.activation approvers list
    .venv/Scripts/python.exe -m hrctl.activation approvers set --priority 1 --name "KG" --email kg@ctdtechs.com [--inactive]
    .venv/Scripts/python.exe -m hrctl.activation approvers remove --priority 2
    .venv/Scripts/python.exe -m hrctl.activation requests [--status pending]
    .venv/Scripts/python.exe -m hrctl.activation sweep        (retries + escalation once, now)

Every approver must be a ctdtechs.com address; anything else is refused. Changes are audit-logged.
"""

import argparse
import json
import sys


def main(argv=None) -> int:
    import hrctl  # noqa: F401 -- registers models
    from app.platform import activation

    parser = argparse.ArgumentParser(prog="hrctl activation")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ap = sub.add_parser("approvers", help="the priority list activation codes go to")
    asub = ap.add_subparsers(dest="action", required=True)
    asub.add_parser("list")
    s = asub.add_parser("set")
    s.add_argument("--priority", type=int, required=True)
    s.add_argument("--email", required=True)
    s.add_argument("--name")
    s.add_argument("--inactive", action="store_true")
    rm = asub.add_parser("remove")
    rm.add_argument("--priority", type=int, required=True)
    r = sub.add_parser("requests", help="activation requests across companies")
    r.add_argument("--status")
    sub.add_parser("sweep", help="retry failed sends and escalate now")
    args = parser.parse_args(argv)

    actor = "hrctl (server)"
    try:
        if args.cmd == "approvers":
            if args.action == "list":
                out = activation.list_approvers()
            elif args.action == "set":
                out = activation.set_approver(args.priority, args.email, actor, name=args.name, active=not args.inactive)
            else:
                out = activation.remove_approver(args.priority, actor)
            print(json.dumps(out, indent=1))
        elif args.cmd == "requests":
            print(json.dumps(activation.list_requests(args.status), indent=1, default=str))
        else:
            print(json.dumps(activation.sweep(), indent=1))
    except activation.ActivationError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
