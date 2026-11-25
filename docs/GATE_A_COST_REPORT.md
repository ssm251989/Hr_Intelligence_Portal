# Gate A - AI cost report and draft pricing

Part 33 · data 2026-10-01 to 2026-11-30 · built 2026-11-25 by `backend/scripts/gate_a_report.py` (re-run it to refresh) · Excel: `docs/reports/GATE_A_COST_REPORT.xlsx`

> Prices are Claude **list prices** (Sonnet 5 $2/$10, Haiku 4.5 $1/$5 per million tokens in/out, 1 USD = Rs 88 from `ai.fx_rates`). All Rs figures are AI only - no hosting, support, payment fees or GST.

## 1. One-line answer

**AI costs about Rs 0.88 per resume, Rs 60 per job (50 applicants) and Rs 66 per hire (1 hire per job) - at today's Claude list prices.**

- Per resume is measured (30 resumes, real model). Per job and per hire are built from measured unit costs and the assumptions in section 6; a heavy job (150 applicants, 15 questions) is Rs 177 per job / Rs 184 per hire.
- If Sonnet 5's $2/$10 launch price has ended and $3/$15 applies (sources disagree - list price, check): Rs 68 per job, Rs 77 per hire. Per resume does not change (Haiku).

## 2. Cost per unit

Median and p90 (9 in 10 cost less). *Estimate* = fewer than 20 samples. Source: *controlled run* = the Gate A run (section 6), *recorded* = the install's own AI usage rows.

| Unit | Median | p90 | Samples | Model | Source |
|---|---|---|---|---|---|
| Resume screened (read + suitable-job check + screening) | Rs 0.88 | Rs 0.99 | 30 | claude-haiku-4-5 | controlled run |
| JD drafted | Rs 0.81 | Rs 0.92 | 5 (estimate) | claude-sonnet-5 | recorded |
| HR-assistant question (assistant + specialist agent) | Rs 2.82 | Rs 3.63 | 20 | claude-sonnet-5 | recorded |
| Policy question (Copilot) | Rs 0.23 | Rs 0.26 | 7 (estimate) | claude-sonnet-5 | recorded |
| Interview summary | Rs 0.17 | Rs 0.17 | 2 (estimate) | claude-sonnet-5 | controlled run |
| BGV report reading | Rs 0.30 | Rs 0.33 | 2 (estimate) | claude-sonnet-5 | controlled run |
| Employee exit (exit summary) | Rs 0.33 | Rs 0.62 | 3 (estimate) | claude-sonnet-5 | recorded |
| Hire - the hired application's own AI | Rs 0.83 | Rs 0.83 | 2 (estimate) | claude-haiku-4-5 | recorded; document checks only; agents are counted below |
| **Job, modelled** (50 applicants) | **Rs 59.84** | - | - | Haiku 4.5 + Sonnet 5 | measured units x section 6 |
| **Hire, modelled** (1 per job) | **Rs 66.29** | - | - | Haiku 4.5 + Sonnet 5 | job + hire journey |

Agent runs (one run = the calls one agent makes for one request):

| Agent run | Median | p90 | Samples | Source |
|---|---|---|---|---|
| Screening agent | Rs 3.27 | Rs 4.13 | 4 (estimate) | controlled run |
| Job agent | Rs 0.90 | Rs 1.29 | 5 (estimate) | recorded |
| Scheduling agent | Rs 1.79 | Rs 1.79 | 1 (estimate) | recorded |
| Salary agent | Rs 2.34 | Rs 2.37 | 3 (estimate) | recorded |
| Offer agent | Rs 1.87 | Rs 1.91 | 3 (estimate) | recorded |
| BGV agent | Rs 2.56 | Rs 2.66 | 4 (estimate) | recorded |
| Onboarding agent | Rs 1.11 | Rs 1.88 | 3 (estimate) | recorded |
| Exit agent | Rs 1.80 | Rs 1.80 | 1 (estimate) | recorded |
| Daily briefing | Rs 0.57 | Rs 0.63 | 23 | recorded |

How the modelled job and hire add up:

- JD draft: Rs 0.81
- 50 resumes read + screened: Rs 44.07
- 5 interview summaries: Rs 0.83
- 5 HR-assistant questions: Rs 14.12
- = **Rs 59.84 per job**; per hire adds the hire journey Rs 6.45 (documents and checks (recorded hires) Rs 0.83, BGV report reading Rs 0.30, salary agent run Rs 2.34, offer agent run Rs 1.87, onboarding agent run Rs 1.11)
- Cross-check: the run's 3 jobs (10 applicants each) measured Rs 10.17 median for everything recorded on the job (JD draft, resumes, an interview summary on two of them); the model gives Rs 9.63 for a JD + 10 applicants - within 5%.

## 3. What drives cost, and three ways to cut it

In the controlled run (Rs 51.70 for 188 calls) the spend splits as follows:

| Step | Model | Calls | Avg tokens in / out | Rs per call | Share |
|---|---|---|---|---|---|
| `recruitment.screening` | claude-haiku-4-5 | 120 | 1,150 / 27 | 0.113 | 26% |
| `recruitment.resume_parsing` | claude-haiku-4-5 | 30 | 2,488 / 506 | 0.442 | 26% |
| `agents.screening` | claude-sonnet-5 | 17 | 2,389 / 394 | 0.767 | 25% |
| `agents.hr_assistant` | claude-sonnet-5 | 11 | 2,182 / 187 | 0.549 | 12% |
| `recruitment.jd_generation` | claude-sonnet-5 | 3 | 1,672 / 811 | 1.008 | 6% |
| `agents.job` | claude-sonnet-5 | 3 | 1,451 / 410 | 0.616 | 4% |
| `agents.bgv_reader` | claude-sonnet-5 | 2 | 527 / 238 | 0.303 | 1% |
| `agents.interview_summary` | claude-sonnet-5 | 2 | 218 / 145 | 0.166 | 1% |

- **Resumes** are the volume driver: Rs 0.88 each, about half reading (Rs 0.44, ~506 tokens of structured output) and half matching (Rs 0.113 per match, 4 matches per resume).
- **3 of those 4 matches are the 'suitable job' suggestion** (`screening/suitability.py`): every new resume is matched against the top 3 published jobs even when the candidate applied for one. Until this run those calls were recorded with no candidate, so cost per resume looked 38% lower than it is (fixed in 33.2).
- **Agents run on Sonnet 5 and re-send their instructions and tools on every call** (~1,559+ tokens): a question makes 5.2 calls on average, so Rs 2.82 per question - the most expensive single interaction.

Three concrete cuts (saving per unit at today's prices; each needs the owner's go-ahead and a quality check):

1. **Cheaper model for resume reading and matching** - Claude Haiku 5.5 lists at $0.10 / $0.50, a tenth of Haiku 4.5. Saving: **Rs 0.79 per resume**, Rs 40 per typical job (66% of it). Check first: re-screen the 30 Gate A resumes on Haiku 5.5 and compare scores and parsed fields with today's; switch `ai.models.*` only if they hold.
2. **Fewer / shorter calls on each resume** - match the suitable-job suggestion against the top 1 job instead of 3, or skip it when the candidate applied for a specific job: saves Rs 0.23-Rs 0.34 per resume (Rs 11-Rs 17 per job). Halving the reading prompt's fixed instructions (~1,922 tokens on every resume) saves another ~Rs 0.085 per resume.
3. **Prompt caching for the agents** - their fixed instructions + tools (~1,559 tokens, above Sonnet 5's 1,024-token minimum) are re-sent on every call; cached reads bill at 10%. Estimated saving **Rs 0.64 per question** (23%), Rs 3.20 per job, more when questions come within 5 minutes of each other. Screening already marks the JD for caching but it never caches: Haiku 4.5 only caches prompts of 4,096+ tokens and a screening prompt is ~1,150. Also record `cache_read_input_tokens` / `cache_creation_input_tokens` in `ai_usage_records` - today only `input_tokens` is kept, which leaves cached tokens out of the cost once caching is on.

## 4. Amazon Bedrock vs Anthropic direct (list price, check)

Same models, same token counts. Bedrock's global cross-region profile lists at the same per-token price as Anthropic; the India geographic profile (Mumbai / Hyderabad, data stays in India) is noted in the app's price table as ~10% higher. **List price, check** against the AWS invoice / the Bedrock pricing page before quoting - and note sources disagree on whether Sonnet 5's $2/$10 launch price still applies on either.

| Unit | Anthropic direct | Bedrock global | Bedrock India (+10%) | Sonnet at $3/$15 |
|---|---|---|---|---|
| Resume | Rs 0.88 | Rs 0.88 | Rs 0.97 | Rs 0.88 |
| JD draft | Rs 0.81 | Rs 0.81 | Rs 0.89 | Rs 1.22 |
| HR-assistant question | Rs 2.82 | Rs 2.82 | Rs 3.11 | Rs 4.24 |
| Job (50 applicants) | Rs 59.84 | Rs 59.84 | Rs 65.82 | Rs 67.72 |
| Hire | Rs 66.29 | Rs 66.29 | Rs 72.92 | Rs 76.98 |

Batch processing (50% off on both) fits only work nobody waits for, e.g. a nightly re-screen of a whole job; the screens and agents answer people live, so the report does not count it.

## 5. Draft pricing - DRAFT, for management (the owner decides)

Three plans from the blueprint, each with the AI cost inside it and the AI margin at three price points. Margin here = (price - AI cost) / price; hosting, support, sales and GST still come out of it.

**Lite - per API call** (one call = one resume read + screened; AI cost Rs 0.88 median, Rs 0.99 p90)

| Price per call | AI cost | AI margin (median) | AI margin (p90) |
|---|---|---|---|
| Rs 2 | Rs 0.88 | 56% | 51% |
| Rs 5 | Rs 0.88 | 82% | 80% |
| Rs 10 | Rs 0.88 | 91% | 90% |

**Pro - per active job per month, web app included** (AI cost Rs 60 typical, Rs 177 heavy)

| Price per job / month | AI margin (typical) | AI margin (heavy) |
|---|---|---|
| Rs 750 | 92% | 76% |
| Rs 1,500 | 96% | 88% |
| Rs 3,000 | 98% | 94% |

**Enterprise - platform fee + per hire, on-prem** (AI cost Rs 66 per hire typical, Rs 184 heavy; platform fee e.g. Rs 50,000 / month for hosting and support, no AI inside it)

| Price per hire | AI margin (typical) | AI margin (heavy) |
|---|---|---|
| Rs 1,000 | 93% | 82% |
| Rs 2,500 | 97% | 93% |
| Rs 5,000 | 99% | 96% |

On-prem customers can bring their own Anthropic or Bedrock key; the AI cost is then theirs and the per-hire price is margin before hosting and support.

## 6. Assumptions and what was excluded

- **Recorded data**: 226 AI calls (Rs 85.41) on this install, all from CTD's own development and proof sessions - there is no customer production usage yet, so volumes are test volumes; the per-call token counts are real.
- **Excluded - proof / test job**: 5 calls (Rs 1.98).
- **Excluded - sandbox company**: 7 calls (Rs 1.35).
- **Controlled run (Gate A, 2026-11-25)**: real model, mail to Mailpit; 30 SYNTHETIC resumes (`docs/samples/gate_a/`, 204-576 words, median ~345 - real resumes are often longer, which raises reading cost roughly in proportion) against 3 jobs (10 each), 3 JD drafts, 5 HR-assistant questions, 2 interview summaries, 2 BGV report readings: 188 calls, Rs 51.70. The test jobs, candidates, applications and files were deleted afterwards; the AI usage rows were kept and tagged `gate-a-run`.
- **One shortcut in the run**: the Salary module is on, so BGV can only start after a salary approval that needs the candidate's form; the 2 BGV applications were set to `salary_approved` in the database. Everything else went through the real API.
- **Re-pricing**: every call is priced from its tokens with today's `ai.pricing` (rows recorded at Rs 0 before prices were set are included at today's price).
- **Questions and agent runs** are split from the call stream: a new question starts after a 45 s pause or when the assistant is called twice in a row. Agent calls carry no conversation id, so this is a rule, not a recorded link.
- **Typical job**: 50 applicants, 5 interviews, 5 assistant questions, 1 hire. Heavy job: 150 applicants, 10 interviews, 15 questions. Change them in `scripts/gate_a_report.py` and re-run.
- **Hire journey** uses recorded agent runs (salary, offer, onboarding: 3 samples each - estimates) plus the measured BGV reading; it assumes one run of each agent per hire.
- **Not in any number**: the daily briefing (Rs 0.57 per briefing, a per-company cost, not per job), hosting, verification fees, e-mail/SMS, support.
- **Found during the run**: the HR assistant answered "draft interview questions" with "no agent can do this" although the app has an interview-kit feature - a product gap, not a cost item.

