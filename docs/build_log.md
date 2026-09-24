# HRMS Platform Build Log

Tracks progress against `docs/HRMS_COMPLETE_SPEC.txt`, part by part: commit hash, tests
passed, anything deferred and why, and any autonomous decision made under the standing
"pick the recommended option and continue" directive (2026-09-24).

## Standing directives (from user, 2026-09-24)

- Do not stop to ask questions. When a decision point comes up, take the option that
  would have been marked "(Recommended)", record the decision + reason here, and continue.
- Exceptions (still stop and ask): an action would delete data, overwrite main, push
  secrets, or cannot be undone.
- Work PART 1 -> PART 14 of the spec without waiting between parts. Commit + push after
  each part with message `part-N: <title>`, quoting that part's Checks output in the
  commit summary.

## Pre-Part-1: pending diff on main

Before branching, `main` had a complete but uncommitted change (not part of this spec
build - left over from the prior session): adds `interviewer_email` to
`negotiation_tokens` and `interviewer_name`/`interviewer_email` to `interviews`, so the
interviewer-first negotiation flow can attribute/email a finalized interview without
requiring the interviewer to have a registered `User` account. Matching Alembic migration
`a7c4f9e1b3d6` was present but untracked.

- **Decision:** commit it to `main` as its own commit, then branch `hrms-platform` from
  clean `main`, rather than folding it into Part 1's diff.
- **Why:** it's unrelated to the platform rebuild and already finished; keeping it as a
  separate commit keeps the new spec-driven history clean.
- **Secrets/PII check:** reviewed the diff. `interviewer_email` stores a business email
  address for an internal interviewer - the same class of data as the pre-existing
  `User.email` column, already stored in plain text. No password, token, PAN, Aadhaar,
  bank, or other sensitive-per-spec-section-H field is touched by this diff. No fail-safe
  change was needed.
- **Tests:** `test_interview_negotiation.py`, `test_interviews_dashboard.py`,
  `test_scheduling.py` - 86 passed. Full suite run before commit (see below).

## PART 1 (branch `hrms-platform`)

Step 0 (`docs/module_parity_checklist.md`) and Step 1 (`docs/hardcode_inventory.md`)
complete - see those files. Step 2, closing the 6 pending bugs listed in the spec:

- **2a - Tracker file lock.** Was genuinely unbuilt (confirmed via grep first, per the
  spec). Added `tracker._save_with_retry` (5 attempts, 0.5s backoff) and
  `tracker.TrackerFileLockedError`; every `workbook.save(path)` call site in
  `tracker.py` now goes through it. In `negotiation.py`, added
  `TrackerLockedNegotiationError` and guarded every `append_interview_log_row` call:
  the two call sites where an email had ALREADY been sent successfully before the
  tracker write failed (`_advance_interviewer_round`, `_start_candidate_round`)
  invalidate the just-created token (no orphan live token) and propagate the error;
  the two bookkeeping-only call sites (`_flag_for_manual_scheduling`,
  `_flag_send_failed`) swallow it into an audit-log entry, since the real outcome
  they record is already independently logged; `_finalize`'s (the interview is
  already committed/confirmed by that point) swallows it too, for the same reason.
  `attempt_auto_negotiate_interview_slots` keeps its "never raises" contract intact
  (catches `TrackerLockedNegotiationError` alongside `SmtpError` everywhere it already
  caught the latter). `retry_negotiation` recognizes the tracker-locked reason string
  and re-raises `TrackerLockedNegotiationError` specifically so `router.py`'s
  `retry_negotiation_endpoint` can map just that one to HTTP 409
  `{code: "TRACKER_LOCKED", message}`; `RetryNegotiationMenuItem.tsx` shows the exact
  snackbar text the spec asked for. Tests: 4 new lock-simulation tests in
  `test_tracker.py` (retry succeeds, retry exhausts, a real write path surfaces the
  error) + 1 new endpoint test in `test_interview_negotiation.py` for the 409 mapping.
- **2b - Interviewer pool comma parsing.** Added 9 parametrized cases to
  `test_tracker.py` for every variant the spec listed. All passed as-is except
  duplicate-name dedup, which `read_interviewer_pool` did not do at all -- fixed to
  dedup case/whitespace-insensitively, keeping the first occurrence's spelling and
  overall order. `";"` is deliberately NOT treated as a separator (the column header
  says comma-separated) -- confirmed via test, not changed.
- **2c - `test_candidates_top_skills_no_limit_param_returns_every_skill`.** Was
  relying on ambient rows in this shared dev DB (`assert len(body) > 5` after
  creating 15 candidates all sharing ONE skill). Rewrote to create 6 genuinely
  distinct skills itself and assert every one comes back, matching the pattern its
  own sibling test right below it already used correctly.
- **2d - `test_jobs_dashboard_stats_top_jobs_ranked_by_application_count`.** The
  `top_job_rows` query in `reports/router.py` had no secondary sort key, so jobs tied
  on `application_count` (routine for 0-application jobs) could come back in a
  different order from one query to the next. Added `JobRole.created_at, JobRole.id`
  as secondary/tertiary `ORDER BY` keys and a new test
  (`test_jobs_dashboard_stats_top_jobs_tiebreak_is_stable`) asserting the tie-break
  order directly.
- **2e - TS error in `CandidateDetailPage.tsx`.** Investigated: `npx tsc --noEmit`
  in `frontend/` currently exits 0 with empty output -- no error reproduces. Left
  unchanged; whatever this referred to was already fixed in an earlier session.
  Literal before/after are identical (clean).
- **2f - `Sample/Automation_Anywhere_Architect_Resume.docx`.** File no longer exists
  in the working tree or anywhere in git history -- nothing to decide or fix. (Two
  unrelated untracked sample files, `Sample/ASWATH_T_AA.pdf` and
  `Sample/Bhavani Shankar - AA.doc`, are present instead; left untouched per the
  spec's own "don't commit or delete Sample/ fixtures" instruction.)

Full backend suite green after each fix (see individual test runs); ran again at the
end of Step 2: all passing.

Step 3 (`backend/tests/test_no_hardcoded_tenant_values.py` + `hardcode_allowlist.txt`):
implemented the guard exactly to Step 3's own (narrower than the full Step-1 audit)
pattern list -- email addresses outside tests/fixtures, "gmail.com", "ctdtechs"/"CTD
Techs", absolute Windows/Unix paths, ".xlsx" literals, hex colours (scoped to
`backend/app` only -- see the test's own docstring for why: no `comms/` package exists
yet to scope it to more narrowly, and frontend's `theme/tokens.ts` palette is already a
generic, non-client design system, not something this guard should flag), and model IDs
(excluding `platform/ai/model_catalog.py`, which doesn't exist yet). Found **84 offending
lines across 15 distinct files** after one genuine allow-list exception (a UI placeholder
string). Marked `xfail(strict=True)` per the spec (would fail as XPASS, catching anyone
who "fixes" this test by weakening the patterns instead of removing real offenders).
Verified both that it reports XFAIL (not XPASS -- confirming real offenders are actually
being found) and that the allow-list mechanism actually suppresses the one entry in it.

Step 4 (frontend constants sweep): created `frontend/src/bootstrap/defaults.ts`
(`ORG_DISPLAY_NAME`, `ORG_LOGO_MARK`, `CAREERS_SITE_TITLE`), tagged `// TENANT-CONFIG`
per the spec, and pointed `AppLayout.tsx`'s logo mark/wordmark and `CareersLayout.tsx`'s
header/footer at it instead of the literal "CTD Techs" strings. Scoped to the actual
client-branding literals (the two "CTD Techs" occurrences) -- left the generic hiring
stage labels ("Screening", "Shortlisted", "On Hold", ...) alone: those are a Part 8
concern (`pipeline_stages`, decision E3), not client branding, and moving them into a
bootstrap/branding staging file would conflate two different target systems (Part 6
tenant branding vs. Part 8 configurable pipeline). `npx tsc --noEmit` clean; had to add
`hasErrorCode` to `RetryNegotiationMenuItem.test.tsx`'s `../api/client` mock (added as
part of 2a's frontend snackbar work) or its existing tests failed with an unhandled
rejection -- fixed, plus one new test for the TRACKER_LOCKED snackbar path. Full frontend
suite (`npm test`): 7 files / 27 tests passed.

Part 1 complete. Full backend suite (892 passed) + guard test (1 xfailed, as expected)
+ full frontend suite (27 passed) all green. Ready to commit "part-1: hardcode
inventory, tracker lock fix, guard test" and move to Part 2.
