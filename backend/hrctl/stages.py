"""Part 18.28: stages that say "interviewed / selected" without an interview record.

    .venv/Scripts/python.exe -m hrctl.stages check --tenant <slug>
    .venv/Scripts/python.exe -m hrctl.stages fix --tenant <slug>     (moves them back; nothing deleted)
"""

import argparse
import json


def main(argv=None) -> int:
    from hrctl.demo_data import _run

    parser = argparse.ArgumentParser(prog="hrctl stages")
    parser.add_argument("cmd", choices=("check", "fix"))
    parser.add_argument("--tenant", required=True)
    args = parser.parse_args(argv)

    def fn(db, ctx):
        from app.recruitment import stage_consistency

        rows = stage_consistency.fix(db, ctx, actor="hrctl stages fix") if args.cmd == "fix" else stage_consistency.check(db, ctx)
        return {"mode": args.cmd, "count": len(rows), "rows": rows}

    print(json.dumps(_run(args.tenant, fn), indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
