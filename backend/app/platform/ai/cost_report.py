"""Part 33.1: the AI cost report - what the AI really costs per resume, JD, job, hire, exit,
assistant question and agent run, with min / median / p90 and the number of samples behind each.

Pure: plain rows in (`Call`, `Links`), a dict out, so it is tested with fixed rows. The loader
(`load_calls` / `load_links`) reads one company's rows through any SQLAlchemy connection or
session; scripts/ai_cost_report.py runs it for every company on the install, and the
"Export cost report" button (AI Intelligence > Usage) runs it for the signed-in company.

Every call is re-priced from its tokens with ONE price table (ai.pricing + ai.fx_rates), so
rows recorded before prices were set (cost 0) are counted at today's price, and USD / INR come
from the same numbers.

What a call is "for" (its subject): the usage row's entity (`ai_subject(...)`), else the AI
decision log's input refs (application_id, candidate_id, job_role_id, separation_id,
bgv_assignment_id -> its application).

Units:
- resume   : per candidate - reading + screening / ranking / shortlist feedback across their applications
- jd       : per JD draft (recruitment.jd_generation, or the job agent's draft = agents.job llm.judgment)
- job      : per job - everything on the job, its applications, and a candidate's resume reading
             shared across the jobs they applied to
- hire     : per hired application (application -> joined) - its own AI + its candidate's share + its BGV
- exit     : per separation - exit summary and anything else recorded for that separation
- question : per HR-assistant question (agents.hr_assistant + the specialist agent calls it made),
             and per policy question (copilot.chat, one call each)
- agent    : per agent run (agents.<name>): a run = the consecutive calls of that agent inside one question,
             or one call for a scheduled / judgment agent (briefing, bgv reader, interview summary, JD draft ...)

Excluded (and counted, so the report can say so): sandbox companies, rows tied to proof / test jobs.
Rows from the Gate A controlled run (module "gate-a-run") are reported apart, as source "controlled".
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

ESTIMATE_BELOW = 20  # fewer samples than this -> the number is an "estimate"
GATE_A_TAG = "gate-a-run"
QUESTION_GAP_S = 45  # a pause this long (or two assistant calls in a row) starts a new question

RESUME_FEATURES = frozenset({"recruitment.resume_parsing", "recruitment.screening", "recruitment.ranking", "recruitment.shortlist_feedback"})
JD_FEATURES = frozenset({"recruitment.jd_generation"})
ASSISTANT = "agents.hr_assistant"
POLICY_QA = "copilot.chat"
HIRED_STATUSES = frozenset({"onboarding_started", "onboarding_completed", "left_after_joining"})

PROOF_JOB = re.compile(r"(?i)^\s*(proof|sandbox|test|demo|dummy)\b|\(p\d{2}[a-z]?\)|\bp\d{2}[a-z]\b")
SANDBOX_COMPANY = re.compile(r"(?i)sandbox|demo|test")

UNIT_LABELS = {
    "resume": "Resume screened",
    "jd": "JD drafted",
    "job": "Job (all AI on the job)",
    "hire": "Hire (application to joined)",
    "exit": "Employee exit",
    "question": "HR-assistant question",
    "policy_question": "Policy question (Copilot)",
}


# ------------------------------------------------------------------ rows in


@dataclass(frozen=True)
class Call:
    id: str
    company: str
    feature: str
    model: Optional[str]
    input_tokens: int
    output_tokens: int
    created_at: datetime
    purpose: Optional[str] = None
    module: Optional[str] = None
    user_id: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    refs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AppLink:
    job_id: Optional[str]
    candidate_id: Optional[str]
    status: Optional[str]


@dataclass
class Links:
    """What the subjects point at, for one or more companies (ids are unique across them)."""
    applications: dict = field(default_factory=dict)  # app_id -> AppLink
    jobs: dict = field(default_factory=dict)  # job_id -> title
    bgv_assignments: dict = field(default_factory=dict)  # bgv_assignment_id -> app_id
    separations: set = field(default_factory=set)

    def merge(self, other: "Links") -> "Links":
        self.applications.update(other.applications)
        self.jobs.update(other.jobs)
        self.bgv_assignments.update(other.bgv_assignments)
        self.separations |= other.separations
        return self


# ------------------------------------------------------------------ prices


@dataclass(frozen=True)
class Prices:
    """`pricing` = ai.pricing ({model: {input_per_mtok, output_per_mtok, currency?}}); an entry with no
    currency is in `currency` (ai.currency). `fx` = ai.fx_rates ({X: units of ai.currency per 1 X})."""
    pricing: dict
    currency: str = "INR"
    fx: dict = field(default_factory=lambda: {"USD": 88})

    def _to_base(self, amount: Decimal, cur: str) -> Optional[Decimal]:
        cur, base = (cur or self.currency).upper(), self.currency.upper()
        if cur == base:
            return amount
        rate = (self.fx or {}).get(cur)
        return amount * Decimal(str(rate)) if rate else None

    def _from_base(self, amount: Decimal, cur: str) -> Optional[Decimal]:
        cur, base = cur.upper(), self.currency.upper()
        if cur == base:
            return amount
        rate = (self.fx or {}).get(cur)
        return amount / Decimal(str(rate)) if rate else None

    def cost(self, model: Optional[str], input_tokens: int, output_tokens: int) -> Optional[dict]:
        """{"usd", "inr"} for one call, or None when the model has no price (or no rate to convert)."""
        entry = (self.pricing or {}).get(model or "")
        if not entry:
            return None
        amount = (Decimal(str(entry.get("input_per_mtok") or 0)) * input_tokens
                  + Decimal(str(entry.get("output_per_mtok") or 0)) * output_tokens) / Decimal(1_000_000)
        base = self._to_base(amount, entry.get("currency") or self.currency)
        if base is None:
            return None
        usd, inr = self._from_base(base, "USD"), self._from_base(base, "INR")
        if usd is None or inr is None:
            return None
        return {"usd": float(usd), "inr": float(inr)}

    def usd_to_inr(self) -> Optional[float]:
        one = self._to_base(Decimal(1), "USD")
        inr = self._from_base(one, "INR") if one is not None else None
        return float(inr) if inr is not None else None


# ------------------------------------------------------------------ stats


def percentile(values: list, p: float) -> Optional[float]:
    """Linear interpolation between closest ranks (numpy's default)."""
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _r(x: Optional[float], nd: int = 4) -> Optional[float]:
    return None if x is None else round(x, nd)


class _Sample:
    """One unit of work (a resume, a job, a hire ...) and the calls / cost behind it."""
    __slots__ = ("usd", "inr", "calls", "tin", "tout", "models", "unpriced")

    def __init__(self):
        self.usd = self.inr = 0.0
        self.calls = self.tin = self.tout = self.unpriced = 0
        self.models: dict = defaultdict(int)

    def add(self, call: Call, price: Optional[dict], share: float = 1.0):
        self.calls += 1
        self.tin += call.input_tokens * share
        self.tout += call.output_tokens * share
        self.models[call.model or "?"] += 1
        if price is None:
            self.unpriced += 1
        else:
            self.usd += price["usd"] * share
            self.inr += price["inr"] * share


def summarise(samples: Iterable[_Sample]) -> dict:
    samples = list(samples)
    n = len(samples)
    inr = [s.inr for s in samples]
    usd = [s.usd for s in samples]
    models: dict = defaultdict(int)
    for s in samples:
        for m, c in s.models.items():
            models[m] += c
    out = {
        "samples": n,
        "estimate": n < ESTIMATE_BELOW,
        "calls": sum(s.calls for s in samples),
        "unpriced_calls": sum(s.unpriced for s in samples),
        "models": dict(sorted(models.items(), key=lambda kv: -kv[1])),
        "inr": {"min": _r(min(inr) if inr else None), "median": _r(percentile(inr, 0.5)), "p90": _r(percentile(inr, 0.9)),
                "avg": _r(sum(inr) / n if n else None), "total": _r(sum(inr))},
        "usd": {"min": _r(min(usd) if usd else None, 6), "median": _r(percentile(usd, 0.5), 6), "p90": _r(percentile(usd, 0.9), 6),
                "avg": _r(sum(usd) / n if n else None, 6), "total": _r(sum(usd), 6)},
        "calls_per_sample": _r(sum(s.calls for s in samples) / n, 2) if n else None,
        "tokens_in_median": _r(percentile([s.tin for s in samples], 0.5), 0),
        "tokens_out_median": _r(percentile([s.tout for s in samples], 0.5), 0),
    }
    return out


# ------------------------------------------------------------------ the report


def subject(call: Call, links: Links) -> tuple[Optional[str], Optional[str]]:
    """(entity_type, entity_id) the call was for, from the usage row or the decision log refs."""
    if call.entity_type and call.entity_id:
        return call.entity_type, str(call.entity_id)
    refs = call.refs or {}
    if refs.get("application_id"):
        return "application", str(refs["application_id"])
    if refs.get("bgv_assignment_id") and str(refs["bgv_assignment_id"]) in links.bgv_assignments:
        return "application", str(links.bgv_assignments[str(refs["bgv_assignment_id"])])
    if refs.get("candidate_id"):
        return "candidate", str(refs["candidate_id"])
    if refs.get("job_role_id") or refs.get("job_id"):
        return "job", str(refs.get("job_role_id") or refs.get("job_id"))
    if refs.get("separation_id"):
        return "separation", str(refs["separation_id"])
    if refs.get("entity_type") and refs.get("entity_id"):
        return str(refs["entity_type"]), str(refs["entity_id"])
    return None, None


def _jobs_of(subj: tuple, links: Links, apps_of_candidate: dict) -> list[tuple[str, float]]:
    """[(job_id, share)] a call belongs to."""
    kind, sid = subj
    if kind == "job":
        return [(sid, 1.0)]
    if kind == "application" and sid in links.applications and links.applications[sid].job_id:
        return [(links.applications[sid].job_id, 1.0)]
    if kind == "candidate" and apps_of_candidate.get(sid):
        apps = [a for a in apps_of_candidate[sid] if links.applications[a].job_id]
        return [(links.applications[a].job_id, 1.0 / len(apps)) for a in apps]
    return []


def exclusion_reason(call: Call, subj: tuple, links: Links, apps_of_candidate: dict, sandbox_companies: set) -> Optional[str]:
    if call.company in sandbox_companies:
        return "sandbox company"
    for job_id, _ in _jobs_of(subj, links, apps_of_candidate):
        if PROOF_JOB.search(links.jobs.get(job_id) or ""):
            return "proof / test job"
    return None


def segment_runs(calls: list[Call]) -> tuple[list[list[Call]], list[list[Call]]]:
    """Chat-agent calls (purpose llm.copilot, agents.*) -> (questions, runs).

    A question starts at an hr_assistant call that follows another hr_assistant call (the previous
    question's answer), or after a pause of QUESTION_GAP_S; the specialist calls in between belong
    to it. Specialist calls with no assistant around them (the agent used directly) form their own
    question. A run = consecutive calls of one agent inside a question."""
    streams: dict = defaultdict(list)
    for c in calls:
        streams[(c.company, c.user_id)].append(c)
    questions: list = []
    for stream in streams.values():
        stream.sort(key=lambda c: c.created_at)
        current: list = []
        for c in stream:
            prev = current[-1] if current else None
            gap = (c.created_at - prev.created_at).total_seconds() if prev else None
            # assistant after a specialist = that question's answer; assistant after assistant = the next question
            new = prev is None or gap >= QUESTION_GAP_S or (c.feature == ASSISTANT and prev.feature == ASSISTANT)
            if new and current:
                questions.append(current)
                current = []
            current.append(c)
        if current:
            questions.append(current)
    runs: list = []
    for q in questions:
        run: list = []
        for c in q:
            if run and c.feature != run[-1].feature:
                runs.append(run)
                run = []
            run.append(c)
        if run:
            runs.append(run)
    return questions, runs


def _is_chat_agent(c: Call) -> bool:
    return c.feature.startswith("agents.") and (c.purpose or "llm.copilot") == "llm.copilot" and c.feature != "agents.briefing"


def build(calls: Iterable[Call], links: Links, prices: Prices, *, sandbox_companies: Iterable[str] = (),
          since: Optional[datetime] = None, until: Optional[datetime] = None) -> dict:
    calls = list(calls)
    sandbox = set(sandbox_companies)
    apps_of_candidate: dict = defaultdict(list)
    for app_id, a in links.applications.items():
        if a.candidate_id:
            apps_of_candidate[a.candidate_id].append(app_id)

    excluded: dict = defaultdict(lambda: {"calls": 0, "inr": 0.0, "usd": 0.0})
    by_source: dict = {"recorded": [], "controlled": []}
    priced: dict = {}
    subjects: dict = {}
    unpriced_models: set = set()
    for c in calls:
        subj = subject(c, links)
        p = prices.cost(c.model, c.input_tokens, c.output_tokens)
        if p is None:
            unpriced_models.add(c.model or "?")
        priced[c.id], subjects[c.id] = p, subj
        if c.module == GATE_A_TAG:
            by_source["controlled"].append(c)
            continue
        reason = exclusion_reason(c, subj, links, apps_of_candidate, sandbox)
        if reason:
            e = excluded[reason]
            e["calls"] += 1
            e["inr"] += (p or {}).get("inr", 0.0)
            e["usd"] += (p or {}).get("usd", 0.0)
            continue
        by_source["recorded"].append(c)

    sources = {name: _units(rows, links, priced, subjects, apps_of_candidate) for name, rows in by_source.items()}
    return {
        "since": since.isoformat() if since else None,
        "until": until.isoformat() if until else None,
        "currency": prices.currency,
        "usd_to_inr": prices.usd_to_inr(),
        "pricing": prices.pricing,
        "estimate_below": ESTIMATE_BELOW,
        "companies": sorted({c.company for c in calls}),
        "sandbox_companies": sorted(sandbox),
        "calls_total": len(calls),
        "excluded": {k: {"calls": v["calls"], "inr": _r(v["inr"]), "usd": _r(v["usd"], 6)} for k, v in excluded.items()},
        "unpriced_models": sorted(unpriced_models),
        "sources": sources,
    }


def _units(calls: list[Call], links: Links, priced: dict, subjects: dict, apps_of_candidate: dict) -> dict:
    s = lambda: defaultdict(_Sample)  # noqa: E731
    resume, job, hire, exit_ = s(), s(), s(), s()
    jd: list = []
    policy: list = []
    judgment_runs: dict = defaultdict(list)
    chat = []
    drivers: dict = defaultdict(lambda: {"calls": 0, "tin": 0, "tout": 0, "inr": 0.0, "usd": 0.0, "unpriced": 0})
    total = _Sample()

    for c in calls:
        p, subj = priced[c.id], subjects[c.id]
        total.add(c, p)
        d = drivers[(c.feature, c.model or "?")]
        d["calls"] += 1
        d["tin"] += c.input_tokens
        d["tout"] += c.output_tokens
        if p:
            d["inr"] += p["inr"]
            d["usd"] += p["usd"]
        else:
            d["unpriced"] += 1
        kind, sid = subj

        # resume: per candidate
        if c.feature in RESUME_FEATURES:
            cand = sid if kind == "candidate" else (links.applications[sid].candidate_id if kind == "application" and sid in links.applications else None)
            if cand:
                resume[cand].add(c, p)
        # JD drafted: one call = one draft
        if c.feature in JD_FEATURES or (c.feature == "agents.job" and c.purpose == "llm.judgment"):
            one = _Sample()
            one.add(c, p)
            jd.append(one)
        # job
        for job_id, share in _jobs_of(subj, links, apps_of_candidate):
            job[job_id].add(c, p, share)
        # hire: the hired application's own calls, plus its candidate's share
        if kind == "application" and sid in links.applications and links.applications[sid].status in HIRED_STATUSES:
            hire[sid].add(c, p)
        elif kind == "candidate":
            hired = [a for a in apps_of_candidate.get(sid, []) if links.applications[a].status in HIRED_STATUSES]
            n_apps = len(apps_of_candidate.get(sid, [])) or 1
            for a in hired:
                hire[a].add(c, p, 1.0 / n_apps)
        # exit
        if kind == "separation":
            exit_[sid].add(c, p)
        # questions and agent runs
        if c.feature == POLICY_QA:
            one = _Sample()
            one.add(c, p)
            policy.append(one)
        elif _is_chat_agent(c):
            chat.append(c)
        elif c.feature.startswith("agents."):
            one = _Sample()
            one.add(c, p)
            judgment_runs[c.feature].append(one)

    questions, runs = segment_runs(chat)
    q_samples = []
    for q in questions:
        if not any(c.feature == ASSISTANT for c in q):
            continue  # a specialist agent used on its own - counted as an agent run, not a question
        one = _Sample()
        for c in q:
            one.add(c, priced[c.id])
        q_samples.append(one)
    agent_samples: dict = defaultdict(list)
    for run in runs:
        one = _Sample()
        for c in run:
            one.add(c, priced[c.id])
        agent_samples[run[0].feature].append(one)
    for feature, items in judgment_runs.items():
        agent_samples[feature].extend(items)

    units = {
        "resume": summarise(resume.values()),
        "jd": summarise(jd),
        "job": summarise(job.values()),
        "hire": summarise(hire.values()),
        "exit": summarise(exit_.values()),
        "question": summarise(q_samples),
        "policy_question": summarise(policy),
    }
    agents = {f: summarise(items) for f, items in sorted(agent_samples.items())}
    driver_rows = sorted(({"feature": f, "model": m, "calls": d["calls"], "tokens_in": d["tin"], "tokens_out": d["tout"],
                           "avg_in": round(d["tin"] / d["calls"]), "avg_out": round(d["tout"] / d["calls"]),
                           "inr": _r(d["inr"]), "usd": _r(d["usd"], 6), "unpriced_calls": d["unpriced"],
                           "inr_per_call": _r(d["inr"] / d["calls"])} for (f, m), d in drivers.items()), key=lambda r: -r["inr"])
    tot = summarise([total])
    return {
        "calls": len(calls),
        "total_inr": tot["inr"]["total"],
        "total_usd": tot["usd"]["total"],
        "units": units,
        "agents": agents,
        "drivers": driver_rows,
    }


def headline(report: dict, source: Optional[str] = None) -> dict:
    """The one-line answer: the median per resume / job / hire from the source with more samples
    for each unit (the controlled run where the recorded data is thin)."""
    out = {}
    for unit in ("resume", "job", "hire"):
        options = [(name, report["sources"][name]["units"][unit]) for name in ([source] if source else ("recorded", "controlled"))]
        options = [o for o in options if o[1]["samples"]]
        if not options:
            out[unit] = None
            continue
        name, u = max(options, key=lambda o: o[1]["samples"])
        out[unit] = {"inr": u["inr"]["median"], "usd": u["usd"]["median"], "samples": u["samples"], "estimate": u["estimate"], "source": name}
    return out


# ------------------------------------------------------------------ loading (one company)


def _jsonish(v: Any) -> dict:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        import json

        try:
            return json.loads(v)
        except ValueError:
            return {}
    return {}


def load_calls(conn, tenant_id, company: str, since: datetime, until: datetime) -> list[Call]:
    from sqlalchemy import text

    rows = conn.execute(text("""
        SELECT u.id, u.feature, u.purpose, u.module, u.model, u.input_tokens, u.output_tokens, u.created_at,
               u.user_id, u.entity_type, u.entity_id, d.input_refs_json
          FROM ai_usage_records u LEFT JOIN ai_decision_log d ON d.id = u.decision_log_id
         WHERE u.tenant_id = :t AND u.created_at >= :s AND u.created_at <= :u AND u.status = 'ok'
         ORDER BY u.created_at"""), {"t": str(tenant_id), "s": since, "u": until})
    return [Call(id=str(r.id), company=company, feature=r.feature, purpose=r.purpose, module=r.module, model=r.model,
                 input_tokens=int(r.input_tokens or 0), output_tokens=int(r.output_tokens or 0), created_at=r.created_at,
                 user_id=str(r.user_id) if r.user_id else None, entity_type=r.entity_type,
                 entity_id=str(r.entity_id) if r.entity_id else None, refs=_jsonish(r.input_refs_json))
            for r in rows]


def load_links(conn, tenant_id) -> Links:
    from sqlalchemy import text

    t = {"t": str(tenant_id)}
    links = Links()
    for r in conn.execute(text("SELECT id, job_role_id, candidate_id, status FROM applications WHERE tenant_id = :t"), t):
        links.applications[str(r.id)] = AppLink(str(r.job_role_id) if r.job_role_id else None, str(r.candidate_id) if r.candidate_id else None, r.status)
    for r in conn.execute(text("SELECT id, title FROM job_roles WHERE tenant_id = :t"), t):
        links.jobs[str(r.id)] = r.title
    for r in conn.execute(text("SELECT id, application_id FROM bgv_assignments WHERE tenant_id = :t"), t):
        links.bgv_assignments[str(r.id)] = str(r.application_id)
    for r in conn.execute(text("SELECT id FROM separations WHERE tenant_id = :t"), t):
        links.separations.add(str(r.id))
    return links


def load_prices(conn, tenant_id) -> Prices:
    """The company's ai.pricing / ai.currency / ai.fx_rates, falling back to the registered defaults."""
    from sqlalchemy import text

    from app.platform.settings.bootstrap_definitions import register_all
    from app.platform.settings.registry import get_definition

    register_all()
    values = {}
    for key in ("ai.pricing", "ai.currency", "ai.fx_rates"):
        row = conn.execute(text("SELECT value_json FROM setting_values WHERE tenant_id = :t AND key = :k AND scope_type = 'tenant' "
                                "ORDER BY version DESC LIMIT 1"), {"t": str(tenant_id), "k": key}).fetchone()
        values[key] = row[0] if row is not None else get_definition(key).default
    return Prices(pricing=values["ai.pricing"] or {}, currency=values["ai.currency"] or "INR", fx=values["ai.fx_rates"] or {})
