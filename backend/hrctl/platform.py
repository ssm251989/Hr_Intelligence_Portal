"""Part 19.2c: the PLATFORM system mailbox and CTD Techs-only platform settings.

    .venv/Scripts/python.exe -m hrctl.platform mailbox show
    .venv/Scripts/python.exe -m hrctl.platform mailbox set --host smtp.example.com --port 587 --user me@ctdtechs.com \
        --from-address hrms@ctdtechs.com [--from-name "CTD Techs HRMS"] [--no-starttls]      (password is prompted)
    .venv/Scripts/python.exe -m hrctl.platform mailbox test --to kg@ctdtechs.com
    .venv/Scripts/python.exe -m hrctl.platform settings show
    .venv/Scripts/python.exe -m hrctl.platform settings set activation.escalation_minutes 2

The password goes only to the control-plane SecretStore (never on the command line, never in git).
"""

import argparse
import getpass
import json
import sys


def main(argv=None) -> int:
    import hrctl  # noqa: F401
    from app.platform import platform_mail

    parser = argparse.ArgumentParser(prog="hrctl platform")
    sub = parser.add_subparsers(dest="cmd", required=True)
    mb = sub.add_parser("mailbox")
    msub = mb.add_subparsers(dest="action", required=True)
    msub.add_parser("show")
    ms = msub.add_parser("set")
    ms.add_argument("--host", required=True)
    ms.add_argument("--port", type=int, default=587)
    ms.add_argument("--user", default="")
    ms.add_argument("--from-address", required=True)
    ms.add_argument("--from-name", default="CTD Techs HRMS")
    ms.add_argument("--no-starttls", action="store_true")
    ms.add_argument("--keep-password", action="store_true", help="don't change the stored password")
    mt = msub.add_parser("test")
    mt.add_argument("--to", required=True)
    st = sub.add_parser("settings")
    ssub = st.add_subparsers(dest="action", required=True)
    ssub.add_parser("show")
    sset = ssub.add_parser("set")
    sset.add_argument("key")
    sset.add_argument("value")
    args = parser.parse_args(argv)

    actor = "hrctl (server)"
    try:
        if args.cmd == "mailbox" and args.action == "show":
            print(json.dumps(platform_mail.health(), indent=1, default=str))
        elif args.cmd == "mailbox" and args.action == "set":
            password = None if args.keep_password else getpass.getpass("Mailbox password (app password): ")
            print(json.dumps(platform_mail.set_mailbox(host=args.host, port=args.port, user=args.user, starttls=not args.no_starttls,
                                                       from_name=args.from_name, from_address=args.from_address, password=password, actor=actor), indent=1))
        elif args.cmd == "mailbox":
            r = platform_mail.test(args.to, actor)
            print(json.dumps(r, indent=1))
            return 0 if r["ok"] else 1
        elif args.action == "show":
            print(json.dumps(platform_mail.all_settings(), indent=1))
        else:
            value = json.loads(args.value) if args.value.strip()[:1] in "0123456789tf[{\"-" else args.value
            platform_mail.set_setting(args.key, value, actor)
            print(json.dumps(platform_mail.all_settings(), indent=1))
    except (platform_mail.MailError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
