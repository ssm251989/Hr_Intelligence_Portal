"""Part 17.5: the scoring factors. Each factor looks at one thing about a candidate against
the job and returns a 0-100 score, the candidate's value in words, and evidence lines
from the resume. A factor whose data is unknown returns the neutral NEUTRAL score and says
so ("not given") -- never a silent 0.

Rules shape (stored as JSON, see rules.py):
  {"factors": {"<key>": {"enabled": bool, "weight": 0-100, "params": {...}}},
   "knockouts": [{"type": "...", ...}], "shortlist_threshold": int | null}
"""

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional

NEUTRAL = 50


@dataclass
class Facts:
    """Everything the factors read, gathered once per application (engine.gather)."""

    job: Any
    parsed: dict
    candidate: Any
    application: Any
    ai_match: Optional[float] = None  # the AI resume-to-job fit (applications.match_score)
    job_place: Any = None  # geo.Place of the job location
    candidate_place: Any = None  # geo.Place of the candidate location


@dataclass
class FactorResult:
    score: float
    value: str
    evidence: list[str] = field(default_factory=list)
    known: bool = True


# ---------------------------------------------------------------- helpers

def _num(v) -> Optional[float]:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _skills_tokens(parsed: dict) -> set[str]:
    from app.screening.service import _tokenize_all

    return _tokenize_all(parsed.get("skills")) | _tokenize_all(parsed.get("certificates"))


def _coverage(parsed: dict, wanted: Optional[list]) -> tuple[Optional[float], list[str], list[str]]:
    """(coverage 0-1 or None when the job lists nothing, matched, missing)."""
    from app.screening.service import _is_experience_years_requirement, _skill_coverage

    # "8+ years of experience" lines are scored by the experience factor, not as skills
    wanted = [w for w in (wanted or []) if w and str(w).strip() and not _is_experience_years_requirement(w)]
    if not wanted:
        return None, [], []
    cov, missing = _skill_coverage(_skills_tokens(parsed), wanted)
    matched = [w for w in wanted if w not in missing]
    return cov, matched, missing


def _parse_year_month(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    t = str(text).strip().lower()
    if t in ("present", "current", "now", "till date", "to date", "ongoing"):
        return date.today()
    m = re.search(r"(19|20)\d{2}", t)
    if not m:
        return None
    year = int(m.group(0))
    months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    month = next((v for k, v in months.items() if k in t), None)
    if month is None:
        mm = re.search(r"\b(0?[1-9]|1[0-2])[/-](19|20)\d{2}", t)
        month = int(mm.group(1)) if mm else 6
    return date(year, month, 1)


def _roles(parsed: dict) -> list[dict]:
    out = []
    for w in parsed.get("work_history") or []:
        start, end = _parse_year_month(w.get("start")), _parse_year_month(w.get("end")) or date.today()
        if start and end and end >= start:
            out.append({**w, "_start": start, "_end": end, "_years": (end - start).days / 365.25})
    return sorted(out, key=lambda r: r["_end"], reverse=True)


def _words(text: Optional[str]) -> set[str]:
    stop = {"and", "of", "the", "for", "in", "a", "an", "to", "with", "senior", "junior", "lead", "sr", "jr", "ii", "iii", "i"}
    return {w for w in re.findall(r"[a-z][a-z0-9+#.]{1,}", (text or "").lower()) if w not in stop}


def _bands(value: float, bands: list[dict], key: str) -> float:
    """First band whose `key` limit the value is within -> its score; beyond all -> last score."""
    for b in bands:
        if b.get(key) is None or value <= float(b[key]):
            return float(b["score"])
    return float(bands[-1]["score"]) if bands else NEUTRAL


def _haversine_km(a, b) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a.lat, a.lng, b.lat, b.lng))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


_EDU_LEVELS = [
    (4, ("phd", "ph.d", "doctor")),
    (3, ("master", "m.tech", "mtech", "m.e", "m.sc", "msc", "mba", "mca", "m.com", "pgdm", "post graduate", "pg ")),
    (2, ("bachelor", "b.tech", "btech", "b.e", "b.sc", "bsc", "bca", "b.com", "bcom", "bba", "b.a", "graduate", "engineering")),
    (1, ("diploma", "polytechnic", "iti")),
]
_JOB_LEVEL = {"Any": 0, "Diploma": 1, "Bachelor's": 2, "Master's": 3, "PhD": 4}


def _edu_level(text: str) -> int:
    t = f" {text.lower()} "
    for level, needles in _EDU_LEVELS:
        if any(n in t for n in needles):
            return level
    return 0


# ---------------------------------------------------------------- factors

def f_skills_ai(facts: Facts, p: dict) -> FactorResult:
    if facts.ai_match is None:
        return FactorResult(NEUTRAL, "AI check not run yet", known=False)
    return FactorResult(float(facts.ai_match), f"{round(facts.ai_match)}/100 fit to the job description")


def f_must_have(facts: Facts, p: dict) -> FactorResult:
    job = facts.job
    cov, matched, missing = _coverage(facts.parsed, (job.technical_skills_must_have or []) + (job.soft_skills_must_have or []))
    if cov is None:
        return FactorResult(100, "the job lists no must-have skills")
    ev = [f"Has: {', '.join(matched[:8])}"] if matched else []
    if missing:
        ev.append(f"Not found in resume: {', '.join(missing[:8])}")
    return FactorResult(round(cov * 100), f"{len(matched)} of {len(matched) + len(missing)} must-haves", ev)


def f_nice_to_have(facts: Facts, p: dict) -> FactorResult:
    job = facts.job
    cov, matched, missing = _coverage(facts.parsed, (job.technical_skills_good_to_have or []) + (job.soft_skills_good_to_have or []))
    if cov is None:
        return FactorResult(100, "the job lists no nice-to-have skills")
    ev = [f"Has: {', '.join(matched[:8])}"] if matched else []
    return FactorResult(round(cov * 100), f"{len(matched)} of {len(matched) + len(missing)} nice-to-haves", ev)


def f_experience(facts: Facts, p: dict) -> FactorResult:
    """0 below min, rising to 100 at ideal, 100 up to max, then gently lower (-8/yr)."""
    years = _num(facts.parsed.get("total_experience_years"))
    lo = _num(p.get("min")) if p.get("min") is not None else _num(facts.job.experience_min_years)
    hi = _num(p.get("max")) if p.get("max") is not None else _num(facts.job.experience_max_years)
    ideal = _num(p.get("ideal"))
    if ideal is None:
        ideal = (lo + hi) / 2 if lo is not None and hi is not None else lo if lo is not None else hi
    if years is None:
        return FactorResult(NEUTRAL, "years not found in resume", known=False)
    value = f"{years:g} years"
    if lo is None and hi is None and ideal is None:
        return FactorResult(100, value + " (the job sets no range)")
    lo = lo if lo is not None else 0.0
    ideal = max(ideal if ideal is not None else lo, lo)
    if years < lo:
        return FactorResult(0, value + f" (below the minimum of {lo:g})")
    if years < ideal:
        span = max(ideal - lo, 0.5)
        return FactorResult(round(60 + 40 * (years - lo) / span), value + f" (ideal is {ideal:g})")
    if hi is None or years <= hi:
        return FactorResult(100, value)
    over = years - hi
    return FactorResult(max(40, round(100 - 8 * over)), value + f" ({over:g} above the maximum of {hi:g})")


def f_domain(facts: Facts, p: dict) -> FactorResult:
    """Years in roles whose titles share words with this job's title / department / the
    domain keywords, against `years_for_full` (default = job minimum, else 3)."""
    roles = _roles(facts.parsed)
    if not roles:
        return FactorResult(NEUTRAL, "no work history in resume", known=False)
    keys = _words(facts.job.title) | _words(facts.job.department) | {w.lower() for w in p.get("keywords") or []}
    relevant = [r for r in roles if keys & _words(r.get("title"))]
    years = sum(r["_years"] for r in relevant)
    full = _num(p.get("years_for_full")) or _num(facts.job.experience_min_years) or 3.0
    ev = [f"{r.get('title')} at {r.get('company')}" for r in relevant[:4]]
    return FactorResult(min(100, round(100 * years / max(full, 0.5))), f"{years:.1f} years in similar roles", ev)


def f_location(facts: Facts, p: dict) -> FactorResult:
    job_p, cand_p = facts.job_place, facts.candidate_place
    relocate = bool(getattr(facts.candidate, "willing_to_relocate", False))
    if job_p is None:
        return FactorResult(100, "the job has no fixed location")
    if cand_p is None:
        if relocate:
            return FactorResult(float(p.get("relocation_score", 70)), "location unknown, willing to relocate")
        return FactorResult(NEUTRAL, "candidate location not found", known=False)
    km = _haversine_km(job_p, cand_p)
    bands = p.get("km_bands") or [{"km": 25, "score": 100}, {"km": 100, "score": 75}, {"km": 300, "score": 45}, {"km": None, "score": 15}]
    score = _bands(km, bands, "km")
    if relocate:
        score = max(score, float(p.get("relocation_score", 70)))
    where = cand_p.label.split(",")[0]
    return FactorResult(score, f"{where}, about {round(km)} km from the job" + (" - willing to relocate" if relocate else ""))


def f_notice(facts: Facts, p: dict) -> FactorResult:
    days = _num(getattr(facts.candidate, "notice_period_days", None))
    if days is None:
        return FactorResult(NEUTRAL, "notice period not given", known=False)
    bands = p.get("day_bands") or [{"days": 15, "score": 100}, {"days": 30, "score": 90}, {"days": 60, "score": 70}, {"days": 90, "score": 40}, {"days": None, "score": 10}]
    return FactorResult(_bands(days, bands, "days"), f"{days:g} days notice")


def f_salary(facts: Facts, p: dict) -> FactorResult:
    expected = _num(getattr(facts.candidate, "expected_ctc", None)) or _num(getattr(facts.application, "expected_salary", None))
    lo, hi = _num(facts.job.salary_band_min), _num(facts.job.salary_band_max)
    if hi is None:
        return FactorResult(100, "the job has no salary band")
    if expected is None:
        return FactorResult(NEUTRAL, "expected salary not given", known=False)
    if expected <= hi:
        return FactorResult(100, f"expects {expected:,.0f} - within the band" + (f" ({lo:,.0f}-{hi:,.0f})" if lo else ""))
    over = 100 * (expected - hi) / hi
    bands = p.get("over_pct_bands") or [{"pct": 10, "score": 60}, {"pct": 20, "score": 30}, {"pct": None, "score": 0}]
    return FactorResult(_bands(over, bands, "pct"), f"expects {expected:,.0f} - {over:.0f}% above the band")


def f_education(facts: Facts, p: dict) -> FactorResult:
    need = _JOB_LEVEL.get(p.get("level") or facts.job.education_degree_level or "Any", 0)
    degrees = [e.get("degree") or "" for e in facts.parsed.get("education") or []]
    have = max((_edu_level(d) for d in degrees), default=0)
    if need == 0:
        return FactorResult(100, "the job needs no particular degree")
    if not degrees:
        return FactorResult(NEUTRAL, "education not found in resume", known=False)
    field_ok = True
    wanted_field = (p.get("field") or facts.job.education_field or "").strip().lower()
    if wanted_field and wanted_field not in ("any", ""):
        field_ok = any(w in " ".join(degrees).lower() for w in _words(wanted_field))
    score = 100 if have >= need else 55 if have == need - 1 else 20
    if not field_ok:
        score = min(score, 70)
    return FactorResult(score, ", ".join(d for d in degrees if d)[:120] or "degree not clear", [d for d in degrees if d][:3])


def f_certifications(facts: Facts, p: dict) -> FactorResult:
    wanted = p.get("list") or facts.job.preferred_certifications or []
    if not wanted:
        return FactorResult(100, "the job lists no certifications")
    from app.screening.service import _skill_coverage, _tokenize_all

    cov, missing = _skill_coverage(_tokenize_all(facts.parsed.get("certificates")), wanted)
    have = [w for w in wanted if w not in missing]
    return FactorResult(round(cov * 100), f"{len(have)} of {len(wanted)} certifications", [f"Has: {', '.join(have)}"] if have else [])


def f_stability(facts: Facts, p: dict) -> FactorResult:
    roles = [r for r in _roles(facts.parsed) if r["_years"] > 0.05]
    if len(roles) < 2:
        return FactorResult(NEUTRAL if not roles else 80, "not enough jobs to judge" if not roles else "one job so far", known=bool(roles))
    avg = sum(r["_years"] for r in roles) / len(roles)
    bands = p.get("year_bands") or [{"years": 1, "score": 25}, {"years": 2, "score": 55}, {"years": 3, "score": 80}, {"years": None, "score": 100}]
    score = 100.0
    for b in bands:
        if b.get("years") is None or avg < float(b["years"]):
            score = float(b["score"])
            break
    return FactorResult(score, f"stays {avg:.1f} years per job on average ({len(roles)} jobs)")


def f_recent_skills(facts: Facts, p: dict) -> FactorResult:
    """Must-have skills the candidate has, weighted by how recently they worked: the latest
    job ended within 12 months = full credit, within 36 = 60%, older = 30%."""
    job = facts.job
    cov, matched, _missing = _coverage(facts.parsed, p.get("skills") or job.technical_skills_must_have)
    roles = _roles(facts.parsed)
    if cov is None:
        return FactorResult(100, "the job lists no key skills")
    if not roles:
        return FactorResult(round(cov * 100 * 0.6), "work dates not found - counted as not recent", known=False)
    months = (date.today() - roles[0]["_end"]).days / 30.4
    recency = 1.0 if months <= 12 else 0.6 if months <= 36 else 0.3
    when = "working now" if months < 1 else f"last job ended {round(months)} months ago"
    return FactorResult(round(cov * 100 * recency), f"{len(matched)} key skills, {when}", [f"Latest: {roles[0].get('title')} at {roles[0].get('company')}"])


def f_languages(facts: Facts, p: dict) -> FactorResult:
    wanted = [w.strip().lower() for w in p.get("list") or [] if str(w).strip()]
    if not wanted:
        return FactorResult(100, "no languages required")
    have = {str(x).strip().lower() for x in (getattr(facts.candidate, "languages", None) or facts.parsed.get("languages") or [])}
    if not have:
        return FactorResult(NEUTRAL, "languages not given", known=False)
    got = [w for w in wanted if w in have]
    return FactorResult(round(100 * len(got) / len(wanted)), f"speaks {len(got)} of {len(wanted)}: {', '.join(got) or 'none'}")


def f_custom(facts: Facts, p: dict) -> FactorResult:
    code = p.get("field")
    if not code:
        return FactorResult(100, "no field chosen")
    value = (getattr(facts.candidate, "custom_fields", None) or {}).get(code)
    if value in (None, ""):
        return FactorResult(NEUTRAL, f"{code} not filled in", known=False)
    if p.get("kind") == "yes_no":
        yes = str(value).strip().lower() in ("true", "yes", "1", "y")
        want = p.get("want", True)
        return FactorResult(100 if yes == bool(want) else 0, "yes" if yes else "no")
    n, lo, hi = _num(value), _num(p.get("min")), _num(p.get("max"))
    if n is None:
        return FactorResult(NEUTRAL, str(value), known=False)
    if lo is not None and hi is not None and hi > lo:
        return FactorResult(round(100 * min(1, max(0, (n - lo) / (hi - lo)))), f"{n:g}")
    return FactorResult(100 if (lo is None or n >= lo) else 0, f"{n:g}")


# key -> (function, plain name). Order = order shown on screen.
FACTORS: dict[str, tuple[Callable[[Facts, dict], FactorResult], str]] = {
    "skills_ai": (f_skills_ai, "Skills match (AI)"),
    "must_have": (f_must_have, "Must-have skills"),
    "nice_to_have": (f_nice_to_have, "Nice-to-have skills"),
    "experience": (f_experience, "Years of experience"),
    "domain": (f_domain, "Experience in similar roles"),
    "location": (f_location, "Location / distance to office"),
    "notice": (f_notice, "Notice period"),
    "salary": (f_salary, "Expected salary vs band"),
    "education": (f_education, "Education level"),
    "certifications": (f_certifications, "Certifications"),
    "stability": (f_stability, "Job stability"),
    "recent_skills": (f_recent_skills, "Recent use of key skills"),
    "languages": (f_languages, "Languages"),
    "custom": (f_custom, "Custom field"),
}
