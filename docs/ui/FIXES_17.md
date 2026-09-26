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
