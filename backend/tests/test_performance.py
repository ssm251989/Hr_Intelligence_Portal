"""Performance, goals, calibration, compensation, succession (docs/HRMS_COMPLETE_SPEC.txt
Part 10). Covers this part's named TESTS: cycle eligibility, weightage calc, anonymity
enforcement, calibration audit, merit matrix, successor readiness -- plus goals/KPIs,
compensation apply idempotency and API coverage.

Written under the owner's testing-deferred directive (2026-09-25): not yet executed.
"""

from datetime import date, timedelta

import pytest

from app.core_hr import employees as employees_service
from app.core_hr import lifecycle
from app.models.core_hr import Position
from app.models.performance import CalibrationAudit, RatingScale, Review
from app.performance import calibration, compensation, goals, reviews, talent
from app.platform.tenancy.context import TENANT_1_ID, TenantContext

TENANT = TenantContext(tenant_id=TENANT_1_ID, slug="tenant1-test", isolation="dedicated_db")
PERIOD = (date(2026, 4, 1), date(2027, 3, 31))

STAGES = [{"stage": "self", "weight": 20}, {"stage": "manager", "weight": 60}, {"stage": "peer", "weight": 20}]
SECTIONS = [{"key": "goals", "weight": 70}, {"key": "competencies", "weight": 30}]


def _employee(db_session, *, grade="G1", manager_id=None, worker_type="employee", hired=date(2025, 1, 1), status="active"):
    employee = employees_service.create_employee(db_session, TENANT, first_name="E", status=status, worker_type=worker_type)
    lifecycle.apply_event(db_session, TENANT, employee_id=employee.id, event_type="hire", effective_from=hired,
                          changes={"grade": grade, "manager_employee_id": manager_id})
    return employee


def _scale(db_session) -> RatingScale:
    scale = RatingScale(tenant_id=TENANT.tenant_id, code="five", name="Five point", points_json=[{"value": v, "label": str(v)} for v in range(1, 6)])
    db_session.add(scale)
    db_session.commit()
    return scale


def _cycle(db_session, **kwargs):
    return reviews.create_cycle(
        db_session, TENANT, name="FY27", cycle_type="annual", period_start=PERIOD[0], period_end=PERIOD[1],
        stages=kwargs.pop("stages", STAGES), sections=kwargs.pop("sections", SECTIONS), rating_scale_id=_scale(db_session).id, **kwargs,
    )


# ---- goals ----


def test_cascade_cannot_go_upward(db_session):
    emp = _employee(db_session)
    individual = goals.create_goal(db_session, TENANT, title="Mine", owner_employee_id=emp.id, weightage=50)
    with pytest.raises(goals.GoalValidationError):
        goals.create_goal(db_session, TENANT, title="Company", level="company", parent_goal_id=individual.id)


def test_kpi_progress_increase_and_decrease():
    assert goals.kpi_progress({"metric": "revenue", "baseline": 0, "target": 200}, 50) == 25.0
    assert goals.kpi_progress({"metric": "attrition", "baseline": 20, "target": 10}, 15) == 50.0
    assert goals.kpi_progress({"metric": "x", "baseline": 0, "target": 10}, 50) == 100.0  # clamped


def test_weightage_validation(db_session):
    emp = _employee(db_session)
    goals.create_goal(db_session, TENANT, title="A", owner_employee_id=emp.id, weightage=60)
    assert goals.validate_weightage(db_session, TENANT, emp.id)["valid"] is False
    goals.create_goal(db_session, TENANT, title="B", owner_employee_id=emp.id, weightage=40)
    assert goals.validate_weightage(db_session, TENANT, emp.id)["valid"] is True


def test_integration_progress_updates_matching_goals(db_session):
    emp = _employee(db_session)
    goal = goals.create_goal(db_session, TENANT, title="Ship", owner_employee_id=emp.id, kpi={"metric": "stories", "target": 10}, external_ref="EPIC-1")
    goals.apply_integration_progress(db_session, TENANT, external_ref="EPIC-1", current_value=10)
    db_session.refresh(goal)
    assert float(goal.progress_pct) == 100.0 and goal.status == "completed"


# ---- cycle eligibility ----


def test_cycle_eligibility_rule(db_session):
    cycle = _cycle(db_session, eligibility_jsonlogic={"and": [{">=": [{"var": "tenure_days"}, 90]}, {"!=": [{"var": "worker_type"}, "intern"]}]})
    veteran = _employee(db_session, hired=date(2025, 1, 1))
    newbie = _employee(db_session, hired=PERIOD[1] - timedelta(days=30))
    intern = _employee(db_session, worker_type="intern")
    assert reviews.is_eligible(db_session, TENANT, cycle, veteran)
    assert not reviews.is_eligible(db_session, TENANT, cycle, newbie)
    assert not reviews.is_eligible(db_session, TENANT, cycle, intern)


def test_inactive_employee_never_eligible(db_session):
    cycle = _cycle(db_session)
    assert not reviews.is_eligible(db_session, TENANT, cycle, _employee(db_session, status="inactive"))


def test_launch_creates_self_and_manager_reviews_idempotently(db_session):
    manager = _employee(db_session)
    report = _employee(db_session, manager_id=manager.id)
    cycle = _cycle(db_session, eligibility_jsonlogic={"==": [{"var": "employee_id"}, str(report.id)]})
    first = reviews.launch_cycle(db_session, TENANT, cycle)
    second = reviews.launch_cycle(db_session, TENANT, cycle)
    assert first == {"eligible": 1, "reviews_created": 2}
    assert second["reviews_created"] == 0


# ---- weightage calc ----


def _submitted(db_session, cycle, employee, reviewer, stage, goals_score, competencies):
    review = Review(tenant_id=TENANT.tenant_id, cycle_id=cycle.id, employee_id=employee.id, reviewer_employee_id=reviewer.id, stage=stage)
    db_session.add(review)
    db_session.commit()
    return reviews.submit_review(db_session, TENANT, review, section_scores={"goals": goals_score, "competencies": competencies})


def test_weightage_calc_sections_and_stages(db_session):
    cycle = _cycle(db_session)
    cycle.status = "active"
    emp, mgr, peer = _employee(db_session), _employee(db_session), _employee(db_session)
    self_review = _submitted(db_session, cycle, emp, emp, "self", 5, 5)
    mgr_review = _submitted(db_session, cycle, emp, mgr, "manager", 3, 4)
    _submitted(db_session, cycle, emp, peer, "peer", 4, 4)
    assert float(self_review.overall_rating) == 5.0
    assert float(mgr_review.overall_rating) == pytest.approx(3.3)  # 3*0.7 + 4*0.3
    # final = 5*0.2 + 3.3*0.6 + 4*0.2
    assert reviews.compute_final_rating(db_session, TENANT, cycle, emp.id) == pytest.approx(3.78)


def test_goal_ratings_weighted_by_goal_weightage(db_session):
    emp = _employee(db_session)
    g1 = goals.create_goal(db_session, TENANT, title="A", owner_employee_id=emp.id, weightage=75)
    g2 = goals.create_goal(db_session, TENANT, title="B", owner_employee_id=emp.id, weightage=25)
    assert reviews.goals_section_score(db_session, TENANT, {str(g1.id): 4, str(g2.id): 2}) == 3.5


def test_rating_outside_scale_rejected(db_session):
    cycle = _cycle(db_session)
    cycle.status = "active"
    emp = _employee(db_session)
    review = Review(tenant_id=TENANT.tenant_id, cycle_id=cycle.id, employee_id=emp.id, reviewer_employee_id=emp.id, stage="self")
    db_session.add(review)
    db_session.commit()
    with pytest.raises(reviews.ReviewCycleError):
        reviews.submit_review(db_session, TENANT, review, section_scores={"goals": 9})


# ---- anonymity enforcement ----


def test_peer_reviews_withheld_below_threshold(db_session):
    cycle = _cycle(db_session, anonymity={"peer_anonymous": True, "min_peer_responses": 3})
    cycle.status = "active"
    emp = _employee(db_session)
    for _ in range(2):
        _submitted(db_session, cycle, emp, _employee(db_session), "peer", 4, 4)
    view = reviews.reviews_for_viewer(db_session, TENANT, cycle, emp.id, viewer="employee")
    assert view["peer"]["withheld"] is True and view["peer"]["reviews"] == []
    assert view["peer"]["count"] == 2


def test_peer_identity_stripped_at_threshold(db_session):
    cycle = _cycle(db_session, anonymity={"peer_anonymous": True, "min_peer_responses": 2})
    cycle.status = "active"
    emp = _employee(db_session)
    for _ in range(2):
        _submitted(db_session, cycle, emp, _employee(db_session), "peer", 4, 4)
    for viewer in ("employee", "manager", "hr"):
        peers = reviews.reviews_for_viewer(db_session, TENANT, cycle, emp.id, viewer=viewer)["peer"]["reviews"]
        assert len(peers) == 2
        assert all(p["reviewer_employee_id"] is None for p in peers)


def test_hr_sees_identity_only_when_cycle_allows(db_session):
    cycle = _cycle(db_session, anonymity={"peer_anonymous": True, "min_peer_responses": 1, "hr_sees_peer_identity": True})
    cycle.status = "active"
    emp, peer = _employee(db_session), _employee(db_session)
    _submitted(db_session, cycle, emp, peer, "peer", 4, 4)
    assert reviews.reviews_for_viewer(db_session, TENANT, cycle, emp.id, viewer="hr")["peer"]["reviews"][0]["reviewer_employee_id"] == str(peer.id)
    assert reviews.reviews_for_viewer(db_session, TENANT, cycle, emp.id, viewer="manager")["peer"]["reviews"][0]["reviewer_employee_id"] is None


def test_unsubmitted_reviews_never_visible(db_session):
    cycle = _cycle(db_session, anonymity={"min_peer_responses": 0})
    emp, mgr = _employee(db_session), _employee(db_session)
    db_session.add(Review(tenant_id=TENANT.tenant_id, cycle_id=cycle.id, employee_id=emp.id, reviewer_employee_id=mgr.id, stage="manager"))
    db_session.commit()
    assert reviews.reviews_for_viewer(db_session, TENANT, cycle, emp.id, viewer="employee")["reviews"] == []


def test_ai_draft_never_submits_and_flags_bias(db_session, monkeypatch):
    cycle = _cycle(db_session)
    emp = _employee(db_session)
    review = Review(tenant_id=TENANT.tenant_id, cycle_id=cycle.id, employee_id=emp.id, reviewer_employee_id=emp.id, stage="self")
    db_session.add(review)
    db_session.commit()
    from types import SimpleNamespace

    monkeypatch.setattr("app.platform.ai.governance.governed_complete", lambda *a, **k: SimpleNamespace(text="She can be abrasive in meetings but delivers."))
    review = reviews.draft_review_summary(db_session, TENANT, review)
    assert review.status == "pending"
    assert "abrasive" in review.ai_draft_json["bias_flags"]


# ---- calibration audit ----


def _calibration_session(db_session, **kwargs):
    cycle = _cycle(db_session)
    cycle.status = "active"
    mgr = _employee(db_session)
    emps = [_employee(db_session) for _ in range(4)]
    for emp, score in zip(emps, (5, 4, 3, 3)):
        _submitted(db_session, cycle, emp, mgr, "manager", score, score)
    return calibration.open_session(db_session, TENANT, cycle, name="Eng", **kwargs), emps


def test_calibration_adjust_writes_audit_and_requires_reason(db_session):
    session, _ = _calibration_session(db_session)
    entry = calibration.entries(db_session, TENANT, session)[0]
    with pytest.raises(calibration.CalibrationError):
        calibration.adjust(db_session, TENANT, entry, actor="hrbp", reason="", performance_rating=2)
    calibration.adjust(db_session, TENANT, entry, actor="hrbp", reason="peer-group comparison", performance_rating=2, potential_rating=3)
    trail = calibration.audit_trail(db_session, TENANT, entry)
    assert {t["field"] for t in trail} == {"performance_rating", "potential_rating"}
    assert all(t["actor"] == "hrbp" and t["reason"] == "peer-group comparison" for t in trail)
    assert float(entry.original_rating) != 2  # the pre-calibration rating is preserved


def test_calibration_no_op_move_not_audited(db_session):
    session, _ = _calibration_session(db_session)
    entry = calibration.entries(db_session, TENANT, session)[0]
    calibration.adjust(db_session, TENANT, entry, actor="hrbp", reason="same", performance_rating=float(entry.performance_rating))
    assert db_session.query(CalibrationAudit).filter(CalibrationAudit.entry_id == entry.id).count() == 0


def test_hard_distribution_blocks_finalize_soft_warns(db_session):
    session, _ = _calibration_session(db_session, distribution={"5": 10, "4": 20, "3": 70}, tolerance_pct=5, enforcement="hard")
    with pytest.raises(calibration.CalibrationError):
        calibration.finalize(db_session, TENANT, session, actor="hr")
    session.enforcement = "soft"
    result = calibration.finalize(db_session, TENANT, session, actor="hr")
    assert result["warnings"] and session.status == "finalized"


def test_nine_box_and_normalisation(db_session):
    session, _ = _calibration_session(db_session)
    for entry in calibration.entries(db_session, TENANT, session):
        calibration.adjust(db_session, TENANT, entry, actor="hr", reason="potential", potential_rating=3)
    grid = calibration.nine_box(db_session, TENANT, session)
    assert "3x3" in grid["boxes"] and grid["boxes"]["3x3"]["label"] == "Future leader"
    report = calibration.normalisation_report(db_session, TENANT, session)
    assert report["employees"] == 4 and report["changed"] == 0


# ---- merit matrix ----

CELLS = [
    {"rating_min": 1, "rating_max": 3, "compa_min": 0, "compa_max": 1, "pct_min": 2, "pct_max": 4},
    {"rating_min": 1, "rating_max": 3, "compa_min": 1, "compa_max": 2, "pct_min": 0, "pct_max": 2},
    {"rating_min": 3, "rating_max": 5, "compa_min": 0, "compa_max": 1, "pct_min": 8, "pct_max": 12},
    {"rating_min": 3, "rating_max": 5, "compa_min": 1, "compa_max": 2, "pct_min": 5, "pct_max": 8},
]


def test_merit_matrix_lookup(db_session):
    matrix = compensation.upsert_matrix(db_session, TENANT, code="fy27", name="FY27", cells=CELLS)
    assert compensation.merit_range(matrix, 4, 0.9) == (8, 12)
    assert compensation.merit_range(matrix, 4, 1.1) == (5, 8)
    assert compensation.merit_range(matrix, 2, 0.8) == (2, 4)
    assert compensation.merit_range(matrix, 5, 2) == (5, 8)  # top edges are inclusive
    assert compensation.merit_range(matrix, 4, 2.5) is None


def test_merit_matrix_rejects_overlap(db_session):
    with pytest.raises(compensation.CompensationError):
        compensation.upsert_matrix(db_session, TENANT, code="bad", name="Bad", cells=[CELLS[0], {**CELLS[0], "pct_min": 1}])


def test_worksheet_guideline_and_apply_is_idempotent(db_session):
    from app.models.performance import CompensationCycle, SalaryBand

    emp = _employee(db_session, grade="G3")
    db_session.add(SalaryBand(tenant_id=TENANT.tenant_id, grade="G3", currency="INR", min_amount=800000, mid_amount=1000000, max_amount=1200000))
    matrix = compensation.upsert_matrix(db_session, TENANT, code="fy27", name="FY27", cells=CELLS)
    compensation.record_compensation(db_session, TENANT, employee_id=emp.id, effective_from=date(2025, 1, 1), base_amount=900000, currency="INR")
    comp_cycle = CompensationCycle(tenant_id=TENANT.tenant_id, name="FY27 merit", effective_date=date(2027, 4, 1), currency="INR", merit_matrix_id=matrix.id)
    db_session.add(comp_cycle)
    db_session.commit()

    [proposal] = compensation.build_worksheet(db_session, TENANT, comp_cycle, [emp.id])
    assert float(proposal.compa_ratio) == 0.9 and proposal.rating is None  # no review cycle linked -> no guideline

    proposal.rating, proposal.guideline_min_pct, proposal.guideline_max_pct = 4, 8, 12
    compensation.update_proposal(proposal, merit_pct=15)
    with pytest.raises(compensation.CompensationError):
        compensation.submit_proposal(db_session, TENANT, proposal, actor="mgr")  # outside guideline, no justification
    compensation.update_proposal(proposal, justification="retention risk")
    compensation.submit_proposal(db_session, TENANT, proposal, actor="mgr")
    compensation.decide_proposal(db_session, TENANT, proposal, approve=True, actor="hr")
    first = compensation.apply_proposal(db_session, TENANT, proposal, actor="hr")
    second = compensation.apply_proposal(db_session, TENANT, proposal, actor="hr")
    assert first["new_base"] == 1035000.0
    assert second["already_applied"] is True and second["record_id"] == first["record_id"]
    assert float(compensation.current_compensation(db_session, TENANT, emp.id, as_of=date(2027, 4, 2)).base_amount) == 1035000.0
    assert float(compensation.current_compensation(db_session, TENANT, emp.id, as_of=date(2027, 3, 1)).base_amount) == 900000.0


# ---- successor readiness ----


def _position(db_session, critical=True) -> Position:
    position = Position(tenant_id=TENANT.tenant_id, code=f"P-{date.today().toordinal()}-{id(object())}", title="Head of Eng", is_critical=critical)
    db_session.add(position)
    db_session.commit()
    return position


def test_successor_readiness_coverage(db_session):
    position = _position(db_session)
    slate = talent.get_or_create_slate(db_session, TENANT, position.id)
    assert talent.slate_readiness(db_session, TENANT, slate)["coverage"] == "uncovered"
    later = _employee(db_session)
    talent.add_successor(db_session, TENANT, slate, employee_id=later.id, readiness="ready_1_2_years")
    assert talent.slate_readiness(db_session, TENANT, slate)["coverage"] == "at_risk"
    now = _employee(db_session)
    talent.add_successor(db_session, TENANT, slate, employee_id=now.id, readiness="ready_now", rank=2)
    result = talent.slate_readiness(db_session, TENANT, slate)
    assert result["coverage"] == "covered"
    assert result["successors"][0]["employee_id"] == str(now.id)  # ready-now sorts first regardless of rank


def test_successor_rejects_unknown_readiness(db_session):
    slate = talent.get_or_create_slate(db_session, TENANT, _position(db_session).id)
    with pytest.raises(talent.TalentError):
        talent.add_successor(db_session, TENANT, slate, employee_id=_employee(db_session).id, readiness="someday")


def test_manager_flight_risk_overrides_ai_estimate(db_session):
    profile = talent.get_or_create_profile(db_session, TENANT, _employee(db_session).id)
    talent.record_ai_flight_risk(db_session, profile, score=0.9, factors={"tenure": "short"})
    assert talent.effective_flight_risk(profile) == "high"
    talent.set_manager_flight_risk(db_session, profile, level="low", notes="just promoted")
    assert talent.effective_flight_risk(profile) == "low"


# ---- API ----


def test_api_cycle_create_and_preview(client):
    response = client.post("/api/v1/performance/cycles", json={
        "name": "API cycle", "cycle_type": "quarterly", "period_start": "2026-04-01", "period_end": "2026-06-30",
        "stages": [{"stage": "manager", "weight": 100}], "sections": [{"key": "goals", "weight": 100}],
    })
    assert response.status_code == 201
    preview = client.get(f"/api/v1/performance/cycles/{response.json()['id']}/eligibility-preview")
    assert preview.status_code == 200 and "eligible_count" in preview.json()


def test_api_me_endpoints_require_linked_employee(client):
    response = client.get("/api/v1/performance/me/feedback")
    assert response.status_code == 404  # admin test user has no employee record


def test_api_compensation_needs_permission(make_auth_headers, anonymous_client):
    headers = make_auth_headers(role="interviewer")
    assert anonymous_client.get("/api/v1/performance/compensation/salary-bands", headers=headers).status_code == 403
