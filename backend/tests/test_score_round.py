"""A1 (Part 27): the list showed 97% and Remarks "Match score 96/100" for one row (Python round() is half-to-even)."""

from app.recruitment.scoring import score_round


def test_match_score_rounds_half_up_like_the_screens():
    assert score_round(96.5) == 97  # round() gives 96; the list's Math.round gives 97
    assert score_round(97.5) == 98
    assert score_round(96.49) == 96
    assert score_round(None) == 0


def test_remarks_use_the_same_rounding():
    import inspect

    from app.screening import service

    src = inspect.getsource(service)
    assert "Match score {round(" not in src and "Match score {score_round(composite)}" in src


def test_years_in_similar_roles_never_exceed_total_experience():
    """P4 (Part 27): overlapping roles were added up - "7.0 years in similar roles" with 5 years in total."""
    from types import SimpleNamespace

    from app.recruitment.scoring.factors import Facts, f_domain

    parsed = {"total_experience_years": 5, "work_history": [
        {"title": "Data Engineer", "company": "A", "start": "2021-01", "end": "2026-01"},
        {"title": "Data Engineer (part time)", "company": "B", "start": "2022-01", "end": "2024-01"},
    ]}
    job = SimpleNamespace(title="Data Engineer", department="Data", experience_min_years=5)
    r = f_domain(Facts(job=job, parsed=parsed, candidate=None, application=None), {})
    assert r.value == "5.0 years in similar roles" and r.score == 100
