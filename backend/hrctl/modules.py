"""Part 19.1: which modules a company has (active / waiting for the activation code / off).

    .venv/Scripts/python.exe -m hrctl.modules status --tenant <slug>

Modules are switched on with an activation code from CTD Techs (hrctl.activation); the shared
module passcode of Part 18.4 is retired.
"""

import argparse
import json


def main(argv=None) -> int:
    from hrctl.demo_data import _run

    parser = argparse.ArgumentParser(prog="hrctl modules")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="each module: active / pending / off")
    s.add_argument("--tenant", required=True)
    args = parser.parse_args(argv)

    def fn(db, ctx):
        from app.platform import module_status

        return {"modules": {m["key"]: m["status"] for m in module_status.status(db, ctx)}}

    print(json.dumps(_run(args.tenant, fn), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
