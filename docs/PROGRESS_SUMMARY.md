# Progress Summary — Since the Candidates Module

Covers the AI Screening module (Resume Matcher, Candidate Ranking), HR Shortlisting, Interview Scheduling + Feedback, Salary Validation & Approval, BGV Management, and Offer & Onboarding. Written as a pause point before starting Reports & Status.

---

## AI Screening Module — Complete

**Location:** `app/screening/router.py`, `app/ai_services/resume_matcher.py`, `app/ai_services/candidate_ranker.py`

| Piece | Model | Status |
|---|---|---|
| Resume Matcher | Claude Haiku 4.5 | Fully working |
| Candidate Ranking | Claude Sonnet 5 | Fully working |

**Endpoints:**
- `POST /applications/{id}/screen` — runs Resume Matcher. Requires the job's `jd_text` and the candidate's `parsed_fields` to already exist (400 otherwise). Sets `match_score`, `skill_match_pct`, `missing_skills`; advances `status` → `screened`.
- `POST /applications/{id}/rank` — runs Candidate Ranking. Requires the application to already be `screened` (400 otherwise). Pulls any existing interview feedback. **Overwrites `match_score`** with the refined composite score — there's no separate column for the two, a deliberate schema limitation flagged at the time. Writes a combined rationale (rank rationale + strengths + concerns + recommendation) into `ranking_rationale`. Does **not** change `status` — final accept/reject stays human, per the architecture doc's advisory-only principle.

Both endpoints log raw AI output to `audit_log` (`ai_resume_matcher_scored`, `ai_candidate_ranking_scored`) before applying it.

**Test coverage:** `tests/test_screening.py`, 6 tests — screen success, screen without JD (400), screen without parsed resume (400), screen not-found (404), rank success, rank-before-screening (400). All AI calls mocked.

**Live-verified:** Ran the full real pipeline once (job → JD → resume upload/parse → application → screen → rank) against the actual Claude API. Output was coherent and evidence-grounded — e.g. the ranker correctly flagged missing JD-required skills even with a decent match score. Test data cleaned from the dev DB afterward.

---

## HR Shortlisting Module — Complete

**Location:** `app/shortlisting/router.py`

**Endpoints:**
- `GET /jobs/{job_id}/shortlist` — applications for a job with `status == "screened"`, sorted best-match-first.
- `POST /applications/{id}/shortlist-decision` — `{decision: "select"|"reject", notes?, decided_by?}`. Requires `screened` status (400 otherwise). Transitions to `hr_selected`/`hr_rejected`. Audit actor defaults to the string `"hr"` if `decided_by` is omitted, since there's no real auth system yet to attribute a real user.

**Bug found and fixed during this module:** `Application.match_score` is a `Numeric` column, so SQLAlchemy returns a `Decimal`, which isn't JSON-serializable into the `audit_log.details` JSONB column. This was caught by the transactional Postgres test fixture (not by mocks) and fixed with an explicit `float()` cast before logging.

**Test coverage:** `tests/test_shortlisting.py`, 6 tests — queue ordering/filtering, select, reject, actor-defaulting, precondition (400), not-found (404). No AI involved, so no live smoke test was needed — the real-Postgres-backed pytest run was the verification.

---

## Interview Scheduling + Feedback Module — Complete

**Location:** `app/scheduling/router.py`, `app/ai_services/interview_question_generator.py`

**Endpoints:**
- `POST /applications/{id}/interviews` — schedule a round. Requires `status` to be `hr_selected` or already `interview_scheduled` (so multiple rounds are supported). Validates `interviewer_id` against `users` if given. Advances status to `interview_scheduled`.
- `GET /applications/{id}/interviews` / `GET /interviews/{id}` — read access.
- `PATCH /interviews/{id}/feedback` — ratings/comments can be recorded any time; recording a `decision` requires `status == "interview_scheduled"` (400 otherwise) and transitions to `interview_selected`/`interview_rejected`.
- `POST /applications/{id}/interview-questions` — Claude Haiku 4.5, generates prep questions tailored to `missing_skills`. Not persisted anywhere (no schema column for it) — returned directly, logged to `audit_log` as `ai_interview_questions_generated`.

**Design simplification flagged at the time:** a decision on *any* single interview round immediately flips the application's status — there's no "final round" or multi-interviewer consensus concept, since the schema doesn't model that.

**Test coverage:** `tests/test_scheduling.py`, 15 tests — scheduling success/preconditions/404s, multi-round scheduling, listing order, feedback with/without decision, decision-precondition enforcement, question generation success/precondition/404. AI call mocked in tests.

**Live-verified:** Ran `interview-questions` against the real Claude API once (job → JD → candidate → application, no screening run first). Got good technical/behavioral questions; `questions_to_probe_gaps` came back empty, correctly, since `missing_skills` was null for that application. Test data cleaned afterward.

---

## Salary Validation & Approval Module — Complete

**Location:** `app/salary/router.py`

**Endpoints:**
- `POST /applications/{id}/validate-salary` — requires `hr_selected` or `interview_selected` (400 otherwise) and a set `expected_salary` and job `salary_band_min`/`salary_band_max` (400 otherwise). Deterministic comparison, no AI involved: within the job's band → `salary_ok`, above it → `salary_above_band`.
- `POST /applications/{id}/approve-salary` — `{decision: "approve"|"reject", approved_salary?, notes?, approved_by?}`. Requires `salary_above_band` (400 otherwise). On approval, sets `applications.approved_salary` (falls back to `expected_salary` if no override given) and status → `salary_approved`; on rejection, status → `salary_rejected`. Audit actor defaults to `"hr"` if `approved_by` is omitted, same convention as HR shortlisting.
- `GET /applications/{id}/salary-status` — read-only view of expected/approved salary against the job's band.

**Test coverage:** `tests/test_salary.py`, 15 tests — validation within/above band, precondition checks (wrong status, missing expected salary, missing salary band), approval with/without override amount, rejection, actor-defaulting, not-found cases.

---

## BGV Management Module — Complete

**Location:** `app/bgv/router.py`, `app/bgv/document_extraction.py`, `app/bgv/storage.py`, `app/ai_services/document_validator.py`

**Endpoints:**
- `POST /applications/{id}/bgv/request` — requires `salary_approved` (400 otherwise), status → `bgv_requested`.
- `POST /applications/{id}/bgv/documents` — multipart upload (`doc_type` + file). Requires `bgv_requested`/`bgv_pending` (400 otherwise). Validates doc type against the fixed set (`aadhaar`/`pan`/`degree`/`experience`) and file extension (`pdf`/`docx`/`jpg`/`jpeg`/`png`), extracts text to fail fast on unreadable files, then stores the file and DB row. First document uploaded flips status from `bgv_requested` → `bgv_pending`.
- `GET /applications/{id}/bgv/documents` — list, oldest first.
- `POST /applications/{id}/bgv/documents/{doc_id}/validate` — Claude Haiku 4.5 (`document_validator`), re-reads the stored file, sets `validation_status` (`pending`/`valid`/`invalid`/`needs_review`) and `validator_output` verbatim from the AI result. `needs_review` is deliberately never auto-collapsed to `invalid` — a human decides at `/bgv/clear`.
- `POST /applications/{id}/bgv/clear` — `{decision: "clear"|"reject", notes?, cleared_by?}`. Requires `bgv_requested`/`bgv_pending` (400 otherwise). Clearing requires at least one uploaded document and all documents `valid` (400 with the list of non-valid docs otherwise); status → `bgv_cleared`. Rejection → `bgv_rejected`. Same `"hr"`-default-actor convention.

**Test coverage:** `tests/test_bgv.py`, 26 tests (largest suite) — request preconditions, upload validation (bad doc type, bad extension, unreadable file, wrong status), status transition on first upload, listing order, AI validation success/not-found, clear success/blocked-by-invalid-docs/no-documents/wrong-status, reject, actor-defaulting. AI and file I/O mocked.

---

## Offer & Onboarding Module — Complete

**Location:** `app/offers/router.py`, `app/ai_services/offer_letter_generator.py`

**Endpoints:**
- `POST /applications/{id}/offer/generate` — requires `bgv_cleared` (400 otherwise), an `approved_salary` or `expected_salary` (400 otherwise), and a candidate `full_name` (400 otherwise). Reporting manager name resolves from the payload, else the job's `hiring_manager_id` user, else `"Not specified"`. Calls Claude Haiku 4.5 to draft `offer_letter_text`, creates/updates the `Offer` row, status → `offer_sent`. Logged as `ai_offer_letter_generated`.
- `POST /applications/{id}/offer/mark-signed` — records `signed = true` and an optional `docusign_envelope_id` pasted in manually (real DocuSign integration explicitly out of scope for the MVP). Status → `onboarding_started`, `offers.onboarding_status` → `in_progress`.
- `POST /applications/{id}/offer/complete-onboarding` — requires `onboarding_started` (400 otherwise). Status → `onboarding_completed`, `offers.onboarding_status` → `completed`.
- `GET /applications/{id}/offer` — read.

**Test coverage:** `tests/test_offers.py`, 20 tests — generate success/preconditions (wrong status, no salary, no candidate name)/reporting-manager resolution, mark-signed with/without envelope ID, complete-onboarding success/precondition, not-found cases across all four endpoints. AI call mocked.

**Live-verified:** Ran `offer/generate` against the real Claude API once end-to-end (job → candidate → application through bgv_cleared → generate). Output was a coherent, correctly-populated offer letter. Smoke-test rows were left in `job_roles`/`candidates`/`applications`/`offers`/`audit_log` after this run; cleaned up in a later pass (see Overall section below) rather than immediately.

---

## Overall

- **98 tests total**, all passing (`pytest -q` → `98 passed`). Per file: `test_applications.py` (4), `test_candidates.py` (6), `test_screening.py` (6), `test_shortlisting.py` (6), `test_scheduling.py` (15), `test_salary.py` (15), `test_bgv.py` (26), `test_offers.py` (20).
- Since this summary was first written, the AI Screening module's ranking flow was also fixed: `POST /applications/{id}/rank` now writes to a new `ranking_score` column instead of overwriting `match_score` (see `alembic/versions/8cb496eb423e_add_ranking_score_to_applications.py`). `match_score` is set by `screen` and left untouched by `rank`. The `float()`-before-`audit_log` cast was applied to `ranking_score` too.
- A second migration, `alembic/versions/7b0e8b9108aa_add_approved_salary_to_applications.py`, added `applications.approved_salary` for the Salary Validation module. DB is at this head revision.
- Every module's dev-DB smoke-test data has been cleaned up — `job_roles`, `candidates`, `applications`, `offers`, `audit_log`, and `backend/uploads/` are all empty as of this pause point (the Offer module's leftover smoke-test rows, noted above, were cleared in this same pass).
- Everything from screening through offers stays consistent with established conventions: structured-output AI calls (no manual JSON retry needed, schema enforcement replaces it), audit-log-before-use, advisory-only AI (status changes are either deterministic backend logic or explicit HR/interview/salary/BGV decisions, never automatic AI decisions), `"hr"`-default audit actor where there's no real auth system yet.
- Initial git commit made at this pause point, capturing jobs through offers in one snapshot; going forward each completed module gets its own commit.

**Not started yet:** Reports & Status, auth/users endpoints.
