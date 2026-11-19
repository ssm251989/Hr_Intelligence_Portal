"""Part 17.4/17.5: the ONE candidate score -- "Match score (0-100)" -- built from
configurable, weighted factors (company default + per-job override, versioned), plus
knock-out rules that flag (never delete, never auto-reject) a candidate."""


def score_round(value) -> int:
    """A1 (Part 27): the ONE rounding of a Match score for people (round half up). Python's round() rounds
    96.5 to 96 while the screens' Math.round shows 97 - the same score read 97% and "96/100" on one row."""
    from decimal import ROUND_HALF_UP, Decimal

    return int(Decimal(str(float(value or 0))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
