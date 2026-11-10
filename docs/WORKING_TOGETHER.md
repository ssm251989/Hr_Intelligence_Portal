# Working together on HR Automation

Two developers, one code base: `https://github.com/ssm251989/Hr_Intelligence_Portal`.

## The one folder

`C:\Users\Dell\Documents\hr-portal-work` is the only working folder. Each developer has their own
copy (a git clone) on their own PC; GitHub is where the two copies meet.

Kept on each PC only, never in git (see `.gitignore`):

- `backend/.env`: passwords and keys. Each developer has their own.
- `backend/uploads/`: résumés and other files the app stored.
- `backups/`: database backups.
- `Sample/` résumés, the `.docx` / `.pdf` business documents in the root, and `Claude outputs/`.

Real candidate data never goes into git. The repository is public.

## Branches

- `KG-Development` is the shared branch. It must always start and pass its tests. Nobody commits
  straight to it.
- Each piece of work gets its own branch from `KG-Development`, named
  `<who>/<what>`, e.g. `kishore/part-29-agents` or `ravi/leave-module`.
- A finished branch goes back through a **pull request** on GitHub. The other person reviews it, then it
  is merged.

## Daily routine (Git Bash, in hr-portal-work)

Start of the day, bring in the other person's merged work:

```
git checkout KG-Development
git pull
git checkout <your-branch>
git merge KG-Development
```

Start a new piece of work:

```
git checkout KG-Development
git pull
git checkout -b <who>/<what>
```

Save and share your work (small commits, several times a day):

```
git add -A
git status            # check nothing private is listed (.env, uploads, résumés)
git commit -m "part-30.1: <what changed>"
git push -u origin <who>/<what>
```

Then on GitHub: **Compare & pull request** into `KG-Development` and ask the other person to review.

## Rules that prevent most conflicts

1. **Say who owns what.** Write the part or module you are working on in the team chat before starting.
   Two people should not change the same files in the same week.
2. **Database changes (alembic).** Before creating a migration: pull `KG-Development` first. After
   merging: `alembic heads` must show ONE head. If it shows two, the person merging second creates a
   merge revision (`alembic merge heads -m "merge"`), then runs `alembic upgrade head`.
3. **Settings, menu and translations** (`bootstrap_definitions.py`, `modules.py`, `i18n/*.ts`) are shared
   files. Only add lines, do not reorder, and pull before editing them.
4. **Before every pull request:** backend `pytest -q` (no new failures) and frontend `npm run build`
   (i18n check and tsc must pass).
5. **Each developer has their own local database.** Never share a `.env` or point at the other
   person's database.
6. **Using Claude Code:** give each Part prompt (`docs/PARTxx_*.txt`) to one person only, and start it
   on a fresh branch.

## One-time setup for a new developer

1. The repo owner (ssm251989) adds them on GitHub: **Settings > Collaborators > Add people** (role: Write).
2. They clone and switch to the shared branch:
   ```
   git clone https://github.com/ssm251989/Hr_Intelligence_Portal.git hr-portal-work
   cd hr-portal-work
   git checkout KG-Development
   ```
3. They set up the database and their own `.env` with the install engine. It asks for their own
   passwords:
   ```
   cd backend
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python -m app.platform.install
   ```
4. Frontend: `cd frontend`, `npm ci`, `npm run dev`.

## Protect the shared branch (repo owner, once)

GitHub > Settings > Branches > Add rule for `KG-Development`:

- Require a pull request before merging, with 1 approval.
- Do not allow force pushes.
