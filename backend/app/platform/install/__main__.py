"""python -m app.platform.install -- install HR Automation in one step (Part 27; docs/INSTALLER.md).

Runs BEFORE backend/.env exists, so it imports nothing that needs the database settings.

    python -m app.platform.install                      # asks the questions, checks every answer, installs
    python -m app.platform.install --answers a.json     # no questions (the Windows installer / scripts)
          [--json]                                      # one JSON line per step, for an installer screen
          [--delete-answers]                            # remove the answers file once read (it holds passwords)
    python -m app.platform.install --check --answers a.json   # only check the answers, change nothing

Safe to run again: an interrupted or repeated install continues where it is. Passwords are never
printed or put on a command line. The admin password is kept only as a bcrypt hash; database
passwords live in backend/.env (readable only by the account that runs the app).
"""

import argparse
import getpass
import json
import sys
from pathlib import Path

QUESTIONS = (
    ("company_name", "Company name", False, None),
    ("company_slug", "Short name for the company (letters, digits, '-'; e.g. ctd-techs)", False, None),
    ("admin_name", "Your full name (the first administrator)", False, None),
    ("admin_email", "Your work email (you sign in with it)", False, None),
    ("admin_password", "Choose your sign-in password", True, "admin_password"),
    ("pg_host", "PostgreSQL server", False, "localhost"),
    ("pg_port", "PostgreSQL port", False, "5432"),
    ("pg_superuser_password", "PostgreSQL 'postgres' password (chosen when PostgreSQL was installed)", True, None),
    ("app_db_password", "Choose a password for the app's own database login (hr_app)", True, "app_db_password"),
)


def _ask(answers: dict) -> dict:
    from app.platform.install.validate import Answers, InvalidInput, check

    print("HR Automation setup. Press Enter to accept a value in [brackets].\n")
    while True:
        for key, label, secret, default in QUESTIONS:
            if key in answers and answers[key] not in (None, ""):
                continue
            while True:
                prompt = f"{label}{f' [{default}]' if default and not secret else ''}: "
                value = getpass.getpass(prompt) if secret else input(prompt)
                if not value and default and not secret:
                    value = default
                if secret and key != "pg_superuser_password":
                    if getpass.getpass("Type it again: ") != value:
                        print("  The two passwords are different. Try again.")
                        continue
                answers[key] = int(value) if key == "pg_port" and value.isdigit() else value
                break
        try:
            check(Answers.from_dict(answers))
            return answers
        except InvalidInput as exc:
            print("\nPlease fix:")
            for key, problem in exc.problems.items():
                print(f"  - {problem}")
                answers.pop(key, None)
            print()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="hrctl setup")
    parser.add_argument("--answers", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--delete-answers", action="store_true")
    parser.add_argument("--env", type=Path, help="path of backend/.env (default: next to this app)")
    args = parser.parse_args(argv)

    from app.platform.install import provision
    from app.platform.install.validate import Answers, InvalidInput, check

    answers: dict = {}
    if args.answers:
        answers = json.loads(args.answers.read_text(encoding="utf-8-sig"))
        if args.delete_answers:
            args.answers.unlink(missing_ok=True)
    elif not args.check:
        answers = _ask({})

    def emit(obj):
        print(json.dumps(obj) if args.json else obj.get("text", ""), flush=True)

    try:
        a = Answers.from_dict(answers)
        if args.check:
            check(a)
            emit({"event": "ok", "text": "All answers are fine."})
            return 0
        labels = {"postgres": "Checking PostgreSQL", "databases": "Creating the app login and databases", "env": "Writing settings (.env)",
                  "migrate": "Creating tables", "grants": "Giving the app access", "company": "Creating your company",
                  "base_data": "Adding base data", "admin": "Creating your admin account", "modules": "Modules"}
        provision.run(a, env_path=args.env, say=lambda step, state, r: emit(
            {"event": state, "step": step, "text": f"{labels[step]}..." if state == "start" else f"  done {('- ' + json.dumps(r)) if step in ('modules', 'admin') else ''}",
             "result": r if state == "done" else None}))
        emit({"event": "finished", "text": f"\nHR Automation is installed. Sign in at {a.frontend_url} with {a.admin_email}."})
        return 0
    except InvalidInput as exc:
        emit({"event": "invalid", "problems": exc.problems, "text": "Please fix:\n" + "\n".join(f"  - {p}" for p in exc.problems.values())})
        return 2
    except provision.StepFailed as exc:
        emit({"event": "failed", "step": exc.step, "message": exc.message, "detail": exc.detail,
              "text": f"Setup stopped at '{exc.step}': {exc.message}\nFix it and run setup again; finished steps are not repeated."})
        return 1



if __name__ == "__main__":
    sys.exit(main())
