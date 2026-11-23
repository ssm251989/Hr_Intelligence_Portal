# CTD licence runbook (Part 32)

CTD Techs approves every company's **first access** and every **module change** with a code signed by CTD's
**private key**. The app only holds the matching **public key** (it can check a code, never make one). A client who
edits the database, the code text or `.env` switches nothing on.

## The pieces

| Piece | Where | Who has it |
|---|---|---|
| Private key `ctd_private_key.pem` (Ed25519, encrypted with a passphrase) | the CTD PC: `%USERPROFILE%\.ctd_licence` (or `CTD_LICENCE_HOME`) | CTD only. Never on a server, never in the repo, never in a zip |
| Public key `ctd_public_key.pem` | `backend/app/platform/licence/` - committed and in every zip | everyone (it is public) |
| Signed CTD file `ctd_config.json` + `.sig` | in every zip (`build_zip.ps1 -CtdConfig`), or loaded later in Settings > Licence > Load CTD file | made by CTD; names the ONE approver (@ctdtechs.com) |
| The signing tool | `tools/ctd_licence` (not in the zip) | CTD PC only |
| Approvals log `approvals_log.csv` | next to the private key | CTD |

## Once, after Part 32 is merged

```
cd tools
python -m ctd_licence keygen                       # asks for a passphrase (12+ characters) - write it down offline
copy %USERPROFILE%\.ctd_licence\ctd_public_key.pem ..\backend\app\platform\licence\ctd_public_key.pem
git add backend/app/platform/licence/ctd_public_key.pem && git commit -m "CTD public key"
python -m ctd_licence config --approver <the CTD approver>@ctdtechs.com --support-email support@ctdtechs.com --support-phone "+91 ..." --out ctd_file
powershell -ExecutionPolicy Bypass -File installer\build_zip.ps1 -Version 1.1.0 -CtdConfig tools\ctd_file
```

The build stops if the package has no public key or no signed CTD file, or if any private key (or the signing tool,
or the approvals log) got into it.

Existing installations (this PC and early clients) keep working for **14 days** after the update with the banner
"Ask CTD Techs for your approval code". Approve them in that time (below).

## Every approval

1. The company sends its request (their HR mailbox, "Email CTD", or pasted from "Copy request"): a block starting
   `CTDREQ1.`
2. On the CTD PC:
   ```
   cd tools
   python -m ctd_licence approve "CTDREQ1...."               # or @request.txt
   python -m ctd_licence approve @request.txt --valid-until 2027-12-31   # a yearly licence
   python -m ctd_licence approve @request.txt --modules jobs,candidates  # approve fewer modules than asked
   ```
   It shows the company, admin and modules and asks **Approve? [y/N]**, then prints the code (`CTD1....`) and adds a
   line to `approvals_log.csv`.
3. Email the code back. The company pastes it on the waiting page / Settings > Licence / Choose what you want.

A code works only for that installation, that company and that request (its nonce), once. A module-change approval
lists the company's **complete** set of modules. `python -m ctd_licence inspect <code>` shows what a code contains
and whether CTD's signature is valid.

## Changing the approver

`python -m ctd_licence config --approver new@ctdtechs.com --out ctd_file` -> send `ctd_config.json` + `.sig` to the
client (they load it in Settings > Licence > Load CTD file) or deploy it (cloud). Use it in the next zip build too.

## Keep the private key safe

- Keep it on the CTD PC only, plus an **offline backup** (encrypted USB in a safe). Store the passphrase separately.
- Never copy it to a server, a shared drive, email or chat.

## If the private key is LOST

No new approvals can be made. Make a new key pair (`keygen --force`), commit the new public key, issue a new CTD
file, **build a new zip** and give it to every client (Upgrade keeps their data), then approve each installation
again with the new key. Codes signed by the old key stop counting once the app has the new public key, so plan the
roll-out (the 14-day grace covers it only for companies that existed before Part 32).

## If the private key LEAKED

Anyone with it can approve. Do the same as "lost" **now** (rotate: new key pair, new public key in a new zip, new CTD
file, re-approve every client). Tell clients to upgrade. Check `approvals_log.csv` against the companies you know.

## Honest limits (on-prem)

On-prem the client owns the PC and the files. The signature stops the easy ways (editing the database, `.env`, the
codes, the CTD file). Someone who changes the app's program files (e.g. replaces the public key and re-signs) can
still get around it - that is a licence breach, not something software on the client's own PC can fully prevent.
