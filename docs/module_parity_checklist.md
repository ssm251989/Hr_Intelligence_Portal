# Existing-Module Parity Checklist

Part 1, Step 0 of `docs/HRMS_COMPLETE_SPEC.txt`. Confirms the 13 modules on
`AppLayout.tsx` MODULES / `App.tsx` routes / `backend/app/main.py` routers as of
2026-09-24 (branch `hrms-platform`, base commit `bc2f46f`), and where each is rebuilt
in the new spec. **This checklist must be re-verified at the end of Parts 4, 8 and 10;
none of the 13 may be dropped.**

| # | Module | Backend routers/services | Frontend pages | Tests | Target PART | Status |
|---|--------|---------------------------|-----------------|-------|--------------|--------|
| 1 | Overview | `reports/stats.py` (overview section), `reports/router.py` | `OverviewPage.tsx` | `test_reports.py` | PART 12 (role dashboards / widgets) | refactored |
| 2 | Jobs | `jobs/router.py`, `jobs/service.py`; `ai_services/jd_generator.py`; `integrations/linkedin.py` (posting links) | `JobsPage.tsx` | `test_jobs.py`, `test_jobs_service.py`, `test_linkedin.py` | PART 8 (Requisitions & Jobs, JD library, job boards via connections) | refactored |
| 3 | Candidates | `candidates/router.py`, `applications_router.py`, `pipeline_actions.py`, `hold.py`, `photo_extraction.py`, `gender_inference.py`, `resume_extraction.py`, `storage.py`; `local_import/` (`router.py`, `service.py`, `scheduler.py`, `job_folders.py`, `storage.py`); `ai_services/resume_parser.py` | `CandidatesDashboardPage.tsx`, `CandidatesListPage.tsx`, `CandidatesImportPage.tsx`, `CandidateDetailPage.tsx` | `test_candidates.py`, `test_applications.py`, `test_local_import.py`, `test_photo_extraction.py`, `test_gender_inference.py`, `test_experience_migration.py`, `test_skills_migration.py`, `test_remarks.py` | PART 8 (candidate intake, career-site apply, talent pool) + PART 7 (import wizard reused) | refactored |
| 4 | Screening | `screening/router.py`, `service.py`, `suitability.py`, `settings_router` (screening settings); `ai_services/resume_matcher.py`, `candidate_ranker.py` | `ScreeningListPage.tsx`, `ScreeningDashboardPage.tsx` | `test_screening.py`, `test_screening_service.py`, `test_screening_settings.py`, `test_screening_dashboard.py`, `test_suitability_service.py`, `test_stemming.py` | PART 8 (configurable weights/formula, bias guardrails, prompt registry) | refactored |
| 5 | Shortlisting | `shortlisting/router.py`, `service.py`; `ai_services/shortlist_feedback_generator.py` | `ShortlistingListPage.tsx`, `ShortlistingDashboardPage.tsx` | `test_shortlisting.py`, `test_shortlisting_dashboard.py` | PART 8 (pipeline stage `category=screening/interview`, auto-actions) | refactored |
| 6 | Interviews | `scheduling/router.py`; `interview_scheduling/` (`negotiation.py`, `negotiation_router.py`, `confirmation.py`, `confirm_router.py`, `router.py`, `service.py`, `storage.py`, `tracker.py`); `ai_services/interview_question_generator.py` | `InterviewListPage.tsx`, `InterviewsDashboardPage.tsx` | `test_interview_negotiation.py`, `test_interview_confirmation.py`, `test_interview_scheduling.py`, `test_interviews_dashboard.py`, `test_scheduling.py`, `test_ics.py`, `test_tracker.py`, `test_google_calendar.py` | PART 8 section 6 (interviewer_availability replaces Excel tracker; negotiation mechanics from settings) | replaced (tracker as system of record) / refactored (negotiation mechanics) |
| 7 | HR Inbox | `hr_inbox/router.py`, `service.py`; `integrations/imap_poll.py` | `HrInboxListPage.tsx` | `test_hr_inbox_list.py`, `test_imap_poll.py` | PART 4 (inbound routing, `email.inbound.*` purposes) | refactored |
| 8 | Salary | `salary/router.py` | `SalaryPage.tsx` | `test_salary.py` | PART 8 section 7 / decision H1 (expected salary vs band - a hiring step, kept, NOT payroll) | refactored |
| 9 | BGV | `bgv/router.py`, `document_extraction.py`, `storage.py`; `ai_services/document_validator.py` | `BgvPage.tsx` | `test_bgv.py` | PART 9 section 2 (BGV cases, vendor connections, HITL decision) | refactored |
| 10 | Offers | `offers/router.py`; `ai_services/offer_letter_generator.py`; `integrations/docusign.py` | `OffersPage.tsx` | `test_offers.py`, `test_docusign.py` | PART 8 section 7 (offer templates, CTC builder, e-sign via connection) | refactored |
| 11 | Reports | `reports/router.py`, `stats.py` | `ReportsPage.tsx` | `test_reports.py` | PART 12 (semantic layer + report builder; keep recharts/Leaflet as widgets) | refactored |
| 12 | Settings | `integrations/router.py`, `hr_email.py`, `google_calendar.py`; HR mailbox cards; tracker settings; screening thresholds; `users/router.py`; `auth/router.py`, `dependencies.py` | `SettingsPage.tsx`, `LoginPage.tsx`, `RegisterPage.tsx` | `test_integrations.py`, `test_hr_email.py`, `test_google_calendar.py`, `test_users.py`, `test_auth.py` | PART 2 (Settings Registry) + PART 3 (Connections) + PART 5 (IAM/2FA/RBAC) | refactored |
| 13 | Careers portal | `public/router.py` | `careers/CareersListPage.tsx`, `CareersJobDetailPage.tsx`, `CareersApplyPage.tsx`, `CareersLayout.tsx`, `CareersThankYouPage.tsx` | `test_public.py` | PART 8 section 3 (Career Site & Candidate Portal) | refactored |

**Cross-cutting today** (not one of the 13, but relied on by all of them): `audit/service.py`
-> PART 5 platform `audit/` (append-only, before/after diff); `core/config.py`,
`crypto.py`, `security.py` -> PART 2 (Settings Registry / SecretStore) and PART 13
(security baseline); `models/` -> split across every module's own `models.py` per the
Part E package layout, plus PART 7's `employees`/`legal_entities`/etc.

**Verification method:** every backend package under `backend/app/` and every frontend
page under `frontend/src/pages/` + `frontend/src/careers/` was enumerated directly
(`find`, `ls`) against `backend/app/main.py`'s `include_router` calls, rather than taken
from the spec's own summary - the spec's Step-0 list matched exactly; nothing extra was
found and nothing listed there was missing from the current tree.

**Re-verification checkpoints:** re-run this same enumeration at the end of Part 4 (after
comms migration - Jobs/Screening/Shortlisting/Interviews/Offers must still send mail),
Part 8 (the actual recruitment refactor - all 13 rows should flip to a live E2E check
against tenant #1), and Part 10 (once Core HR/Performance exist alongside recruitment, to
confirm none of the 13 regressed while new modules were added).
