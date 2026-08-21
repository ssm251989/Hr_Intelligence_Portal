from app.screening import service as screening_service

# _stem is a single, fixed-order pass through a small, explicit suffix list
# (-ship, -ing, -ers, -er, -ions, -ion, -ies->y, -ed, -s), never a real dictionary-based
# stemmer -- these tests document exactly which of the word-form pairs it does and doesn't
# unify, rather than assuming every "obviously related" pair collapses to the same stem.


# --- pairs that DO unify under this exact suffix list ---


def test_leadership_stems_to_the_same_root_as_lead():
    # The motivating case: "leadership" clears two rules in one pass ("-ship" -> "leader",
    # then "-er" -> "lead"), landing on the same stem as the bare word "lead".
    assert screening_service._stem("leadership") == screening_service._stem("lead") == "lead"


def test_developer_stems_to_the_same_root_as_develop():
    # "-er" alone is enough here: "developer" -> "develop".
    assert screening_service._stem("developer") == screening_service._stem("develop") == "develop"


def test_solution_and_solutions_stem_to_the_same_root():
    # "-ions" is checked before "-ion" specifically so the plural doesn't reduce
    # differently from the singular ("solutions" -> "solut", "solution" -> "solut").
    assert screening_service._stem("solutions") == screening_service._stem("solution")


# --- pairs that do NOT unify -- the suffixes that actually differ them ("-ture", "-ment")
# are not in the specified list, so these stay genuinely distinct rather than being forced
# together by a rule that was never asked for. Documented here so this limitation is a
# known, tested fact, not a silent gap. ---


def test_architecture_and_architect_do_not_unify():
    # They differ by "-ture", not any suffix in _STEM_SUFFIX_RULES -- both pass through
    # unchanged, and the two words plainly still are not equal.
    assert screening_service._stem("architecture") == "architecture"
    assert screening_service._stem("architect") == "architect"


def test_development_and_develop_do_not_unify():
    # "-ment" is not in _STEM_SUFFIX_RULES -- "development" passes through unchanged, so it
    # does NOT reduce to "develop" the way "developer" does (that one clears via "-er").
    assert screening_service._stem("development") == "development"
    assert screening_service._stem("develop") == "develop"


def test_management_and_manage_do_not_unify():
    # Same "-ment" gap as development/develop above.
    assert screening_service._stem("management") == "management"
    assert screening_service._stem("manage") == "manage"


# --- acronyms and short words are never touched, regardless of what they happen to end in ---


def test_short_acronyms_are_never_stemmed():
    # Protected by the >= 4 remaining-character floor, not by a length check on the
    # acronym itself -- these are all short enough that no rule could fire without
    # dropping the result below that floor.
    for term in ["AI", "OCR", "SQL", "IT", "UI", "ML", "API", "SAP"]:
        assert screening_service._stem(term.lower()) == term.lower()


def test_four_letter_word_is_only_stemmed_if_the_remainder_still_clears_the_floor():
    # "cats" (4 letters) -> stripping "s" would leave "cat" (3 letters), below the floor,
    # so the rule does not fire and the word is left as-is.
    assert screening_service._stem("cats") == "cats"
    # "cards" (5 letters) -> stripping "s" leaves "card" (4 letters), which clears the
    # floor, so it does fire.
    assert screening_service._stem("cards") == "card"


# --- integration: _tokenize applies stemming symmetrically to both sides of a comparison ---


def test_compute_skills_score_matches_a_requirement_via_stemmed_word_form():
    # "Ability to lead technical teams" (job) vs the candidate's "Technical Leadership"
    # skill -- "technical" is stopped on both sides, "leadership" stems to "lead", exactly
    # matching the requirement's own "lead" token.
    result = screening_service.compute_skills_score(
        ["Technical Leadership"],
        technical_must_have=None, technical_good_to_have=None,
        soft_must_have=["Ability to lead technical teams"], soft_good_to_have=None,
    )
    assert result["missing_required"] == []
    assert result["score"] == 100


def test_compute_skills_score_does_not_match_via_a_suffix_the_stemmer_does_not_cover():
    # "Ability to lead technical teams" (job) vs a candidate whose only related skill is
    # phrased as "Technical Management" -- "management" does NOT stem to "manage" (the
    # "-ment" gap above), and neither word stems to "lead" at all, so this must stay a
    # real, correctly-reported miss, not a false match manufactured by over-eager stemming.
    result = screening_service.compute_skills_score(
        ["Technical Management"],
        technical_must_have=None, technical_good_to_have=None,
        soft_must_have=["Ability to lead technical teams"], soft_good_to_have=None,
    )
    assert result["missing_required"] == ["Ability to lead technical teams"]
