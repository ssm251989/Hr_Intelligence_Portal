"""Part 18.4: set the module unlock passcode for a company (run on the server).

    .venv/Scripts/python.exe -m hrctl.modules set-passcode --tenant <slug> [--module <key>]
    .venv/Scripts/python.exe -m hrctl.modules status --tenant <slug>

The passcode is asked for twice at a hidden prompt (never on the command line, so it is not
kept in the shell history) and stored only as a bcrypt hash. Setting it the first time locks
every module until an admin enters it in the app.
"""

import argparse
import getpass
import sys


def _set(slug: str, module: str) -> dict:
    from hrctl.demo_data import _run

    first = getpass.getpass("New module passcode: ")
    again = getpass.getpass("Type it again: ")
    if first != again:
        raise SystemExit("The two entries don't match. Nothing was changed.")

    def fn(db, ctx):
        from app.platform import module_lock

        try:
            module_lock.set_passcode(db, ctx, first, actor="hrctl (server)", key=module, require_current=False)
        except module_lock.LockError as exc:
            raise SystemExit(str(exc))
        st = module_lock.status(db, ctx)
        return {"passcode_set": True, "module": module, "locking_active": st["active"], "locked": sum(1 for m in st["modules"] if m["locked"])}

    return _run(slug, fn)


def _status(slug: str) -> dict:
    from hrctl.demo_data import _run

    def fn(db, ctx):
        from app.platform import module_lock

        st = module_lock.status(db, ctx)
        return {"active": st["active"], "mode": st["mode"], "passcode_set": st["passcode_set"],
                "locked": [m["module"] for m in st["modules"] if m["locked"]], "unlocked": [m["module"] for m in st["modules"] if not m["locked"]]}

    return _run(slug, fn)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hrctl modules")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("set-passcode", help="set (or reset) the module unlock passcode")
    p.add_argument("--tenant", required=True)
    p.add_argument("--module", default="__all__", help="per-module mode only; default: the one passcode for all modules")
    s = sub.add_parser("status", help="which modules are locked")
    s.add_argument("--tenant", required=True)
    args = parser.parse_args(argv)
    result = _set(args.tenant, args.module) if args.cmd == "set-passcode" else _status(args.tenant)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
