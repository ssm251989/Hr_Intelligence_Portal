"""Part 33.3: builds docs/GATE_A_COST_REPORT.md + docs/reports/GATE_A_COST_REPORT.xlsx from the AI cost report
(scripts/ai_cost_report.collect) and the assumptions below. Read-only on the database.

    python -m scripts.gate_a_report --since 2026-10-01 --until 2026-11-30

Every Rs figure in the document is computed here from the recorded AI usage rows (re-priced with ai.pricing) and the
ASSUMPTIONS block; change an assumption and re-run to get a new report.
"""

import argparse
from datetime import date, datetime, time, timezone
from pathlib import Path

from app.platform.ai import cost_report as cr
from app.platform.ai.cost_report_xlsx import to_xlsx
from scripts.ai_cost_report import collect

ROOT = Path(__file__).resolve().parents[2]

# ---- the owner can change these and re-run -------------------------------------------------------------------
ASSUMPTIONS = {
    "applicants_per_job": 50,  # typical job; "heavy" below
    "interviews_per_job": 5,
    "assistant_questions_per_job": 5,
    "hires_per_job": 1,
    "heavy_applicants_per_job": 150,
    "heavy_interviews_per_job": 10,
    "heavy_assistant_questions_per_job": 15,
    "sonnet_alt_price": (3, 15),  # USD per million in/out if Sonnet 5's $2/$10 launch price has ended (list price, check)
    "bedrock_india_premium": 0.10,  # app's own note: India / regional endpoints ~10% above global (list price, check)
    "haiku_55_price": (0.10, 0.50),  # Claude Haiku 5.5 list price, USD per million in/out
    "cache_read_factor": 0.10, "cache_write_factor": 1.25,
    "lite_prices": (2, 5, 10), "pro_prices": (750, 1500, 3000), "enterprise_hire_prices": (1000, 2500, 5000),
    "enterprise_platform_fee": 50000,
}


def _rs(v, nd=2):
    return "-" if v is None else f"Rs {v:,.{nd}f}"


def _pct(v):
    return f"{v * 100:.0f}%"


def build(since: datetime, until: datetime) -> tuple[str, bytes, str]:
    rep = collect(since, until, extra_links=[ROOT / "docs" / "samples" / "gate_a" / "run_links.json"])
    A = ASSUMPTIONS
    rec, ctl = rep["sources"]["recorded"], rep["sources"]["controlled"]
    fx = rep["usd_to_inr"]
    sonnet = {"in": rep["pricing"]["claude-sonnet-5"]["input_per_mtok"], "out": rep["pricing"]["claude-sonnet-5"]["output_per_mtok"]}

    def unit(source, key, agent=False):
        u = (source["agents"] if agent else source["units"]).get(key) or {"samples": 0}
        return u

    def pick(key, agent=False, prefer="controlled"):
        """The unit from the source with more samples (ties -> prefer)."""
        a, b = unit(ctl, key, agent), unit(rec, key, agent)
        order = [(a, "controlled run"), (b, "recorded")] if prefer == "controlled" else [(b, "recorded"), (a, "controlled run")]
        best = max(order, key=lambda o: o[0]["samples"])
        return best if best[0]["samples"] else (None, None)

    U = {}
    for label, key, agent in [("resume", "resume", False), ("jd", "jd", False), ("question", "question", False),
                              ("policy_question", "policy_question", False), ("exit", "exit", False), ("hire_journey", "hire", False),
                              ("interview_summary", "agents.interview_summary", True), ("bgv_read", "agents.bgv_reader", True),
                              ("salary_run", "agents.salary", True), ("offer_run", "agents.offer", True),
                              ("onboarding_run", "agents.onboarding", True), ("scheduling_run", "agents.scheduling", True),
                              ("exit_agent_run", "agents.exit", True), ("briefing", "agents.briefing", True),
                              ("screening_agent_run", "agents.screening", True), ("bgv_agent_run", "agents.bgv", True),
                              ("job_agent_run", "agents.job", True)]:
        u, src = pick(key, agent)
        U[label] = {"u": u, "src": src, "med": u["inr"]["median"] if u else None}

    R, JD, Q, I = U["resume"]["med"], U["jd"]["med"], U["question"]["med"], U["interview_summary"]["med"]
    hire_journey_parts = {"documents and checks (recorded hires)": U["hire_journey"]["med"], "BGV report reading": U["bgv_read"]["med"],
                          "salary agent run": U["salary_run"]["med"], "offer agent run": U["offer_run"]["med"],
                          "onboarding agent run": U["onboarding_run"]["med"]}
    HJ = sum(v for v in hire_journey_parts.values() if v)

    def job_cost(apps, interviews, questions):
        parts = {"JD draft": JD, f"{apps} resumes read + screened": apps * R, f"{interviews} interview summaries": interviews * I,
                 f"{questions} HR-assistant questions": questions * Q}
        return sum(parts.values()), parts

    job_typ, job_parts = job_cost(A["applicants_per_job"], A["interviews_per_job"], A["assistant_questions_per_job"])
    job_heavy, _ = job_cost(A["heavy_applicants_per_job"], A["heavy_interviews_per_job"], A["heavy_assistant_questions_per_job"])
    hire_typ = job_typ / A["hires_per_job"] + HJ
    hire_heavy = job_heavy / A["hires_per_job"] + HJ
    # Sonnet share (JD, interview summaries, questions, hire-journey agents) at the alternative Sonnet list price
    s_in, s_out = A["sonnet_alt_price"]
    sonnet_factor = ((s_in / sonnet["in"]) + (s_out / sonnet["out"])) / 2  # both rise by the same ratio at $3/$15 -> 1.5
    sonnet_job = JD + A["interviews_per_job"] * I + A["assistant_questions_per_job"] * Q
    sonnet_hire_journey = HJ - (U["hire_journey"]["med"] or 0)
    job_alt = job_typ + sonnet_job * (sonnet_factor - 1)
    hire_alt = hire_typ + (sonnet_job + sonnet_hire_journey) * (sonnet_factor - 1)

    # ---- drivers and cuts (controlled run = the clean per-call numbers)
    drv = {(d["feature"], d["model"]): d for d in ctl["drivers"]}
    drv_rec = {(d["feature"], d["model"]): d for d in rec["drivers"]}
    screen_call = drv[("recruitment.screening", "claude-haiku-4-5")]["inr_per_call"]
    parse = drv[("recruitment.resume_parsing", "claude-haiku-4-5")]
    suit_calls_per_resume = 3  # PRE_FILTER_TOP_N; measured: exactly 3 per candidate in the run
    cut_suit = suit_calls_per_resume * screen_call
    cut_suit_top1 = (suit_calls_per_resume - 1) * screen_call
    h_in, h_out = A["haiku_55_price"]
    haiku_ratio = h_in / 1.0  # both in and out are 1/10 of Haiku 4.5
    cut_model = R * (1 - haiku_ratio)
    fixed_parse_prompt = parse["min_in"] - 300  # smallest resume in the run is ~200 words (~300 tokens)
    cut_parse_prompt = (fixed_parse_prompt / 2) * 1.0 / 1e6 * fx  # halve the fixed instructions, Haiku 4.5 input price
    prefix = min(drv_rec[("agents.hr_assistant", "claude-sonnet-5")]["min_in"], drv[("agents.screening", "claude-sonnet-5")]["min_in"])
    calls_per_q = U["question"]["u"]["calls_per_sample"]
    reuses = max(calls_per_q - 2, 0)  # the assistant's 2 calls share one prefix, the specialist's calls another
    per_token = sonnet["in"] / 1e6 * fx
    cut_cache_q = reuses * prefix * (1 - A["cache_read_factor"]) * per_token - 2 * prefix * (A["cache_write_factor"] - 1) * per_token

    headline = (f"AI costs about {_rs(R)} per resume, {_rs(job_typ, 0)} per job ({A['applicants_per_job']} applicants) and "
                f"{_rs(hire_typ, 0)} per hire ({A['hires_per_job']} hire per job) - at today's Claude list prices.")

    # ---- per-unit table rows
    def row(name, key, note=""):
        x = U[key]
        u = x["u"]
        if not u:
            return f"| {name} | - | - | 0 | - | no data |"
        models = ", ".join(u["models"])
        return (f"| {name} | {_rs(u['inr']['median'])} | {_rs(u['inr']['p90'])} | {u['samples']}{' (estimate)' if u['estimate'] else ''} | "
                f"{models} | {x['src']}{'; ' + note if note else ''} |")

    lines = []
    w = lines.append
    w("# Gate A - AI cost report and draft pricing")
    w("")
    w(f"Part 33 · data {since.date()} to {until.date()} · built {datetime.now():%Y-%m-%d} by `backend/scripts/gate_a_report.py` "
      f"(re-run it to refresh) · Excel: `docs/reports/GATE_A_COST_REPORT.xlsx`")
    w("")
    w("> Prices are Claude **list prices** (Sonnet 5 $2/$10, Haiku 4.5 $1/$5 per million tokens in/out, 1 USD = Rs "
      f"{fx:g} from `ai.fx_rates`). All Rs figures are AI only - no hosting, support, payment fees or GST.")
    w("")
    w("## 1. One-line answer")
    w("")
    w(f"**{headline}**")
    w("")
    w(f"- Per resume is measured (30 resumes, real model). Per job and per hire are built from measured unit costs and the "
      f"assumptions in section 6; a heavy job ({A['heavy_applicants_per_job']} applicants, {A['heavy_assistant_questions_per_job']} questions) "
      f"is {_rs(job_heavy, 0)} per job / {_rs(hire_heavy, 0)} per hire.")
    w(f"- If Sonnet 5's $2/$10 launch price has ended and $3/$15 applies (sources disagree - list price, check): "
      f"{_rs(job_alt, 0)} per job, {_rs(hire_alt, 0)} per hire. Per resume does not change (Haiku).")
    w("")
    w("## 2. Cost per unit")
    w("")
    w("Median and p90 (9 in 10 cost less). *Estimate* = fewer than 20 samples. Source: *controlled run* = the Gate A run "
      "(section 6), *recorded* = the install's own AI usage rows.")
    w("")
    w("| Unit | Median | p90 | Samples | Model | Source |")
    w("|---|---|---|---|---|---|")
    w(row("Resume screened (read + suitable-job check + screening)", "resume"))
    w(row("JD drafted", "jd"))
    w(row("HR-assistant question (assistant + specialist agent)", "question"))
    w(row("Policy question (Copilot)", "policy_question"))
    w(row("Interview summary", "interview_summary"))
    w(row("BGV report reading", "bgv_read"))
    w(row("Employee exit (exit summary)", "exit"))
    w(row("Hire - the hired application's own AI", "hire_journey", "document checks only; agents are counted below"))
    w(f"| **Job, modelled** ({A['applicants_per_job']} applicants) | **{_rs(job_typ)}** | - | - | Haiku 4.5 + Sonnet 5 | "
      f"measured units x section 6 |")
    w(f"| **Hire, modelled** ({A['hires_per_job']} per job) | **{_rs(hire_typ)}** | - | - | Haiku 4.5 + Sonnet 5 | job + hire journey |")
    w("")
    w("Agent runs (one run = the calls one agent makes for one request):")
    w("")
    w("| Agent run | Median | p90 | Samples | Source |")
    w("|---|---|---|---|---|")
    for name, key in [("Screening agent", "screening_agent_run"), ("Job agent", "job_agent_run"), ("Scheduling agent", "scheduling_run"),
                      ("Salary agent", "salary_run"), ("Offer agent", "offer_run"), ("BGV agent", "bgv_agent_run"),
                      ("Onboarding agent", "onboarding_run"), ("Exit agent", "exit_agent_run"), ("Daily briefing", "briefing")]:
        x = U[key]
        u = x["u"]
        w(f"| {name} | {_rs(u['inr']['median']) if u else '-'} | {_rs(u['inr']['p90']) if u else '-'} | "
          f"{u['samples'] if u else 0}{' (estimate)' if u and u['estimate'] else ''} | {x['src'] or '-'} |")
    w("")
    w("How the modelled job and hire add up:")
    w("")
    for k, v in job_parts.items():
        w(f"- {k}: {_rs(v)}")
    w(f"- = **{_rs(job_typ)} per job**; per hire adds the hire journey {_rs(HJ)} (" + ", ".join(f"{k} {_rs(v)}" for k, v in hire_journey_parts.items() if v) + ")")
    run_job = ctl["units"]["job"]
    if run_job["samples"]:
        check, _ = job_cost(10, 0, 0)
        gap = (run_job["inr"]["median"] - check) / run_job["inr"]["median"]
        w(f"- Cross-check: the run's {run_job['samples']} jobs (10 applicants each) measured {_rs(run_job['inr']['median'])} median for "
          f"everything recorded on the job (JD draft, resumes, an interview summary on two of them); the model gives {_rs(check)} for "
          f"a JD + 10 applicants - within {_pct(abs(gap))}.")
    w("")
    w("## 3. What drives cost, and three ways to cut it")
    w("")
    tot = ctl["total_inr"]
    w(f"In the controlled run (Rs {tot:.2f} for 188 calls) the spend splits as follows:")
    w("")
    w("| Step | Model | Calls | Avg tokens in / out | Rs per call | Share |")
    w("|---|---|---|---|---|---|")
    for d in ctl["drivers"]:
        w(f"| `{d['feature']}` | {d['model']} | {d['calls']} | {d['avg_in']:,} / {d['avg_out']:,} | {d['inr_per_call']:.3f} | {_pct(d['inr'] / tot)} |")
    w("")
    w(f"- **Resumes** are the volume driver: {_rs(R)} each, about half reading ({_rs(parse['inr_per_call'])}, ~{parse['avg_out']} tokens of "
      f"structured output) and half matching ({_rs(screen_call, 3)} per match, 4 matches per resume).")
    w(f"- **3 of those 4 matches are the 'suitable job' suggestion** (`screening/suitability.py`): every new resume is matched "
      f"against the top 3 published jobs even when the candidate applied for one. Until this run those calls were recorded with "
      f"no candidate, so cost per resume looked {_pct(cut_suit / R)} lower than it is (fixed in 33.2).")
    w(f"- **Agents run on Sonnet 5 and re-send their instructions and tools on every call** (~{prefix:,}+ tokens): a question makes "
      f"{calls_per_q:.1f} calls on average, so {_rs(Q)} per question - the most expensive single interaction.")
    w("")
    w("Three concrete cuts (saving per unit at today's prices; each needs the owner's go-ahead and a quality check):")
    w("")
    w(f"1. **Cheaper model for resume reading and matching** - Claude Haiku 5.5 lists at $0.10 / $0.50, a tenth of Haiku 4.5. "
      f"Saving: **{_rs(cut_model)} per resume**, {_rs(cut_model * A['applicants_per_job'], 0)} per typical job "
      f"({_pct(cut_model * A['applicants_per_job'] / job_typ)} of it). Check first: re-screen the 30 Gate A resumes on Haiku 5.5 and compare "
      f"scores and parsed fields with today's; switch `ai.models.*` only if they hold.")
    w(f"2. **Fewer / shorter calls on each resume** - match the suitable-job suggestion against the top 1 job instead of 3, or skip it "
      f"when the candidate applied for a specific job: saves {_rs(cut_suit_top1)}-{_rs(cut_suit)} per resume "
      f"({_rs(cut_suit_top1 * A['applicants_per_job'], 0)}-{_rs(cut_suit * A['applicants_per_job'], 0)} per job). Halving the reading "
      f"prompt's fixed instructions (~{fixed_parse_prompt:,} tokens on every resume) saves another ~{_rs(cut_parse_prompt, 3)} per resume.")
    w(f"3. **Prompt caching for the agents** - their fixed instructions + tools (~{prefix:,} tokens, above Sonnet 5's 1,024-token "
      f"minimum) are re-sent on every call; cached reads bill at 10%. Estimated saving **{_rs(cut_cache_q)} per question** "
      f"({_pct(cut_cache_q / Q)}), {_rs(cut_cache_q * A['assistant_questions_per_job'])} per job, more when questions come within 5 minutes "
      f"of each other. Screening already marks the JD for caching but it never caches: Haiku 4.5 only caches prompts of 4,096+ tokens "
      f"and a screening prompt is ~{drv[('recruitment.screening', 'claude-haiku-4-5')]['avg_in']:,}. Also record "
      f"`cache_read_input_tokens` / `cache_creation_input_tokens` in `ai_usage_records` - today only `input_tokens` is kept, which "
      f"leaves cached tokens out of the cost once caching is on.")
    w("")
    w("## 4. Amazon Bedrock vs Anthropic direct (list price, check)")
    w("")
    prem = A["bedrock_india_premium"]
    w(f"Same models, same token counts. Bedrock's global cross-region profile lists at the same per-token price as Anthropic; "
      f"the India geographic profile (Mumbai / Hyderabad, data stays in India) is noted in the app's price table as ~{_pct(prem)} higher. "
      f"**List price, check** against the AWS invoice / the Bedrock pricing page before quoting - and note sources disagree on whether "
      f"Sonnet 5's $2/$10 launch price still applies on either.")
    w("")
    w("| Unit | Anthropic direct | Bedrock global | Bedrock India (+" + _pct(prem) + ") | Sonnet at $3/$15 |")
    w("|---|---|---|---|---|")
    for name, v, alt in [("Resume", R, R), ("JD draft", JD, JD * sonnet_factor), ("HR-assistant question", Q, Q * sonnet_factor),
                         (f"Job ({A['applicants_per_job']} applicants)", job_typ, job_alt), ("Hire", hire_typ, hire_alt)]:
        w(f"| {name} | {_rs(v)} | {_rs(v)} | {_rs(v * (1 + prem))} | {_rs(alt)} |")
    w("")
    w("Batch processing (50% off on both) fits only work nobody waits for, e.g. a nightly re-screen of a whole job; "
      "the screens and agents answer people live, so the report does not count it.")
    w("")
    w("## 5. Draft pricing - DRAFT, for management (the owner decides)")
    w("")
    w("Three plans from the blueprint, each with the AI cost inside it and the AI margin at three price points. "
      "Margin here = (price - AI cost) / price; hosting, support, sales and GST still come out of it.")
    w("")
    lite_cost, lite_p90 = R, U["resume"]["u"]["inr"]["p90"]
    w(f"**Lite - per API call** (one call = one resume read + screened; AI cost {_rs(lite_cost)} median, {_rs(lite_p90)} p90)")
    w("")
    w("| Price per call | AI cost | AI margin (median) | AI margin (p90) |")
    w("|---|---|---|---|")
    for p in A["lite_prices"]:
        w(f"| Rs {p} | {_rs(lite_cost)} | {_pct((p - lite_cost) / p)} | {_pct((p - lite_p90) / p)} |")
    w("")
    w(f"**Pro - per active job per month, web app included** (AI cost {_rs(job_typ, 0)} typical, {_rs(job_heavy, 0)} heavy)")
    w("")
    w("| Price per job / month | AI margin (typical) | AI margin (heavy) |")
    w("|---|---|---|")
    for p in A["pro_prices"]:
        w(f"| Rs {p:,} | {_pct((p - job_typ) / p)} | {_pct((p - job_heavy) / p)} |")
    w("")
    w(f"**Enterprise - platform fee + per hire, on-prem** (AI cost {_rs(hire_typ, 0)} per hire typical, {_rs(hire_heavy, 0)} heavy; "
      f"platform fee e.g. Rs {A['enterprise_platform_fee']:,} / month for hosting and support, no AI inside it)")
    w("")
    w("| Price per hire | AI margin (typical) | AI margin (heavy) |")
    w("|---|---|---|")
    for p in A["enterprise_hire_prices"]:
        w(f"| Rs {p:,} | {_pct((p - hire_typ) / p)} | {_pct((p - hire_heavy) / p)} |")
    w("")
    w("On-prem customers can bring their own Anthropic or Bedrock key; the AI cost is then theirs and the per-hire price is margin "
      "before hosting and support.")
    w("")
    w("## 6. Assumptions and what was excluded")
    w("")
    ex = rep["excluded"]
    w(f"- **Recorded data**: {rec['calls']} AI calls ({_rs(rec['total_inr'])}) on this install, all from CTD's own development and proof "
      f"sessions - there is no customer production usage yet, so volumes are test volumes; the per-call token counts are real.")
    for reason, e in ex.items():
        w(f"- **Excluded - {reason}**: {e['calls']} calls ({_rs(e['inr'])}).")
    w(f"- **Controlled run (Gate A, 2026-11-25)**: real model, mail to Mailpit; 30 SYNTHETIC resumes (`docs/samples/gate_a/`, "
      f"204-576 words, median ~345 - real resumes are often longer, which raises reading cost roughly in proportion) against 3 jobs "
      f"(10 each), 3 JD drafts, 5 HR-assistant questions, 2 interview summaries, 2 BGV report readings: {ctl['calls']} calls, "
      f"{_rs(ctl['total_inr'])}. The test jobs, candidates, applications and files were deleted afterwards; the AI usage rows "
      f"were kept and tagged `gate-a-run`.")
    w("- **One shortcut in the run**: the Salary module is on, so BGV can only start after a salary approval that needs the candidate's "
      "form; the 2 BGV applications were set to `salary_approved` in the database. Everything else went through the real API.")
    w("- **Re-pricing**: every call is priced from its tokens with today's `ai.pricing` (rows recorded at Rs 0 before prices were set "
      "are included at today's price).")
    w("- **Questions and agent runs** are split from the call stream: a new question starts after a 45 s pause or when the assistant "
      "is called twice in a row. Agent calls carry no conversation id, so this is a rule, not a recorded link.")
    w(f"- **Typical job**: {A['applicants_per_job']} applicants, {A['interviews_per_job']} interviews, "
      f"{A['assistant_questions_per_job']} assistant questions, {A['hires_per_job']} hire. Heavy job: {A['heavy_applicants_per_job']} "
      f"applicants, {A['heavy_interviews_per_job']} interviews, {A['heavy_assistant_questions_per_job']} questions. Change them in "
      f"`scripts/gate_a_report.py` and re-run.")
    w("- **Hire journey** uses recorded agent runs (salary, offer, onboarding: 3 samples each - estimates) plus the measured BGV reading; "
      "it assumes one run of each agent per hire.")
    w("- **Not in any number**: the daily briefing (" + _rs(U["briefing"]["med"]) + " per briefing, a per-company cost, not per job), "
      "hosting, verification fees, e-mail/SMS, support.")
    w("- **Found during the run**: the HR assistant answered \"draft interview questions\" with \"no agent can do this\" although the "
      "app has an interview-kit feature - a product gap, not a cost item.")
    w("")
    md = "\n".join(lines) + "\n"

    # ---- Excel: the report's sheets + the model, cuts, Bedrock and pricing
    headline_rows = [["Per resume", round(R, 2), round(R / fx, 4), U["resume"]["u"]["samples"], "measured", "controlled run"],
                     [f"Per job ({A['applicants_per_job']} applicants)", round(job_typ, 2), round(job_typ / fx, 4), "-", "modelled", "measured units x assumptions"],
                     [f"Per hire ({A['hires_per_job']} per job)", round(hire_typ, 2), round(hire_typ / fx, 4), "-", "modelled", "measured units x assumptions"]]
    extra = [
        {"title": "Model (job, hire)", "header": ["Item", "Rs"],
         "rows": [[k, round(v, 2)] for k, v in job_parts.items()] + [["= per job (typical)", round(job_typ, 2)], ["per job (heavy)", round(job_heavy, 2)]]
         + [[k, round(v, 2)] for k, v in hire_journey_parts.items() if v] + [["= per hire (typical)", round(hire_typ, 2)], ["per hire (heavy)", round(hire_heavy, 2)],
                                                                            ["per job if Sonnet $3/$15", round(job_alt, 2)], ["per hire if Sonnet $3/$15", round(hire_alt, 2)]],
         "widths": {"Item": 44}},
        {"title": "Cost cuts", "header": ["Cut", "Saving per unit Rs", "Unit", "Saving per typical job Rs"],
         "rows": [["Haiku 5.5 for resume reading + matching", round(cut_model, 3), "resume", round(cut_model * A["applicants_per_job"], 2)],
                  ["Suitable-job check: top 1 instead of 3", round(cut_suit_top1, 3), "resume", round(cut_suit_top1 * A["applicants_per_job"], 2)],
                  ["Suitable-job check: skip when applied to a job", round(cut_suit, 3), "resume", round(cut_suit * A["applicants_per_job"], 2)],
                  ["Halve the reading prompt's fixed instructions", round(cut_parse_prompt, 3), "resume", round(cut_parse_prompt * A["applicants_per_job"], 2)],
                  ["Prompt caching for agents", round(cut_cache_q, 3), "question", round(cut_cache_q * A["assistant_questions_per_job"], 2)]],
         "widths": {"Cut": 46}},
        {"title": "Bedrock vs direct", "header": ["Unit", "Anthropic direct Rs", "Bedrock global Rs", f"Bedrock India +{_pct(prem)} Rs", "Sonnet $3/$15 Rs", "Note"],
         "rows": [[n, round(v, 2), round(v, 2), round(v * (1 + prem), 2), round(alt, 2), "list price, check"]
                  for n, v, alt in [("Resume", R, R), ("JD draft", JD, JD * sonnet_factor), ("HR-assistant question", Q, Q * sonnet_factor),
                                    ("Job", job_typ, job_alt), ("Hire", hire_typ, hire_alt)]]},
        {"title": "Pricing DRAFT", "header": ["Plan", "Price Rs", "Unit", "AI cost Rs (typical)", "AI margin typical", "AI cost Rs (p90 / heavy)", "AI margin p90 / heavy"],
         "rows": [["Lite", p, "API call", round(R, 2), round((p - R) / p, 3), round(lite_p90, 2), round((p - lite_p90) / p, 3)] for p in A["lite_prices"]]
         + [["Pro", p, "active job / month", round(job_typ, 2), round((p - job_typ) / p, 3), round(job_heavy, 2), round((p - job_heavy) / p, 3)] for p in A["pro_prices"]]
         + [["Enterprise", p, f"hire (+ platform fee Rs {A['enterprise_platform_fee']:,}/month)", round(hire_typ, 2), round((p - hire_typ) / p, 3),
             round(hire_heavy, 2), round((p - hire_heavy) / p, 3)] for p in A["enterprise_hire_prices"]],
         "widths": {"Unit": 40}},
        {"title": "Assumptions", "header": ["Assumption", "Value"], "rows": [[k, str(v)] for k, v in A.items()], "widths": {"Assumption": 36}},
    ]
    xlsx = to_xlsx(rep, title="Gate A - AI cost report (DRAFT pricing for management)", extra_sheets=extra, headline_rows=headline_rows,
                   notes=[headline, "Prices: Claude list prices - check before quoting. Pricing sheet is a DRAFT for management."])
    return md, xlsx, headline


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gate_a_report")
    parser.add_argument("--since", type=date.fromisoformat, required=True)
    parser.add_argument("--until", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    md, xlsx, headline = build(datetime.combine(args.since, time.min, tzinfo=timezone.utc), datetime.combine(args.until, time.max, tzinfo=timezone.utc))
    (ROOT / "docs" / "GATE_A_COST_REPORT.md").write_text(md, encoding="utf-8")
    (ROOT / "docs" / "reports").mkdir(exist_ok=True)
    (ROOT / "docs" / "reports" / "GATE_A_COST_REPORT.xlsx").write_bytes(xlsx)
    print(headline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
