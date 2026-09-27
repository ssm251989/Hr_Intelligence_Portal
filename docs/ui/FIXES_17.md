# Part 17 fixes -- proof log

Each item: what was wrong, what changed, how it was verified, screenshot.

How API proofs were run: `backend/scripts/probe.py` calls the endpoint in-process through the
real app (routing, validation, tenant middleware, permission checks) using FastAPI's
TestClient, with the signed-in user supplied by overriding `get_current_user` with an
existing user of the given flat role. No password or token is created or read. Tenant:
`ctd-techs`.

Signed-in screenshots need a real login (none was available in this session). They are
marked **pending login proof**. To take them: `cd frontend; npm i --no-save playwright;
npx playwright install chromium`, set `SHOT_EMAIL` / `SHOT_PASSWORD`, run
`node scripts/take_screenshots.mjs` (optionally `SHOT_ONLY=home,analytics`).

---

## 17.1 Raw text keys on screen

**Wrong:**
- The 15.6 pages called about 750 text keys that had no English text at all, and about 800 more lacked Hindi or Tamil.
- The keys on the Approvals, People and Directory pages, among others, showed raw (e.g. "approvalsPage.title").
- A key missing from English too was shown as-is.

**Changed:**
- New bundles `i18n/pages/{people,performance,insights,shell}.ts` and completed Hindi/Tamil in `agency.ts`. Every block has full en/hi/ta coverage.
- Dynamic keys such as `people.status.${s}` were expanded into their real values.
- Fallback (`i18n/index.tsx`): current language, then English, then readable words ("people.employees.title" becomes "Title", with a dev-console warning). A raw key never reaches the screen.
- `npm run i18n:check` (`frontend/scripts/i18n-check.mjs`) scans every `t()`/`tr()` call and `labelKey`/`label_key` literal against en/hi/ta. A dynamic key passes when its fixed prefix exists. `npm run build` now runs it first and stops on any gap.

**Verified:**
```
first run:  en 752 / hi 803 / ta 803 missing -> i18n:check FAILED -- 2358 missing
now:        npm run build -> "i18n:check OK -- 2837 keys, 0 missing", vite built OK
approvalsPage.title      en "My approvals" | hi "मेरी मंज़ूरियाँ" | ta "எனது ஒப்புதல்கள்"
people.employees.title   en "Employees"    | hi "कर्मचारी"      | ta "பணியாளர்கள்"
people.directory.title   en "Directory"    | hi "डायरेक्टरी"     | ta "அடைவு"
(+ the three *.purpose keys, all present in en/hi/ta)
```

**Screenshot:** `approvals.png`, `employees.png`, `directory.png` -- **pending login proof**.

---

## 17.2 Home -- "Where candidates go" funnel

**Wrong:** a Sankey diagram, hard to read, with no period or job filter and no way to open the candidates behind a number.

**Changed:**
- New `GET /api/v1/home/funnel?period=7d|30d|90d|year&job_id=&locale=`. Six stages: Applied, Screened, Shortlisted, Interviewed, Offered, Joined.
- For each stage it returns:
  - the count that reached it;
  - the % of the previous stage;
  - between stages, how many did not reach the next stage, split into "not selected" and "still waiting".
- Stage names come from the company's default pipeline when it has renamed the stage. The seeded default names are just the status code in words, so they fall back to plain wording.
- Home widget (`components/home/HiringFunnel.tsx`):
  - horizontal bars with period buttons and a job filter;
  - clicking a bar opens `/candidates/list?status=<that stage's statuses>&applied_after=<period start>[&job=]`.
- The candidate list now reads `status`, `job` and `applied_after` from the URL. The API filter accepts a comma-separated `status`.
- The Sankey stays only as the "Flow view" toggle on Analytics.

**Verified (API):**
```
GET /api/v1/home/funnel?period=year -> 200   (total 3, since 2026-01-01)
applied     | 3 | start
screened    | 3 | 100% | -1 did not reach Shortlisted (1 not selected, 0 waiting)
shortlisted | 2 |  67% | -1 (0 not selected, 1 waiting)
interviewed | 1 |  50% | -1 (0 not selected, 1 waiting)
offered     | 0 |   0%
joined      | 0 |   0%
GET /api/v1/home/funnel?period=bad -> 400 "period must be one of 7d, 30d, 90d, year"
GET /candidates/applications?status=screened,hr_selected -> 200 (multi-status filter)
```

**Found and fixed during proof:**
- A stage after an empty stage showed "start"; it now shows 0%.
- Raw default stage names ("Hr Selected") are no longer shown.

**Screenshot:** `home.png`, `analytics.png` -- **pending login proof**.

---

## 17.3 Maps

**Wrong:**
- Three separate map implementations, each with its own small hard-coded city table (about 55 cities).
- The Home map never re-measured itself inside its resizable box, which gave grey or shifted tiles and misplaced markers.
- There was no geocoding and no bounds check. A place that wasn't in a table silently became a chip, and nobody could fix it.

**Changed:**
- `app/platform/geo/`:
  - `india_cities.py`: 304 cities plus aliases (Bangalore, Gurgaon, Bombay…) and India's bounds.
  - `service.py`: resolves a place in this order: manual fix, then the office's own coordinates, then the `geo_cache` table (new, migration `c7e2a9d4f1b8`), then the offline table (whole text, then its parts, then any known city word, e.g. "Plot 12, Madhapur, Hyderabad 500081" gives Hyderabad), then the geocoding connection.
- New connector provider `nominatim` and purpose `geo.geocoding`. The public OpenStreetMap Nominatim server is the default; a company can route its own server.
  - Online lookups run in a background task, 1 request per second (the server's policy), and every answer is cached, including misses (retried after 7 days). A page never waits on the network.
- Settings: `geo.tile_url` (OpenStreetMap by default), `geo.tile_attribution`, `geo.online_lookup`, `geo.countries` (["IN"]). Points outside the allowed countries are rejected.
- API: `GET /api/v1/geo/config`, `GET /api/v1/geo/places?kind=offices|jobs` (placed points plus a not-found list), `PUT /api/v1/geo/fix` (city name or lat/lng, audited; offices also get their record updated).
- One shared `components/maps/PlacesMap.tsx`, used by Home "People by office", the Jobs page panel and the Analytics jobs and offices maps:
  - real Leaflet map, tiles from the setting, zoom (scroll wheel) and pan;
  - marker clusters that add up their counts, auto-fit, bubble size = count;
  - popup with place, count and an "Open list" button;
  - a "Location not found - fix it" list with a Fix dialog.
- The Analytics heat map also uses the tile setting. The old `OfficeMap.tsx` and `JobsLocationMap.tsx` are removed.

**Verified (API):**
```
GET /api/v1/geo/config -> 200  tile_url https://tile.openstreetmap.org/{z}/{x}/{y}.png, countries ["IN"], bounds [[6.5,68],[37.2,97.5]]
GET /api/v1/geo/places?kind=offices -> 200
    Demo - Bengaluru office  3 people  12.972, 77.595 (record)
    Demo - Chennai office    3 people  13.083, 80.271 (record)
GET /api/v1/geo/places?kind=jobs -> 200   Chennai  2 open jobs  13.083, 80.271 (offline)
offline lookups:
    'Hyderabad'                           -> 17.385, 78.4867  Hyderabad, Telangana
    'Bangalore - Whitefield'              -> 12.9716, 77.5946 Bengaluru, Karnataka
    'Chennai, Tamil Nadu'                 -> 13.0827, 80.2707
    'Pune (Hinjewadi)'                    -> 18.5204, 73.8567
    'Plot 12, Madhapur, Hyderabad 500081' -> Hyderabad
    'Gurgaon' -> Gurugram;  'Remote' -> not found;  London inside India? False
live Nominatim: 'Hinjewadi, Pune' -> 18.592, 73.758 (IN)
PUT /api/v1/geo/fix {"kind":"jobs","text":"Hitech City","city":"Hyderabad"} -> 200 (source manual)
PUT /api/v1/geo/fix ... lat 51.5, lng -0.12 -> 400 "That point is outside the countries your company works in."
PUT /api/v1/geo/fix ... city "Atlantis" -> 400 "We don't know that city yet…"
```
(The "Hitech City -> Hyderabad" manual entry is left in `geo_cache` for ctd-techs, where it is correct.)

**Screenshot:**
- `fix17-3-map-cities.png`: Hyderabad, Bengaluru, Chennai and Pune plotted from the geo service's coordinates on OpenStreetMap tiles. Each dot sits on its city.
- In-app maps (`home.png`, `jobs.png`, `analytics.png`): **pending login proof**.

---

## 17.9 Employees vs People directory

**Wrong:**
- Two separate pages (`/employees` table, `/directory` cards) with overlapping content and two menu entries.
- Both needed `core_hr.employee.view`, so ordinary staff couldn't find colleagues.

**Changed:**
- One **People** section (`/people`, `pages/people/PeoplePage.tsx`) with two views:
  - **Directory** (cards: photo/initials, name, role, team, office, work email, skills), which everyone in the company can see;
  - **HR view** (`?view=hr`: the table with HR-only columns, status tabs, filters, saved views, export), only with `core_hr.employee.view`.
- API: `GET /api/v1/ui/people/employees?view=directory` and `/filters?view=directory` work for any staff login. They return only current staff and only the directory fields: no personal email or phone, grade, code, joining date or worker type. `view=hr` still needs the permission.
- `/employees` redirects to `/people?view=hr` and `/directory` to `/people`, both keeping their filters, so the map's `?location=` links still work.
- Profiles open from both views (`/employees/:id`, and a new `/people/:id` alias). Directory cards link to the profile only for people who may open it.
- One "People" menu entry instead of two. Titles: "People", with the page line changing per view.

**Verified (API):**
```
GET /api/v1/ui/people/employees?view=directory  (recruiter, no HR access) -> 200
    6 rows, only active/on_notice; keys: department, department_id, designation, first_name, id, last_name,
    location, location_id, manager_id, manager_name, name, photo_url, skills, status, work_email, work_mode
GET /api/v1/ui/people/employees?view=hr (recruiter) -> 403 "Missing permission: core_hr.employee.view"
GET /api/v1/ui/people/employees (admin) -> 200, 11 rows incl. personal_email, personal_phone, grade, joined_on, employee_code
GET /api/v1/ui/people/filters?view=directory (recruiter) -> 200
GET /api/me/bootstrap, "people" menu group:
    recruiter   -> [People]
    interviewer -> [People]
    admin       -> [Onboarding, People, Org chart, Performance, Compensation, Succession, Helpdesk, Assets, Exits]
```
`scripts/probe.py` now also overrides `get_current_user_optional`. Before this, bootstrap probes ran as anonymous.

**Screenshot:** `people-directory.png`, `people-hr.png` -- **pending login proof**.

---

## 17.4 One scoring language

**Wrong:**
- Four different numbers ("Resume match", "Screening score", "Interview-ready score", "Rank score") and two separate marks ("Automatic screening mark", "Interview-ready / Pass mark").
- Three more settings (weights, formula, auto-shortlist threshold) were stored but never used.

**Changed:**
- **One score everywhere:** "Match score (0-100)", stored in `applications.composite_score` and built by the configurable rules (17.5). The AI resume fit is now only the factor "Skills match (AI)".
- **One threshold:** "Shortlist threshold", with a company default in setting `recruitment.scoring.shortlist_threshold` and a per-job value in its shortlisting rules.
  - The migration copied each company's interview-ready mark into it. ctd-techs: 22.
  - The seven old keys are no longer registered. Their stored rows are kept.
  - `GET/PUT /screening/settings` is now `{shortlist_threshold}`.
- **Frontend:**
  - The two threshold panels are replaced by one `ShortlistThresholdPanel` on the Screening dashboard.
  - Every column, filter, tooltip, chart, export header and dashboard tile now says "Match score" or "Shortlist threshold".
  - The profile radar line reads the shortlist threshold.
- **Backend stats** (candidates dashboard average and distribution, job summary, my interviews) now use the Match score.

**Verified:**
```
GET /screening/settings -> 200 {"shortlist_threshold": 22.0}   (migrated from interview_min_score)
old keys recruitment.screening.{dashboard,interview}_{min,max}_score, auto_shortlist_threshold, weights,
composite_formula -> not registered; grep of backend app/: no readers left
tsc --noEmit clean after the relabel
```
**Screenshot:** `screening-dashboard.png`, `candidates-list.png` -- **pending login proof**.

---

## 17.5 Configurable scoring rules

**Wrong:** fixed equal weights in code. Nothing could be configured, knock-outs didn't exist, and there was no explanation.

**Changed:**
- **Engine** (`app/recruitment/scoring/`): 14 factors, each can be switched on or off with a weight from 0 to 100.
  - The switched-on weights must total 100 (auto-balance helps).
  - Knock-outs are shown separately. They flag, never delete and never reject.
  - Five presets: Balanced, Experience first, Location first, Skills first, Budget first.
  - Versioned company and per-job rules, with history and revert.
  - Saving starts a background recalculation with progress, and each old and new score goes into the audit log.
  - "Why this score": each factor's weight, the candidate's value, points earned and resume evidence, plus the knock-out results.
  - Export and import as JSON or XLSX.
- **UI:**
  - Settings > Hiring > **Scoring rules** (company): `ScoringRulesEditor` plus the company shortlisting defaults.
  - Job wizard steps **Scoring** and **Shortlisting rules**.
  - Candidate profile **Why this score** card (`WhyThisScore.tsx`).

**Verified (API, `scripts/probe.py`):**
```
GET  /api/v1/scoring/catalog -> 14 factors, 5 presets
GET  /api/v1/scoring/rules -> source preset (Balanced), threshold 22 (company)
PUT  rules with weights totalling 120 -> 400 "...add up to 120%. They must add up to 100% - use auto-balance."
POST /balance -> skills_ai 25, must_have 25, nice_to_have 13, location 17, certifications 8, recent_skills 12 = 100
PUT  job rules v1 (Skills first), v2 (Experience first), POST revert to v1 -> v3 "Went back to version 1"
GET  /export?format=xlsx -> 6509-byte workbook; POST /import (that file) -> same weights back (not saved)
DELETE /rules?job_id -> job back on company rules (3 versions removed)
POST /preview "Location first" on Automation Anywhere Architect (nothing saved):
     Pradeep 73.6 -> 81.0 (Pune, ~0 km from the job: location 100)
     Kranthi 74.2 -> 52.5 (Hyderabad, ~506 km: location 15)
GET  /applications/{Pradeep}/why -> score 73.9 = sum of factor points
     Must-have skills w20 "11 of 21 must-haves" (experience-years lines no longer counted as skills)
Recalculation on the demo job "Demo - RPA Developer" (Location first):
     run 8afc3929: status done, total 3, done 3, changed 3
     audit score_recalculated old->new: Asha 94.8->96.6, Karan 54.1->44.4, Nisha 33.6->26.6
```
**Screenshot:** `settings-scoring.png`, `job-wizard-scoring.png`, `candidate-why.png` -- **pending login proof**.

---

## 17.6 Automated shortlisting

**Wrong:** there was no auto-shortlist step. The undo window existed, but nothing used it.

**Changed:**
- **Job rules** (`job_roles.shortlisting_json`, with company defaults in `recruitment.shortlisting.*`): auto-shortlist on/off, threshold, maximum shortlist size, undo window (business hours) and who is notified.
- **When on:** a scored or rescored application that is Screened, not knocked out, and at or above the threshold becomes Shortlisted.
  - A bell notification goes to the job owner or hiring manager, else the admins.
  - The undo button shows until the window ends. Undo is final.
  - Interview scheduling starts only after the window closes (beat job `auto_shortlist_release`).
  - Nobody is ever rejected automatically.
- **Shortlisting page** is now a queue:
  - tabs: Suggested by AI, Needs a look (knocked out, with the reason), Shortlisted (with the AI notice and undo), Rejected, each with a count;
  - a job filter;
  - bulk shortlist, and bulk reject with a required reason;
  - compare up to 3;
  - a Match score chip against the job's threshold.

**Verified (demo job):**
```
PUT /api/v1/scoring/shortlisting?job_id=<demo> {"auto_shortlist":true,"threshold":80,"undo_hours":4,"max_size":5}
rescore -> Asha (96.6) hr_selected; Karan (44.4), Nisha (26.6) stay screened
audit ai_auto_shortlisted: score 96.6, threshold 80, undo_until 2026-09-28T07:30Z (4 business hours)
POST undo-auto-shortlist -> 200 screened; again -> 409 "This was already undone"
rescore after undo -> Asha stays screened (undo is final)
threshold 40 + rescore -> Karan hr_selected; bell to admin "Demo - Karan Joshi was shortlisted automatically..."
```
Not run live: the release into interview scheduling after the window, because that would email interview slots to a candidate. It is covered by `release_due` plus the beat job.

**Screenshot:** `shortlisting-queue.png` -- **pending login proof**.

---

## 17.7 HR Inbox -> Candidate emails

**Wrong:** "HR Inbox" was a raw mail table. It didn't say what a mail was about, whether anyone had handled it, or how mail arrives.

**Changed:**
- Renamed to **Candidate emails** (menu, page, `/candidate-emails` alias of `/hr-inbox`), with the page line as specified.
- Tabs **Needs action / Linked to a candidate / Not matched**, each with a count.
- Email cards show the candidate (or sender), the job, a topic chip, a one-line summary (marked "AI" when the AI wrote it), and the buttons Open candidate / Reply / Mark done (Assign to candidate when not matched).
- Backend (`app/hr_inbox/triage.py`):
  - topic by keyword rules;
  - summary by the AI (governed feature `recruitment.email_summary`, at most 5 per page load), else the reply's first real sentence with quoted history and greetings removed;
  - automatic senders (no-reply, newsletters, bounces) are labelled "Automatic email - not from a candidate" and marked done.
  - Triage also runs when mail arrives, and the timeline entry carries the summary. Linked replies already show on the candidate's timeline.
- Empty state and a no-mailbox banner explain how mail arrives, with a **Connect mailbox** button (`/settings/communication/mailboxes`).

**Verified (API):**
```
GET /api/v1/ui/candidate-emails?tab=not_matched -> 200, mailbox_connected true,
    counts {needs_action 0 after triage, linked 0, not_matched 12}
    the 12 real rows are Google system mails (workspace-noreply@, no-reply@accounts.google.com, mailer-daemon@)
    -> topic automated, status done, "Automatic email - not from a candidate"
topic/summary rules on sample replies:
    "Re: Interview schedule" -> interview_time | "Tuesday 3 pm works for me."   (quoted "On Mon, HR wrote:" dropped)
    "Documents"              -> documents      | "Dear team, attached my PAN card and last payslip as requested."
    "Re: Offer"              -> offer          | "Could you please confirm if the CTC includes the joining bonus?"
    "Update"                 -> withdrawal     | "I have accepted another offer, so I would like to withdraw my application."
First run: the AI wrote meta-comments about the promotional mails ("This is a promotional email...").
Fixed: automatic-sender rule plus a NOT_CANDIDATE answer in the prompt.
npm run build (with i18n:check) OK
```
**Screenshot:** `candidate-emails.png` -- **pending login proof**.

---

## 17.8 Salary - automate collection and checks

**Wrong:**
- The expected salary had to be typed in by hand, and validation was a manual button.
- Nothing asked the candidate for anything, and there was no offer suggestion.

**Changed:**
- **Collection**, where the first source wins and nothing gets overwritten:
  1. The careers apply form asks for current and expected salary and notice period. Expected salary and notice are required unless `recruitment.careers.ask_salary` is off.
  2. The resume parser now reads `current_ctc` / `expected_ctc` / `notice_period_days` / `languages` when they are stated.
  3. The **Salary & joining details** form (`/salary-details/:token`: branded, mobile, one-time link) is emailed automatically on Shortlist when something is missing, with one reminder after 24h.
- **Band check** on every new figure (`applications.salary_check`): in band / needs approval (at most `recruitment.salary.approval_margin_pct`, 10% by default) / flagged / waiting / no band.
  - At the salary stage (interview passed): in band becomes auto-approved at the suggestion. Above the band goes to salary_above_band plus an approval request to the approvers (else the hiring manager, else the admins).
  - New figures back inside the band get auto-approved.
- **Offer suggestion:** the current salary plus `target_hike_pct` (20%), at least what they expect when that fits, clamped to the band and rounded to 10,000. The offer CTC defaults to approved, then the suggestion, then the expected figure.
- **Salary page = queue:**
  - chips Waiting for candidate / In band / Needs approval / Far above band / Approved / Declined, with counts and a job filter;
  - a band bar with the expected-salary marker and the suggestion;
  - Approve/Decline, Send form / Send again (the link is shown when mail can't go), and Edit figures.

**Verified (API + in-process, demo candidates only):**
```
GET /api/v1/ui/salary/queue -> Karan in_band (pos 43%, suggest 1,100,000); 2 real candidates "Waiting for candidate"
PUT figures Karan expects 1,600,000 -> needs_approval (6.7% over, margin 10)
               expects 2,000,000 -> flagged (33.3% over)
               expects 1,200,000 -> in_band (suggest 1,200,000 = current 1,000,000 + 20%)
Asha at salary stage, expects 1,400,000 (current 1,150,000) -> salary_approved, approved 1,400,000 (in band, pos 86%)
Nisha at salary stage, expects 1,600,000 -> salary_above_band + bell to admin "Salary approval needed: ... (6.7% above the band)"
public form GET -> 200 prefilled; POST invalid (-5) -> 422; POST valid -> 200; POST again -> 410
    "Thanks - we already have your answers."; unknown link -> 404
after the form: Nisha 800,000 / 1,000,000 / 30 days / relocate yes -> in_band -> salary_approved at 1,000,000
npm run build OK
```
Not run live: the real email of the form link. It goes through the company mailbox to the candidate, so the link was created in-process for the demo candidate instead.

**Screenshot:** `salary-queue.png`, `salary-details-form.png`, `careers-apply.png` -- **pending login proof** (the form and careers pages are public; screenshots will be taken in 17.14).
