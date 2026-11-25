"""Part 33: the AI cost report (app/platform/ai/cost_report.py) - pure functions with fixed rows."""

from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.platform.ai import cost_report as cr
from app.platform.ai.cost_report_xlsx import to_xlsx

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
# Sonnet $2 / $10, Haiku $1 / $5 per million tokens; 1 USD = Rs 88 (the shipped defaults)
PRICES = cr.Prices(pricing={"sonnet": {"input_per_mtok": 2, "output_per_mtok": 10, "currency": "USD"},
                            "haiku": {"input_per_mtok": 1, "output_per_mtok": 5, "currency": "USD"}},
                   currency="INR", fx={"USD": 88})

_n = iter(range(10_000))


def call(feature, *, model="haiku", tin=1_000_000, tout=0, at=0, company="acme", purpose=None, module=None, user=None,
         entity=None, refs=None):
    et, eid = entity if entity else (None, None)
    return cr.Call(id=str(next(_n)), company=company, feature=feature, model=model, input_tokens=tin, output_tokens=tout,
                   created_at=T0 + timedelta(seconds=at), purpose=purpose, module=module, user_id=user,
                   entity_type=et, entity_id=eid, refs=refs or {})


def links():
    return cr.Links(
        applications={"a1": cr.AppLink("j1", "c1", "onboarding_completed"), "a2": cr.AppLink("j2", "c1", "screened"),
                      "a3": cr.AppLink("j1", "c2", "screened"), "ap": cr.AppLink("jp", "c3", "onboarding_completed")},
        jobs={"j1": "Backend Developer", "j2": "Data Analyst", "jp": "Proof Backend Engineer P30B"},
        bgv_assignments={"b1": "a1"}, separations={"s1"})


def recorded(report):
    return report["sources"]["recorded"]


# ---------------------------------------------------------------- prices and stats


def test_price_in_usd_and_inr():
    assert PRICES.cost("haiku", 1_000_000, 0) == {"usd": 1.0, "inr": 88.0}
    assert PRICES.cost("sonnet", 0, 100_000) == {"usd": 1.0, "inr": 88.0}
    assert PRICES.cost("unknown", 10, 10) is None
    assert PRICES.usd_to_inr() == 88.0


def test_price_given_in_ai_currency_converts_to_usd():
    p = cr.Prices(pricing={"m": {"input_per_mtok": 176}}, currency="INR", fx={"USD": 88})  # no currency = INR
    assert p.cost("m", 1_000_000, 0) == {"usd": 2.0, "inr": 176.0}


def test_percentiles():
    assert cr.percentile([], 0.5) is None
    assert cr.percentile([5], 0.9) == 5
    assert cr.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert cr.percentile(list(range(1, 11)), 0.9) == pytest.approx(9.1)


def test_estimate_below_20_samples():
    rows = [call("copilot.chat", at=i * 100) for i in range(19)]
    assert recorded(cr.build(rows, cr.Links(), PRICES))["units"]["policy_question"]["estimate"] is True
    rows.append(call("copilot.chat", at=5000))
    u = recorded(cr.build(rows, cr.Links(), PRICES))["units"]["policy_question"]
    assert u["samples"] == 20 and u["estimate"] is False


# ---------------------------------------------------------------- units


def test_resume_is_per_candidate_across_reading_and_screening():
    rows = [call("recruitment.resume_parsing", entity=("candidate", "c1")),  # Rs 88
            call("recruitment.screening", tin=500_000, entity=("application", "a1")),  # Rs 44
            call("recruitment.screening", tin=500_000, entity=("application", "a2")),  # Rs 44
            call("recruitment.resume_parsing", tin=250_000, entity=("candidate", "c2"))]  # Rs 22
    u = recorded(cr.build(rows, links(), PRICES))["units"]["resume"]
    assert u["samples"] == 2
    assert u["inr"]["min"] == 22.0 and u["inr"]["total"] == 198.0
    assert u["calls"] == 4


def test_job_shares_a_candidates_reading_across_their_jobs():
    rows = [call("recruitment.resume_parsing", entity=("candidate", "c1")),  # Rs 88 -> j1 44, j2 44
            call("recruitment.jd_generation", model="sonnet", tin=0, tout=100_000, entity=("job", "j1"))]  # Rs 88 on j1
    report = cr.build(rows, links(), PRICES)
    u = recorded(report)["units"]["job"]
    assert u["samples"] == 2
    assert u["inr"]["min"] == 44.0 and u["inr"]["total"] == 176.0
    jd = recorded(report)["units"]["jd"]
    assert jd["samples"] == 1 and jd["inr"]["median"] == 88.0 and jd["models"] == {"sonnet": 1}


def test_job_agent_draft_counts_as_a_jd_and_its_ref_finds_the_job():
    rows = [call("agents.job", model="sonnet", purpose="llm.judgment", tin=0, tout=50_000, refs={"job_role_id": "j2"})]
    r = recorded(cr.build(rows, links(), PRICES))
    assert r["units"]["jd"]["samples"] == 1
    assert r["units"]["job"]["samples"] == 1 and r["units"]["job"]["inr"]["median"] == 44.0
    assert r["agents"]["agents.job"]["samples"] == 1


def test_hire_is_the_hired_applications_journey():
    rows = [call("recruitment.resume_parsing", entity=("candidate", "c1")),  # c1 has 2 applications -> half (Rs 44) to hire a1
            call("recruitment.document_check", tin=500_000, entity=("application", "a1")),  # Rs 44
            call("agents.bgv_reader", model="sonnet", purpose="llm.judgment", tin=0, tout=50_000, refs={"bgv_assignment_id": "b1"}),  # Rs 44
            call("recruitment.screening", entity=("application", "a3"))]  # not hired
    u = recorded(cr.build(rows, links(), PRICES))["units"]["hire"]
    assert u["samples"] == 1
    assert u["inr"]["median"] == 132.0
    assert u["calls"] == 3


def test_exit_is_per_separation():
    rows = [call("separation.exit_summary", model="sonnet", tin=0, tout=100_000, refs={"separation_id": "s1"}),
            call("separation.exit_summary", model="sonnet", tin=0, tout=50_000, refs={"separation_id": "s1"})]
    u = recorded(cr.build(rows, links(), PRICES))["units"]["exit"]
    assert u["samples"] == 1 and u["inr"]["median"] == 132.0 and u["calls"] == 2


# ---------------------------------------------------------------- questions and agent runs


def test_assistant_questions_and_agent_runs_are_split_from_the_call_stream():
    a, chat = "agents.hr_assistant", "llm.copilot"
    rows = [
        # question 1: assistant -> job agent x2 -> assistant answer
        call(a, purpose=chat, at=0), call("agents.job", purpose=chat, at=3), call("agents.job", purpose=chat, at=6), call(a, purpose=chat, at=9),
        # question 2 starts with an assistant call straight after the answer
        call(a, purpose=chat, at=20), call("agents.salary", purpose=chat, at=23), call(a, purpose=chat, at=26),
        # question 3 after a long pause, answered directly
        call(a, purpose=chat, at=200),
        # the screening agent used on its own (no assistant): an agent run, not an assistant question
        call("agents.screening", purpose=chat, at=900), call("agents.screening", purpose=chat, at=902),
    ]
    r = recorded(cr.build(rows, cr.Links(), PRICES))
    q = r["units"]["question"]
    assert q["samples"] == 3 and q["calls"] == 8
    assert q["inr"]["min"] == 88.0 and q["inr"]["p90"] == pytest.approx(352 - 0.2 * 88)  # 4, 3, 1 calls x Rs 88
    assert r["agents"]["agents.job"]["samples"] == 1 and r["agents"]["agents.job"]["calls"] == 2
    assert r["agents"]["agents.salary"]["samples"] == 1
    assert r["agents"]["agents.screening"]["samples"] == 1 and r["agents"]["agents.screening"]["calls"] == 2


def test_different_users_are_separate_streams():
    a, chat = "agents.hr_assistant", "llm.copilot"
    rows = [call(a, purpose=chat, at=0, user="u1"), call(a, purpose=chat, at=1, user="u2"),
            call("agents.job", purpose=chat, at=2, user="u1"), call(a, purpose=chat, at=3, user="u1")]
    q = recorded(cr.build(rows, cr.Links(), PRICES))["units"]["question"]
    assert q["samples"] == 2  # u1: one question of 3 calls; u2: one of 1


def test_briefing_and_judgment_agents_are_one_run_per_call():
    rows = [call("agents.briefing", model="sonnet", purpose="llm.copilot", at=i) for i in range(3)]
    r = recorded(cr.build(rows, cr.Links(), PRICES))
    assert r["agents"]["agents.briefing"]["samples"] == 3
    assert r["units"]["question"]["samples"] == 0


# ---------------------------------------------------------------- exclusions, sources, headline


def test_sandbox_company_and_proof_jobs_are_excluded_and_counted():
    rows = [call("recruitment.screening", company="acme-sandbox", entity=("application", "a1")),
            call("recruitment.screening", entity=("application", "ap")),  # proof job
            call("recruitment.screening", entity=("application", "a3"))]
    report = cr.build(rows, links(), PRICES, sandbox_companies={"acme-sandbox"})
    assert report["excluded"]["sandbox company"] == {"calls": 1, "inr": 88.0, "usd": 1.0}
    assert report["excluded"]["proof / test job"]["calls"] == 1
    assert recorded(report)["calls"] == 1


@pytest.mark.parametrize("title,proof", [("Proof Backend Engineer P30B", True), ("Proof Platform Engineer (P30C)", True),
                                         ("Sandbox Python Developer", True), ("Test job", True),
                                         ("Junior AI Developer", False), ("Senior Python Developer", False), ("Product Manager", False)])
def test_proof_job_titles(title, proof):
    assert bool(cr.PROOF_JOB.search(title)) is proof


def test_gate_a_rows_are_a_separate_source():
    rows = [call("copilot.chat", module=cr.GATE_A_TAG), call("copilot.chat")]
    report = cr.build(rows, cr.Links(), PRICES)
    assert report["sources"]["controlled"]["calls"] == 1
    assert recorded(report)["calls"] == 1


def test_unpriced_model_is_counted_not_hidden():
    report = cr.build([call("copilot.chat", model="mystery")], cr.Links(), PRICES)
    assert report["unpriced_models"] == ["mystery"]
    assert recorded(report)["units"]["policy_question"]["unpriced_calls"] == 1


def test_headline_takes_the_source_with_more_samples():
    rows = [call("recruitment.resume_parsing", entity=("candidate", "c1"))]
    rows += [call("recruitment.resume_parsing", tin=500_000, module=cr.GATE_A_TAG, entity=("candidate", f"g{i}")) for i in range(3)]
    h = cr.headline(cr.build(rows, links(), PRICES))
    assert h["resume"]["source"] == "controlled" and h["resume"]["inr"] == 44.0 and h["resume"]["samples"] == 3
    assert h["hire"]["source"] == "recorded"
    assert h["job"]["source"] == "recorded"


def test_no_usage_gives_empty_numbers():
    report = cr.build([], cr.Links(), PRICES)
    u = recorded(report)["units"]["resume"]
    assert u["samples"] == 0 and u["inr"]["median"] is None
    assert cr.headline(report) == {"resume": None, "job": None, "hire": None}


def test_excel_has_the_sheets_and_numbers():
    rows = [call("recruitment.resume_parsing", entity=("candidate", "c1")), call("separation.exit_summary", refs={"separation_id": "s1"})]
    data = to_xlsx(cr.build(rows, links(), PRICES), extra_sheets=[{"title": "Pricing", "header": ["Plan"], "rows": [["Lite"]]}])
    wb = load_workbook(BytesIO(data))
    assert wb.sheetnames == ["Summary", "Per unit", "Per agent run", "Cost drivers", "Pricing"]
    units = {(r[0], r[1]): r for r in wb["Per unit"].iter_rows(min_row=2, values_only=True)}
    assert units[("Resume screened", "recorded")][4] == 88.0
    assert units[("Employee exit", "recorded")][3] == "estimate"
