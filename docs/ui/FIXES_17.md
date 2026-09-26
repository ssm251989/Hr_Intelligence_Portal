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
