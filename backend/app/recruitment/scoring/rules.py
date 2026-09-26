"""Part 17.5: presets, validation and the knock-out rules.

Weights are whole numbers 0-100 and the ENABLED factors must add up to exactly 100 (the
screen shows the total and offers "auto-balance"). Knock-outs are hard filters: a
knocked-out candidate is flagged and shown separately -- never deleted, never
auto-rejected, and never auto-shortlisted.
"""

import copy
from typing import Any, Optional

from app.recruitment.scoring.factors import FACTORS

KNOCKOUT_TYPES = ("must_have_skill", "max_notice_days", "location_in", "min_experience", "max_expected_salary")


def _preset(weights: dict[str, int]) -> dict:
    return {
        "factors": {key: {"enabled": key in weights, "weight": weights.get(key, 0), "params": {}} for key in FACTORS},
        "knockouts": [],
        "shortlist_threshold": None,  # None = the company setting
    }


PRESETS: dict[str, dict] = {
    "balanced": _preset({"skills_ai": 25, "must_have": 20, "nice_to_have": 5, "experience": 15, "domain": 5, "location": 10,
                         "notice": 5, "salary": 5, "education": 5, "certifications": 5}),
    "experience_first": _preset({"skills_ai": 15, "must_have": 15, "experience": 30, "domain": 20, "stability": 10, "recent_skills": 10}),
    "location_first": _preset({"skills_ai": 20, "must_have": 20, "experience": 15, "location": 35, "notice": 10}),
    "skills_first": _preset({"skills_ai": 30, "must_have": 30, "nice_to_have": 15, "certifications": 10, "recent_skills": 15}),
    "budget_first": _preset({"skills_ai": 20, "must_have": 20, "experience": 15, "salary": 35, "notice": 10}),
}
PRESET_NAMES = {"balanced": "Balanced", "experience_first": "Experience first", "location_first": "Location first",
                "skills_first": "Skills first", "budget_first": "Budget first"}
DEFAULT_PRESET = "balanced"


class RulesError(ValueError):
    pass


def normalise(rules: Optional[dict]) -> dict:
    """Fill in anything missing (new factors added later appear switched off)."""
    base = copy.deepcopy(PRESETS[DEFAULT_PRESET]) if not rules else {"factors": {}, "knockouts": [], "shortlist_threshold": None}
    rules = copy.deepcopy(rules or {})
    out = {"factors": {}, "knockouts": rules.get("knockouts", base["knockouts"]) or [], "shortlist_threshold": rules.get("shortlist_threshold")}
    given = rules.get("factors") or base["factors"]
    for key in FACTORS:
        f = given.get(key) or {"enabled": False, "weight": 0, "params": {}}
        out["factors"][key] = {"enabled": bool(f.get("enabled")), "weight": int(round(float(f.get("weight") or 0))), "params": dict(f.get("params") or {})}
    return out


def validate(rules: dict) -> dict:
    rules = normalise(rules)
    enabled = {k: f for k, f in rules["factors"].items() if f["enabled"]}
    if not enabled:
        raise RulesError("Switch on at least one factor.")
    for key, f in rules["factors"].items():
        if not 0 <= f["weight"] <= 100:
            raise RulesError(f"{FACTORS[key][1]}: weight must be between 0 and 100.")
    total = sum(f["weight"] for f in enabled.values())
    if total != 100:
        raise RulesError(f"The weights of the switched-on factors add up to {total}%. They must add up to 100% - use auto-balance.")
    if rules["factors"]["custom"]["enabled"] and not rules["factors"]["custom"]["params"].get("field"):
        raise RulesError("Custom field: choose which field to score.")
    t = rules.get("shortlist_threshold")
    if t is not None and not (0 <= int(t) <= 100):
        raise RulesError("Shortlist threshold must be between 0 and 100.")
    for k in rules["knockouts"]:
        if k.get("type") not in KNOCKOUT_TYPES:
            raise RulesError(f"Unknown knock-out rule: {k.get('type')}")
    return rules


def auto_balance(rules: dict) -> dict:
    """Scale the switched-on weights so they add up to exactly 100 (keeps their proportions)."""
    rules = normalise(rules)
    enabled = [k for k, f in rules["factors"].items() if f["enabled"]]
    if not enabled:
        return rules
    raw = [max(rules["factors"][k]["weight"], 0) for k in enabled]
    if sum(raw) == 0:
        raw = [1] * len(enabled)
    scaled = [w * 100 / sum(raw) for w in raw]
    whole = [int(s) for s in scaled]
    for i in sorted(range(len(enabled)), key=lambda i: scaled[i] - whole[i], reverse=True)[: 100 - sum(whole)]:
        whole[i] += 1
    for k, w in zip(enabled, whole):
        rules["factors"][k]["weight"] = w
    return rules


# ---------------------------------------------------------------- knock-outs

def evaluate_knockouts(knockouts: list[dict], facts: Any) -> list[dict]:
    """-> one row per rule: {type, label, passed, reason}. Missing data never knocks out."""
    from app.recruitment.scoring.factors import _coverage, _num

    out = []
    for k in knockouts or []:
        t = k.get("type")
        passed, reason, label = True, "", ""
        if t == "must_have_skill":
            skill = str(k.get("skill") or "").strip()
            label = f"Must have {skill}"
            cov, _m, missing = _coverage(facts.parsed, [skill]) if skill else (None, [], [])
            if skill and missing:
                passed, reason = False, f"{skill} not found in resume"
        elif t == "max_notice_days":
            days = _num(getattr(facts.candidate, "notice_period_days", None))
            limit = _num(k.get("days"))
            label = f"Notice {limit:g} days or less" if limit is not None else "Notice period"
            if days is not None and limit is not None and days > limit:
                passed, reason = False, f"notice is {days:g} days"
        elif t == "location_in":
            places = [str(p).strip() for p in k.get("places") or [] if str(p).strip()]
            label = f"Location in {', '.join(places)}" + (" or willing to relocate" if k.get("allow_relocation", True) else "")
            cand = facts.candidate_place
            if places and cand is not None:
                from app.platform.geo.service import offline

                wanted = [offline(p) for p in places]
                near = any(w is not None and abs(w.lat - cand.lat) < 0.35 and abs(w.lng - cand.lng) < 0.35 for w in wanted)
                relocate = k.get("allow_relocation", True) and bool(getattr(facts.candidate, "willing_to_relocate", False))
                if not near and not relocate:
                    passed, reason = False, f"lives in {cand.label.split(',')[0]}"
        elif t == "min_experience":
            years, need = _num(facts.parsed.get("total_experience_years")), _num(k.get("years"))
            label = f"At least {need:g} years" if need is not None else "Minimum experience"
            if years is not None and need is not None and years < need:
                passed, reason = False, f"has {years:g} years"
        elif t == "max_expected_salary":
            expected = _num(getattr(facts.candidate, "expected_ctc", None)) or _num(getattr(facts.application, "expected_salary", None))
            limit = _num(k.get("amount"))
            label = f"Expected salary at most {limit:,.0f}" if limit is not None else "Expected salary"
            if expected is not None and limit is not None and expected > limit:
                passed, reason = False, f"expects {expected:,.0f}"
        out.append({"type": t, "label": label, "passed": passed, "reason": reason})
    return out
