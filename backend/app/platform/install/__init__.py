"""Part 27: one-step installation ("click Install").

The same engine is used by every way of installing HR Automation:
- the Windows installer (setup .exe) calls `python -m hrctl.setup --answers <file> --json`;
- a developer runs `python -m hrctl.setup` and answers the questions;
- the cloud sign-up (Part 28) calls `provision.run(...)` for a new company.

validate.py  checks every value the person types (passwords, names, ports) BEFORE anything is
             created -- no line breaks, no control characters, safe lengths, clear messages.
envfile.py   builds the database URLs (passwords URL-encoded, so @ # : / % are safe) and writes
             backend/.env atomically, one KEY=value per line, then reads it back to prove it.
provision.py runs the steps in order (roles + databases, .env, migrations, permissions, company,
             base data, first admin, modules), each step safe to run again.
"""
