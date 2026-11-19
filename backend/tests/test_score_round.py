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
