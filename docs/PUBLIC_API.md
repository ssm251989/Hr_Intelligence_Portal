# HR Automation public API

Call the HR agents from your own systems (ATS, HRIS, careers site, Slack bot...) and hear what happened through
webhooks. The API runs the same code as the screens: the same rules, the same approval cards, the same reviewers.
Nothing is decided about a person without a human - the API can prepare and approve cards, never skip them.

- Base URL: `https://<your-company-host>/api/public/v1`
- Reference (every endpoint, live): `https://<your-company-host>/api/public/v1/docs` (OpenAPI: `/api/public/v1/openapi.json`)

## Quick start

1. An admin opens **Settings > Developers** (menu: Admin > Developers), creates a key, ticks the scopes it needs and
   copies the key. **The key is shown once**; only its SHA-256 is kept. Keys start with `hra_live_` (your company) or
   `hra_test_` (your sandbox company).
2. First call:

```bash
curl -H "Authorization: Bearer $KEY" https://<your-company-host>/api/public/v1/jobs
```

```json
{"items": [{"id": "f494e13c-...", "title": "Backend Developer", "status": "draft", "has_jd": false, ...}]}
```

A key **acts as the person who created it**: their permissions apply to every call (an interviewer's key cannot
decide a salary card). If that person is deactivated the key stops working. Revoke a key on the same page; it stops at once.

## Test mode (sandbox)

`hra_test_` keys exist only on a sandbox company (slug `sandbox` or `<company>-sandbox`, created by CTD with
`python -m hrctl.tenant create --slug <company>-sandbox --isolation shared_rls ...`). All mail of the sandbox goes to the
test mailbox. A test key never reaches live data and a live key never works on the sandbox (`403 wrong_mode`).
On the sandbox a webhook may point at `http://localhost` / `http://127.0.0.1` for local testing; live webhooks must be
public `https://` URLs.

**What test keys cover today:** screening, jobs (incl. JD drafts and the Publish card), applications and cards.
**Interview scheduling works with live keys only** for now: a sandbox company shares the installation database and the
interview-scheduling settings are still one row per installation (docs/FUTURE_WORK.md, cloud / AWS phase). On the
sandbox, `POST /applications/{id}/interview-scheduling` - and approving a shortlist card, which starts scheduling -
does not get the interview times out.

## Scopes

| Scope | Endpoints |
|---|---|
| `screening` | `POST /screenings` |
| `jobs` | `POST /jd-drafts`, `POST /jobs`, `GET /jobs`, `GET /jobs/{id}` |
| `candidates` | `POST /jobs/{id}/applications`, `GET /applications/{id}`, `GET /applications/{id}/journey` |
| `scheduling` | `POST /applications/{id}/interview-scheduling` |
| `cards` | `GET /cards`, `POST /cards/{id}/decision` |
| `sensitive` | adds salary figures where an answer has them (`GET /jobs/{id}` salary band) |

A scope also needs its module to be active for your company (jobs, candidates, screening, interviews); otherwise
`403 module_not_active`.

## Endpoints

| Method + path | What it does (the screen it matches) |
|---|---|
| `POST /screenings` | Form: `resume` (file) or `resume_text` (the whole resume, 80+ letters), and `jd_text` or `job_id`. Returns `score` 0-100, `location_score`, `reasons`, `missing_skills` (with a `job_id`), `knockouts` (the job's knock-out questions). Nothing is stored. |
| `POST /jd-drafts` | JSON role inputs (`title`, `location`, `technical_skills_must_have`, `key_responsibilities` ...) -> `jd_text`. The Job agent's drafting; never invents a salary or benefit. |
| `POST /jobs` | Creates a **draft** job (the Jobs screen's create). The Job agent then prepares the "Publish <title>" card once nobody has changed the job for 10 minutes. The API never publishes by itself - approve the card. |
| `GET /jobs`, `GET /jobs/{id}` | Jobs (optional `?status=`). `salary_band` only with `sensitive`. |
| `POST /jobs/{id}/applications` | Form: `resume` (file), `full_name`, `email`, `phone`, `consent=true`, `consent_text` (the wording the candidate agreed to; stored), `knockout_answers` (JSON list, in the job's question order), `current_ctc`, `expected_ctc`, `notice_period_days`. The careers page's apply: the same duplicate block, deadline, knock-outs and salary questions. |
| `GET /applications/{id}` | `status`, `score`, `missing_skills`, `next_step` in words, `waiting_card` (the card waiting for HR, if any). |
| `GET /applications/{id}/journey` | What the agents did for this candidate, oldest first. |
| `POST /applications/{id}/interview-scheduling` | = "Send interview times now". 409 with the reason when they cannot go out. |
| `GET /cards` | The approval cards the key's owner can decide (the same as "Waiting for you"). |
| `POST /cards/{id}/decision` | `{"action": "approve"}`, `{"action": "reject"}` or `{"action": "edit", "payload": {...the changed card...}}`. Same appliers and reviewer rules as the screen; a refusal (e.g. "Fill before publishing: interviewer pool") is a 409 and the card stays waiting. |

## Errors

Every error is JSON: `{"error": {"code": "...", "message": "..."}}` - the message is written for a person.

| HTTP | Codes |
|---|---|
| 401 | `missing_key`, `invalid_key`, `revoked_key`, `expired_key`, `owner_inactive` |
| 403 | `missing_scope`, `wrong_mode`, `module_not_active`, `forbidden`, `ai_off` |
| 404 | `not_found` (also for another company's ids) |
| 409 | `conflict`, `not_started`, `idempotency_key_reused` |
| 422 | `invalid`, `consent_required`, `resume_too_short`, `unreadable_resume` |
| 429 | `rate_limited` - wait `Retry-After` seconds |
| 502 / 503 | `ai_failed` / `ai_unavailable` (the AI service; retry later) |
| 500 | `server_error` (retry; send the same `Idempotency-Key`) |

## Limits and safe retries

- **Rate limit:** 60 calls a minute per key (an admin can change `platform.api.rate_limit_per_minute`). Above it:
  `429` with `Retry-After`.
- **Idempotency:** send `Idempotency-Key: <your unique id>` on every POST. A retry with the same key gets the first
  answer back (header `Idempotent-Replay: true`) for 24 hours and nothing is done twice. The same key on a different
  path is refused (`409 idempotency_key_reused`).
- **Metering:** every call is counted per key (Settings > Developers shows calls per day).

## Webhooks

Settings > Developers > Webhooks: your URL, the events, and optionally the `sensitive` scope. **The signing secret
(`whsec_...`) is shown once.** We POST JSON:

```json
{"id": "<delivery id>", "event": "application.created", "occurred_at": "2026-11-20T16:59:41+00:00",
 "data": {"application_id": "...", "job_id": "...", "candidate_id": "...", "status": "received", "link": "https://.../candidates/..."}}
```

Headers: `X-Event`, `X-Delivery-Id`, `X-Signature` = hex HMAC-SHA256 of the raw body with your secret. Answer any
2xx. Anything else (or no answer in 10 s) is retried after 1, 5, 30 minutes, 2 hours and 12 hours, then marked
failed; "Resend" on the delivery log tries again. "Send test ping" sends event `ping`.

Payloads carry ids, status and a link - never resume text, and salary figures only for a subscription with the
`sensitive` scope.

| Event | When |
|---|---|
| `application.created` | a candidate applied (careers page, API, import) |
| `application.screened` | the screening score is ready |
| `interview.scheduled` | an interview was booked |
| `interview.decided` | an interviewer recorded a decision |
| `salary.decided` | the salary was approved / countered / declined (by HR or a company rule) |
| `bgv.decided` | background verification passed or found a discrepancy |
| `offer.sent`, `offer.signed` | the offer went out / was signed |
| `employee.joined` | the joiner joined |
| `separation.approved` | a resignation's last working day was approved |
| `job.published` | a job went on the careers page |
| `card.created`, `card.decided` | an approval card was raised / decided (approved, changed, declined or closed) |

### Verify a webhook - Python

```python
import hashlib, hmac

def verify(raw_body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")

# Flask: verify(request.get_data(), request.headers["X-Signature"], SECRET)
```

### Verify a webhook - Node

```js
const crypto = require("crypto");

function verify(rawBody, signature, secret) {
  const expected = crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
  const a = Buffer.from(expected), b = Buffer.from(signature || "");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// Express: app.post("/hook", express.raw({ type: "application/json" }), (req, res) =>
//   verify(req.body, req.get("X-Signature"), SECRET) ? res.sendStatus(200) : res.sendStatus(401));
```

Always verify the **raw** body (before any JSON parsing), and de-duplicate on `X-Delivery-Id` (a retry repeats it).
Events are collected once a minute, so deliveries from the same minute may arrive in any order: sort on
`occurred_at`. `data.status` is the record's status when the event is sent (it may already have moved on).
