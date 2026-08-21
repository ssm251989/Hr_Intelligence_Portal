import io
import uuid

from docx import Document

from app.ai_services.resume_matcher import ResumeMatchError
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.job_role import JobRole
from app.models.screening_settings import ScreeningSettings
from app.screening import service as screening_service


def _make_job(db_session, jd_text="Backend role needing Python.", **kwargs) -> JobRole:
    job = JobRole(title="Backend Engineer", jd_text=jd_text, **kwargs)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


_DEFAULT_PARSED_FIELDS = {"skills": ["Python"]}


def _make_candidate(db_session, parsed_fields=_DEFAULT_PARSED_FIELDS, **kwargs) -> Candidate:
    candidate = Candidate(full_name="Jane Doe", parsed_fields=parsed_fields, **kwargs)
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def _make_application(db_session, job, candidate, status="received", **kwargs) -> Application:
    application = Application(job_role_id=job.id, candidate_id=candidate.id, status=status, **kwargs)
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def _make_docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _fake_result(**overrides) -> dict:
    # No "experience_score"/"skill_match_pct"/"missing_skills"/"certificates_score" keys
    # -- match_resume (the AI call) no longer produces any of these; run_screening
    # computes them itself via compute_experience_score/compute_skills_score/
    # compute_certificates_score and overwrites whatever's in `result` for those keys, so
    # these tests' jobs/candidates deliberately carry no experience_min_years/max_years/
    # total_experience_years, skill categories, or preferred_certifications, which all
    # three compute functions treat as "no requirement configured" -> a fixed 100 (see
    # test_compute_experience_score_*/test_compute_skills_score_*/
    # test_compute_certificates_score_* below for the cases that actually vary these
    # inputs).
    result = {
        "match_score": 80,
        "location_score": 80,
        "recommendation": "strong_fit",
    }
    result.update(overrides)
    return result


# --- composite_score: pure function, equal weights ---


def test_composite_score_is_equal_weighted_average():
    result = {
        "skill_match_pct": 100,
        "experience_score": 0,
        "location_score": 50,
        "certificates_score": 50,
        "match_score": 100,
    }
    # (100 + 0 + 50 + 50 + 100) / 5 = 60 -- confirms all five factors count equally, not
    # some larger weight for e.g. match_score just because it's the "existing" one.
    assert screening_service.composite_score(result) == 60.0


def test_composite_score_all_equal_inputs_returns_same_value():
    result = {k: 73 for k in ["skill_match_pct", "experience_score", "location_score", "certificates_score", "match_score"]}
    assert screening_service.composite_score(result) == 73.0


def test_composite_score_changing_any_single_factor_moves_the_average_by_its_fifth():
    base = {"skill_match_pct": 60, "experience_score": 60, "location_score": 60, "certificates_score": 60, "match_score": 60}
    bumped = {**base, "certificates_score": 100}
    # +40 on one of five equally-weighted factors -> +8 on the average, not some other
    # fraction that would imply certificates_score carries more or less weight than peers.
    assert screening_service.composite_score(bumped) - screening_service.composite_score(base) == 8.0


# --- compute_experience_score: deterministic replacement for the old AI-judged score ---


def test_compute_experience_score_no_requirement_configured_is_full_score():
    # Both bounds null -- same "absence of a requirement is not a penalty" convention as
    # location_score/certificates_score, regardless of the candidate's own years.
    assert screening_service.compute_experience_score(2, None, None) == 100
    assert screening_service.compute_experience_score(None, None, None) == 100


def test_compute_experience_score_within_range_is_full_score():
    assert screening_service.compute_experience_score(4, 3, 5) == 100
    assert screening_service.compute_experience_score(3, 3, 5) == 100  # at the min boundary
    assert screening_service.compute_experience_score(5, 3, 5) == 100  # at the max boundary


def test_compute_experience_score_open_ended_max_only_checks_the_floor():
    # job_max_years null means "X+ years" -- any candidate at or above the minimum is a
    # full score no matter how much more experience they have.
    assert screening_service.compute_experience_score(5, 5, None) == 100
    assert screening_service.compute_experience_score(20, 5, None) == 100


def test_compute_experience_score_falls_off_below_min():
    # 15 points off per year of shortfall, floored at 0.
    assert screening_service.compute_experience_score(4, 5, 8) == 85
    assert screening_service.compute_experience_score(3, 5, 8) == 70
    assert screening_service.compute_experience_score(0, 5, 8) == max(0, 100 - 5 * 15)


def test_compute_experience_score_falls_off_above_max():
    assert screening_service.compute_experience_score(9, 5, 8) == 85
    assert screening_service.compute_experience_score(10, 5, 8) == 70


def test_compute_experience_score_floors_at_zero_well_outside_range():
    assert screening_service.compute_experience_score(0, 20, 25) == 0


def test_compute_experience_score_unknown_candidate_years_is_neutral_when_requirement_exists():
    # Distinct from both a confirmed match (100) and a confirmed mismatch (a low falloff
    # score) -- the candidate's own years just couldn't be determined.
    assert screening_service.compute_experience_score(None, 3, 5) == 50
    assert screening_service.compute_experience_score(None, 5, None) == 50


# --- compute_skills_score: deterministic replacement for the old AI-judged skill_match_pct ---


def test_compute_skills_score_no_categories_configured_is_full_score():
    # No requirement in any of the 4 categories -- same "absence of a requirement is not
    # a penalty" convention as location_score/certificates_score/experience_score.
    result = screening_service.compute_skills_score(["Python"], None, None, None, None)
    assert result["score"] == 100
    assert result["missing_required"] == []
    assert result["missing_preferred"] == []


def test_compute_skills_score_full_match_across_all_categories_is_100():
    result = screening_service.compute_skills_score(
        ["Python", "FastAPI", "Docker", "Communication"],
        technical_must_have=["Python"], technical_good_to_have=["FastAPI"],
        soft_must_have=["Communication"], soft_good_to_have=["Docker"],
    )
    assert result["score"] == 100
    assert result["missing_required"] == []
    assert result["missing_preferred"] == []


def test_compute_skills_score_missing_must_have_technical_costs_the_most():
    # 100% good-to-have/soft coverage, 0% technical-must-have -> loses exactly the 50-point
    # technical_must_have weight.
    result = screening_service.compute_skills_score(
        [],
        technical_must_have=["Python"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["score"] == 50
    assert result["missing_required"] == ["Python"]
    assert result["missing_preferred"] == []


def test_compute_skills_score_missing_good_to_have_technical_costs_less_than_must_have():
    # Same setup as above but the unmet skill is technical_good_to_have (weight 20, not 50).
    result = screening_service.compute_skills_score(
        [],
        technical_must_have=None, technical_good_to_have=["Kubernetes"],
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["score"] == 80
    assert result["missing_required"] == []
    assert result["missing_preferred"] == ["Kubernetes"]


def test_compute_skills_score_missing_soft_must_have_weighs_the_same_as_technical_good_to_have():
    # Both technical_good_to_have and soft_must_have are weighted 20 -- confirms the
    # "roughly equal next tier" ordering the weights were chosen for.
    technical_good_to_have_result = screening_service.compute_skills_score(
        [], technical_must_have=None, technical_good_to_have=["Kubernetes"], soft_must_have=None, soft_good_to_have=None,
    )
    soft_must_have_result = screening_service.compute_skills_score(
        [], technical_must_have=None, technical_good_to_have=None, soft_must_have=["Leadership"], soft_good_to_have=None,
    )
    assert technical_good_to_have_result["score"] == soft_must_have_result["score"] == 80


def test_compute_skills_score_missing_good_to_have_soft_costs_the_least():
    result = screening_service.compute_skills_score(
        [], technical_must_have=None, technical_good_to_have=None, soft_must_have=None, soft_good_to_have=["Empathy"],
    )
    assert result["score"] == 90
    assert result["missing_required"] == []
    assert result["missing_preferred"] == ["Empathy"]


def test_compute_skills_score_matching_is_case_and_whitespace_insensitive():
    result = screening_service.compute_skills_score(
        ["  PYTHON  "], technical_must_have=["python"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["score"] == 100
    assert result["missing_required"] == []


def test_compute_skills_score_missing_required_combines_technical_and_soft_must_have():
    result = screening_service.compute_skills_score(
        [], technical_must_have=["Python"], technical_good_to_have=None,
        soft_must_have=["Communication"], soft_good_to_have=None,
    )
    assert set(result["missing_required"]) == {"Python", "Communication"}


# --- compute_skills_score: technical/soft breakdown for Remarks (Part C) display grouping --
# missing_required/missing_preferred stay the flat, backward-compatible union (still what
# feeds Application.missing_skills and every score/threshold decision); the _technical
# suffix and missing_soft keys below are purely for Remarks to group soft skills into
# their own "Soft skills to verify in interview" line instead of mixing them into the
# required/preferred technical-gap lines.


def test_compute_skills_score_missing_required_technical_excludes_soft_must_have():
    result = screening_service.compute_skills_score(
        [], technical_must_have=["Python"], technical_good_to_have=None,
        soft_must_have=["Communication"], soft_good_to_have=None,
    )
    assert result["missing_required_technical"] == ["Python"]
    assert result["missing_soft"] == ["Communication"]


def test_compute_skills_score_missing_preferred_technical_excludes_soft_good_to_have():
    result = screening_service.compute_skills_score(
        [], technical_must_have=None, technical_good_to_have=["Kubernetes"],
        soft_must_have=None, soft_good_to_have=["Empathy"],
    )
    assert result["missing_preferred_technical"] == ["Kubernetes"]
    assert result["missing_soft"] == ["Empathy"]


def test_compute_skills_score_missing_soft_combines_must_and_good_to_have_without_severity():
    # missing_soft doesn't distinguish severity the way missing_required/missing_preferred
    # do -- Remarks renders it as one flat "Soft skills to verify in interview" line.
    result = screening_service.compute_skills_score(
        [], technical_must_have=None, technical_good_to_have=None,
        soft_must_have=["Leadership"], soft_good_to_have=["Empathy"],
    )
    assert set(result["missing_soft"]) == {"Leadership", "Empathy"}
    assert result["missing_required_technical"] == []
    assert result["missing_preferred_technical"] == []


# --- compute_skills_score: candidate_certificates cross-check ---


def test_compute_skills_score_cross_checks_certificates_for_a_skill_requirement():
    # A platform/technology named only in a certification, not in parsed skills, should
    # still satisfy a skill requirement naming that platform -- e.g. "Azure" evidenced by
    # holding "Microsoft Azure Fundamentals (AZ-900)", filed under certificates.
    result = screening_service.compute_skills_score(
        ["Python"],
        technical_must_have=["Azure"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
        candidate_certificates=["Microsoft Azure Fundamentals (AZ-900)"],
    )
    assert result["missing_required"] == []
    assert result["score"] == 100


def test_compute_skills_score_certificates_optional_and_defaults_to_no_extra_credit():
    # candidate_certificates is optional -- every pre-existing call site that never passes
    # it keeps behaving exactly as before (no crash, and no accidental match from nothing).
    result = screening_service.compute_skills_score(
        [], technical_must_have=["Azure"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_required"] == ["Azure"]


def test_compute_skills_score_certificates_do_not_manufacture_a_match_they_do_not_evidence():
    # A certificate that has nothing to do with the requirement must not accidentally
    # contribute credit toward it.
    result = screening_service.compute_skills_score(
        [], technical_must_have=["Azure"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
        candidate_certificates=["PMP"],
    )
    assert result["missing_required"] == ["Azure"]


# --- compute_certificates_score: deterministic replacement for the old AI-judged certificates_score ---


def test_compute_certificates_score_no_certifications_configured_is_full_score():
    # No preferred_certifications at all -- same "absence of a requirement is not a
    # penalty" convention as location_score/experience_score/skill_match_pct.
    result = screening_service.compute_certificates_score(["PMP"], None)
    assert result["score"] == 100
    assert result["missing"] == []
    assert screening_service.compute_certificates_score(None, None) == {"score": 100, "missing": []}


def test_compute_certificates_score_full_coverage_is_100():
    result = screening_service.compute_certificates_score(
        ["AWS Certified Solutions Architect", "PMP"], ["PMP"]
    )
    assert result["score"] == 100
    assert result["missing"] == []


def test_compute_certificates_score_partial_coverage_is_scaled_fraction():
    # Candidate holds 1 of 2 preferred certifications -> 50% coverage.
    result = screening_service.compute_certificates_score(["PMP"], ["PMP", "CPA"])
    assert result["score"] == 50
    assert result["missing"] == ["CPA"]


def test_compute_certificates_score_zero_coverage_when_candidate_has_none_of_them():
    result = screening_service.compute_certificates_score([], ["PMP", "CPA"])
    assert result["score"] == 0
    assert set(result["missing"]) == {"PMP", "CPA"}


def test_compute_certificates_score_zero_coverage_when_candidate_certificates_is_none():
    # The candidate's resume was parsed but held no certificates section at all --
    # distinct from an empty list only in how resume_parser.py might represent it, same
    # treatment either way.
    result = screening_service.compute_certificates_score(None, ["PMP"])
    assert result["score"] == 0
    assert result["missing"] == ["PMP"]


def test_compute_certificates_score_matching_is_case_and_whitespace_insensitive():
    result = screening_service.compute_certificates_score(["  pmp  "], ["PMP"])
    assert result["score"] == 100
    assert result["missing"] == []


def test_compute_certificates_score_token_overlap_matches_despite_extra_suffix_wording():
    # Real case that motivated this change: the job names a certification without any
    # platform-version suffix, the candidate's parsed certificate carries one -- an exact
    # or substring comparison would call this a miss even though it's plainly the same
    # certification.
    result = screening_service.compute_certificates_score(
        ["Automation Anywhere Certified Advanced RPA Professional -- A360"],
        ["Automation Anywhere Certified Advanced RPA Professional"],
    )
    assert result["score"] == 100
    assert result["missing"] == []


# --- compute_skills_score / compute_certificates_score: token-overlap matching ---
# (replaces the old exact-string/whole-phrase _skill_coverage -- job requirement lists are
# routinely written as full sentences/compound phrases, not short tags matching a parsed
# resume's skills entries verbatim; see the Arjun Reddy / Automation Anywhere Architect
# investigation that motivated this.)


def test_compute_skills_score_token_overlap_matches_a_compound_requirement_worded_differently():
    # "SQL / database integration" (job) vs candidate skills "SQL Server" + "API
    # Integration" -- no exact or substring match either way, but 2 of the requirement's 3
    # significant tokens ("sql", "integration") are evidenced somewhere in the candidate's
    # skills, clearing the 50% satisfied threshold.
    result = screening_service.compute_skills_score(
        ["SQL Server", "API Integration"],
        technical_must_have=["SQL / database integration"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_required"] == []
    # tech_must_have coverage 2/3 (67%) * weight 50, plus the other 3 unconfigured
    # categories' full 50-point "no requirement configured" credit -- not 100, since this
    # test only cares whether the one configured requirement counts as matched, which
    # missing_required (asserted above) already confirms.
    assert result["score"] == 83


def test_compute_skills_score_token_overlap_matches_a_compound_requirement_split_across_skills():
    # "Automation Anywhere Control Room" (job) vs the candidate's separate "Automation
    # Anywhere A360" and "Control Room" skills -- full token overlap even though neither
    # single parsed skill contains the whole job phrase.
    result = screening_service.compute_skills_score(
        ["Automation Anywhere A360", "Control Room"],
        technical_must_have=["Automation Anywhere Control Room"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_required"] == []
    assert result["score"] == 100


def test_compute_skills_score_token_overlap_matches_narrative_requirement_via_shared_terms():
    # "Exception handling and logging" (job) vs candidate's separate "Exception Handling"
    # and "Logging" skills -- "and" is filler and gets stripped, leaving 3/3 tokens covered.
    result = screening_service.compute_skills_score(
        ["Exception Handling", "Logging"],
        technical_must_have=["Exception handling and logging"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_required"] == []
    assert result["score"] == 100


def test_compute_skills_score_genuinely_absent_skill_still_flagged_as_missing():
    # Token overlap must not manufacture a match out of thin air -- a requirement the
    # candidate's skills never evidence in any form still shows up as missing, at 0 credit.
    result = screening_service.compute_skills_score(
        ["Automation Anywhere A360", "Control Room", "SQL Server"],
        technical_must_have=["Bot Creator / Bot Runner"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_required"] == ["Bot Creator / Bot Runner"]
    # 0% overlap on the one configured (must-have technical, weight 50) category, plus the
    # other 3 unconfigured categories' full 50-point "no requirement configured" credit.
    assert result["score"] == 50


def test_compute_skills_score_generic_padding_words_stripped_so_the_real_term_alone_satisfies_it():
    # "OCR and document processing" -- "document"/"processing" are generic padding around
    # the one real, specific concept ("OCR") and are in _SKILL_MATCH_STOPWORDS for exactly
    # that reason, so the requirement reduces to just {"ocr"}, which the candidate's plain
    # "OCR" skill satisfies outright (100% overlap on what's left).
    result = screening_service.compute_skills_score(
        ["OCR"],
        technical_must_have=None, technical_good_to_have=["OCR and document processing"],
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_preferred"] == []
    assert result["score"] == 100


def test_compute_skills_score_below_threshold_overlap_still_counts_as_missing_but_earns_partial_credit():
    # "Experience with GenAI / AI / Intelligent Automation" -- none of "document"/
    # "processing"/etc. filler is in this phrase, so it isn't reduced the way the OCR case
    # above is. Candidate has "Web Automation" but nothing evidencing "genai"/"ai"/
    # "intelligent" -- 1 of 4 tokens (25%) is below the 50% satisfied threshold, so it's
    # still listed as missing, but the category's coverage is no longer the flat 0 that
    # whole-string matching would have produced for a fully-unmatched phrase.
    result = screening_service.compute_skills_score(
        ["Web Automation"],
        technical_must_have=None, technical_good_to_have=["Experience with GenAI / AI / Intelligent Automation"],
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_preferred"] == ["Experience with GenAI / AI / Intelligent Automation"]
    assert 0 < result["score"] < 100


def test_tokenize_never_treats_short_technical_terms_as_stopwords():
    # The stopword list is a fixed set of filler words, never length-based -- real short
    # technical acronyms must survive tokenizing even though they're as short as (or
    # shorter than) genuine filler words like "a"/"of"/"or"/"the".
    for term in ["AI", "OCR", "SQL", "IT", "UI", "ML"]:
        assert screening_service._tokenize(term) == {term.lower()}


def test_tokenize_strips_filler_words_from_a_narrative_requirement():
    # Deliberately picks words none of _STEM_SUFFIX_RULES touch, so this test verifies only
    # the stopword behavior in isolation -- see test_stemming.py for stemming's own cases.
    tokens = screening_service._tokenize("Ability to work with modern cloud infrastructure")
    assert tokens == {"work", "modern", "cloud", "infrastructure"}
    assert "ability" not in tokens
    assert "with" not in tokens
    assert "to" not in tokens


def test_tokenize_strips_the_new_generic_padding_words_from_a_compound_requirement():
    tokens = screening_service._tokenize("Ability to interact with business and technical stakeholders")
    assert "technical" not in tokens
    assert "ability" not in tokens
    assert "with" not in tokens
    assert "and" not in tokens
    # "business"/"stakeholders" survive filtering but do get stemmed -- see test_stemming.py.
    assert tokens == {"interact", "busines", "stakehold"}


def test_tokenize_strips_generic_words_padding_a_compound_platform_requirement():
    # "solutions"/"platforms"/"teams"/"tools" (plural, generic-noun padding) are stopped;
    # their singular forms are deliberately NOT, since those are the real, meaningful word
    # in other genuine skills elsewhere ("RPA Solution Architecture", "Solution Discovery").
    tokens = screening_service._tokenize("Cloud platforms such as Azure/AWS")
    assert tokens == {"cloud", "azure", "aws"}
    assert "platforms" not in tokens

    # "automation" ends up stemmed to "automat" (the "-ion" rule) -- a side effect of
    # stemming, not of this stopword test, asserted here only so the full expected token
    # set is exact rather than partially checked.
    tokens = screening_service._tokenize("Automation solutions and tools for global teams")
    assert tokens == {"automat", "global"}
    assert "solutions" not in tokens
    assert "tools" not in tokens
    assert "teams" not in tokens


# --- item 3 false-positive check: does stripping generic padding words make an unrelated
# skill accidentally satisfy a real, distinct compound requirement? Checked against real
# requirement strings from the Automation Anywhere Architect job posting (see the Arjun
# Reddy investigation this conversation is built on). ---


def test_unrelated_skill_still_does_not_satisfy_ocr_and_document_processing():
    # "Process mining" has nothing to do with OCR -- must not cross the threshold just
    # because "document"/"processing" are now generic-word stopwords.
    result = screening_service.compute_skills_score(
        ["Process mining"],
        technical_must_have=None, technical_good_to_have=["OCR and document processing"],
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_preferred"] == ["OCR and document processing"]


def test_unrelated_skills_still_do_not_satisfy_cloud_platforms_requirement():
    # "SAP"/"Oracle" are real enterprise platforms, but not Azure/AWS -- must not cross
    # the threshold just because "platforms" is now a generic-word stopword.
    result = screening_service.compute_skills_score(
        ["SAP", "Oracle"],
        technical_must_have=None, technical_good_to_have=["Cloud platforms such as Azure/AWS"],
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_preferred"] == ["Cloud platforms such as Azure/AWS"]


def test_unrelated_automation_skill_still_leaves_iq_bot_document_automation_a_partial_miss():
    # "Web Automation" shares only the generic word "automation" with "Experience with IQ
    # Bot / Document Automation" -- must stay a partial, below-threshold miss, not flip to
    # a full match, since "document" being stopped removes padding but "bot"/"iq" (the
    # requirement's actual distinguishing content) are still completely unevidenced.
    result = screening_service.compute_skills_score(
        ["Web Automation"],
        technical_must_have=None, technical_good_to_have=["Experience with IQ Bot / Document Automation"],
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_preferred"] == ["Experience with IQ Bot / Document Automation"]


def test_KNOWN_LIMITATION_generic_padding_plus_stemming_can_false_positive_on_one_shared_word():
    # Documented, not silently accepted: once a compound requirement is stripped down to a
    # single surviving token ("Ability to lead technical teams" -> just {"lead"} once
    # "technical"/"teams" are stopped), ANY candidate skill containing that same word in a
    # completely unrelated sense -- "Lead Generation" (a sales/marketing skill) rather than
    # "leadership" -- satisfies it outright. This is a real trade-off of combining
    # aggressive stopword-stripping with a single-token-left denominator, not a bug in the
    # comparison logic; flagged here so a future change to the stopword/stemming lists has
    # a test that will visibly break if this risk gets worse, not one that hides it.
    result = screening_service.compute_skills_score(
        ["Lead Generation"],
        technical_must_have=None, technical_good_to_have=None,
        soft_must_have=["Ability to lead technical teams"], soft_good_to_have=None,
    )
    assert result["missing_required"] == []  # a false positive, tracked deliberately


# --- compute_skills_score: bare years-of-experience requirement bullets are excluded --
# entirely, not token-matched -- since compute_experience_score already scores that exact
# gap against experience_min_years/experience_max_years/total_experience_years. Real
# strings from the Automation Anywhere Architect job posting (the Arjun Reddy
# investigation): "8+ years of overall IT experience" and "5+ years of strong RPA
# experience", both filed under technical_skills_must_have.


def test_compute_skills_score_excludes_bare_years_of_experience_requirement():
    result = screening_service.compute_skills_score(
        [], technical_must_have=["8+ years of overall IT experience"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    # Excluded entirely -- not just satisfied, but dropped from the category before
    # coverage is computed -- so a candidate with an empty skills list still scores full
    # marks on a job whose only must-have technical requirement is this phrase.
    assert result["missing_required"] == []
    assert result["missing_required_technical"] == []
    assert result["score"] == 100


def test_compute_skills_score_excludes_years_of_experience_requirement_with_other_content():
    # "5+ years of strong RPA experience" is still years-of-experience phrasing by the same
    # generic pattern, even though it also names a technology ("RPA") -- excluded
    # wholesale like the plainer "8+ years..." bullet, not partially credited.
    result = screening_service.compute_skills_score(
        [], technical_must_have=["5+ years of strong RPA experience", "Python"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_required"] == ["Python"]


def test_compute_skills_score_years_of_experience_exclusion_is_generic_not_hardcoded():
    # A job-specific phrasing that was never hardcoded anywhere -- confirms detection is by
    # pattern (digits + year/years/yrs with "experience" nearby), not a fixed string list.
    result = screening_service.compute_skills_score(
        [], technical_must_have=["10+ yrs of enterprise architecture experience"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_required"] == []
    assert result["score"] == 100


def test_compute_skills_score_does_not_exclude_a_requirement_that_merely_contains_digits():
    # A requirement with digits but no year/experience phrasing at all (e.g. a version
    # number) must still be evaluated normally, not swept up by an overly broad pattern.
    result = screening_service.compute_skills_score(
        [], technical_must_have=["Automation Anywhere A360"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_required"] == ["Automation Anywhere A360"]


def test_compute_skills_score_does_not_exclude_years_phrasing_without_the_word_experience():
    # Digits + "years" alone, with no "experience" anywhere nearby, isn't the
    # already-tracked experience_min_years/max_years phrasing -- must still be evaluated,
    # not silently dropped.
    result = screening_service.compute_skills_score(
        ["Warranty"], technical_must_have=["5 years warranty"], technical_good_to_have=None,
        soft_must_have=None, soft_good_to_have=None,
    )
    assert result["missing_required"] == []  # evaluated normally -- 1 of 2 tokens ("warranty") matches, clearing 50%


# --- run_screening: the deterministic experience_score actually feeds the composite ---


def test_run_screening_uses_real_experience_range_against_candidate_years(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100),
    )
    job = _make_job(db_session, experience_min_years=3, experience_max_years=5)
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"], "total_experience_years": 4})
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    # Candidate's 4 years falls within [3, 5] -> experience_score 100 -> composite 100.
    assert float(result.composite_score) == 100.0

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    assert audit_entry.details["experience_score"] == 100


def test_run_screening_penalizes_candidate_below_the_jobs_min_years(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100),
    )
    job = _make_job(db_session, experience_min_years=5, experience_max_years=8)
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"], "total_experience_years": 3})
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    # 2 years short of the 5-year minimum -> 100 - 2*15 = 70 -> composite (100*4 + 70)/5.
    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    assert audit_entry.details["experience_score"] == 70
    assert float(result.composite_score) == 94.0


def test_run_screening_neutral_score_when_candidate_years_unparsed_but_job_has_a_range(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100),
    )
    job = _make_job(db_session, experience_min_years=3, experience_max_years=5)
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})  # no total_experience_years
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    assert audit_entry.details["experience_score"] == 50
    assert float(result.composite_score) == 90.0


# --- run_screening: the deterministic skill_match_pct actually feeds the composite,
# and Remarks (via missing_required_skills/missing_preferred_skills) can tell severity apart ---


def test_run_screening_uses_real_skill_categories_against_candidate_skills(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100),
    )
    job = _make_job(
        db_session, technical_skills_must_have=["Python"], technical_skills_good_to_have=["Kubernetes"],
        soft_skills_must_have=["Communication"], soft_skills_good_to_have=["Empathy"],
    )
    candidate = _make_candidate(
        db_session, parsed_fields={"skills": ["Python", "Communication"]}
    )
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    # Both must-have categories matched (50 + 20), both good-to-have categories missed
    # (0 + 0) -> skill_match_pct = 70. Composite = (100_experience + 70_skills + 100*3) / 5.
    # missing_required_skills/missing_preferred_skills are technical-only now (Remarks
    # display split, see describe_screening_audit_entry) -- "Empathy" (soft_good_to_have)
    # moves to missing_soft_skills instead, but still counts toward skills_score/
    # composite_score exactly the same either way.
    assert audit_entry.details["skills_score"] == 70
    assert set(audit_entry.details["missing_required_skills"]) == set()
    assert set(audit_entry.details["missing_preferred_skills"]) == {"Kubernetes"}
    assert set(audit_entry.details["missing_soft_skills"]) == {"Empathy"}
    assert float(result.composite_score) == 94.0


def test_run_screening_missing_required_skills_recorded_distinctly_from_preferred(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100),
    )
    job = _make_job(
        db_session, technical_skills_must_have=["Python", "SQL"], technical_skills_good_to_have=["Docker"],
    )
    candidate = _make_candidate(db_session, parsed_fields={"skills": []})
    application = _make_application(db_session, job, candidate)

    screening_service.run_screening(db_session, application, job, candidate, "system")

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    assert set(audit_entry.details["missing_required_skills"]) == {"Python", "SQL"}
    assert audit_entry.details["missing_preferred_skills"] == ["Docker"]
    assert audit_entry.details["missing_soft_skills"] == []  # job configures no soft skills at all
    # missing_skills (the flat, backward-compatible union stored on Application) still
    # carries both severities together.
    assert set(audit_entry.details["missing_skills"]) == {"Python", "SQL", "Docker"}


# --- run_screening: the deterministic certificates_score actually feeds the composite ---


def test_run_screening_uses_real_preferred_certifications_against_candidate_certificates(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100),
    )
    job = _make_job(db_session, preferred_certifications=["PMP", "CPA"])
    candidate = _make_candidate(
        db_session, parsed_fields={"skills": ["Python"], "certificates": ["PMP"]}
    )
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    # 1 of 2 preferred certifications held -> 50. Composite = (100_experience + 100_skills
    # + 50_certificates + 100_location + 100_match) / 5 = 90.
    assert audit_entry.details["certificates_score"] == 50
    assert audit_entry.details["missing_preferred_certifications"] == ["CPA"]
    assert float(result.composite_score) == 90.0


# --- is_eligible_for_screening ---


def test_is_eligible_for_screening_true_only_for_received(db_session):
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    for status in ["screened", "hr_selected", "hr_rejected", "on_hold", "onboarding_completed"]:
        application = _make_application(db_session, job, candidate, status=status)
        assert screening_service.is_eligible_for_screening(application) is False
    received_app = _make_application(db_session, job, candidate, status="received")
    assert screening_service.is_eligible_for_screening(received_app) is True


# --- run_screening: threshold auto-advance, including the max-boundary equivalence ---


def test_run_screening_in_range_advances_to_screened(db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result())
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    # (80 + 80 -- the two AI-scored factors -- + 100 + 100 + 100, the deterministic
    # experience_score/skill_match_pct/certificates_score for a job with no experience
    # range, skill categories, or preferred_certifications configured) / 5.
    assert result.status == "screened"
    assert float(result.composite_score) == 92.0


def test_run_screening_at_max_boundary_advances_to_screened_same_as_in_range(db_session, monkeypatch):
    # Design decision: a score at or above the configured max threshold gets identical
    # treatment to a score within [min, max] -- both become 'screened', no separate
    # high-priority outcome. Default max seeded by migration e1f3a7c9b2d4 is 100.
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=100, location_score=100),
    )
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    assert float(result.composite_score) == 100.0
    assert result.status == "screened"


def test_run_screening_below_min_threshold_stays_received_but_is_still_scored(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=10, location_score=10),
    )
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    # (10 + 10 + 100 + 100 + 100 -- no experience range, skill categories, or
    # preferred_certifications configured) / 5 = 64.
    assert float(result.composite_score) == 64.0
    assert result.status == "received"

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == application.id, AuditLog.action == "ai_screening_scored")
        .one()
    )
    assert audit_entry.details["advanced"] is False
    assert audit_entry.details["new_status"] == "received"


def test_run_screening_respects_configured_threshold_not_just_the_default(db_session, monkeypatch):
    # A score of 55 is below the seeded default min (60) but above a lowered min (40) --
    # proves the threshold is actually read from screening_settings, not hardcoded.
    settings_row = db_session.get(ScreeningSettings, 1)
    settings_row.dashboard_min_score = 40
    db_session.commit()

    monkeypatch.setattr(
        "app.screening.service.match_resume",
        lambda *a, **k: _fake_result(match_score=55, location_score=55),
    )
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    result = screening_service.run_screening(db_session, application, job, candidate, "system")

    assert result.status == "screened"


# --- attempt_auto_screen: the best-effort trigger used by the two automatic hooks ---


def test_attempt_auto_screen_skips_already_screened_application(db_session, monkeypatch):
    called = []
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: called.append(1) or _fake_result())
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate, status="screened", composite_score=90)

    outcome = screening_service.attempt_auto_screen(db_session, application)

    assert outcome is None
    assert called == []
    db_session.refresh(application)
    assert application.status == "screened"


def test_attempt_auto_screen_noop_when_job_has_no_jd_text(db_session, monkeypatch):
    called = []
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: called.append(1) or _fake_result())
    job = _make_job(db_session, jd_text=None)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    outcome = screening_service.attempt_auto_screen(db_session, application)

    assert outcome is None
    assert called == []


def test_attempt_auto_screen_noop_when_candidate_not_parsed(db_session, monkeypatch):
    called = []
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: called.append(1) or _fake_result())
    job = _make_job(db_session)
    candidate = _make_candidate(db_session, parsed_fields=None)
    application = _make_application(db_session, job, candidate)

    outcome = screening_service.attempt_auto_screen(db_session, application)

    assert outcome is None
    assert called == []


def test_attempt_auto_screen_swallows_ai_failure(db_session, monkeypatch):
    def fake_match_resume(*args, **kwargs):
        raise ResumeMatchError("boom")

    monkeypatch.setattr("app.screening.service.match_resume", fake_match_resume)
    job = _make_job(db_session)
    candidate = _make_candidate(db_session)
    application = _make_application(db_session, job, candidate)

    outcome = screening_service.attempt_auto_screen(db_session, application)

    assert outcome is None
    db_session.refresh(application)
    assert application.status == "received"
    assert application.composite_score is None


# --- integration: the two real hook points fire automatically ---


def test_create_application_triggers_auto_screen_when_resume_already_parsed(client, db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result())
    job = _make_job(db_session, jd_text="Needs Python.")
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})

    response = client.post("/applications", json={"job_role_id": str(job.id), "candidate_id": str(candidate.id)})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "screened"
    # (80 * 2 AI-scored factors + 100 + 100 + 100, the deterministic experience_score/
    # skill_match_pct/certificates_score for a job with no experience range, skill
    # categories, or preferred_certifications configured) / 5.
    assert body["composite_score"] == 92.0

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(body["id"]), AuditLog.action == "ai_screening_scored")
        .one_or_none()
    )
    assert audit_entry is not None


def test_create_application_does_not_fail_when_screening_ai_call_errors(client, db_session, monkeypatch):
    # The application-creation flow must succeed regardless of screening's own problems.
    def fake_match_resume(*args, **kwargs):
        raise ResumeMatchError("boom")

    monkeypatch.setattr("app.screening.service.match_resume", fake_match_resume)
    job = _make_job(db_session, jd_text="Needs Python.")
    candidate = _make_candidate(db_session, parsed_fields={"skills": ["Python"]})

    response = client.post("/applications", json={"job_role_id": str(job.id), "candidate_id": str(candidate.id)})

    assert response.status_code == 201
    assert response.json()["status"] == "received"


def test_parse_resume_triggers_auto_screen_for_existing_received_application(client, db_session, monkeypatch):
    monkeypatch.setattr("app.screening.service.match_resume", lambda *a, **k: _fake_result())
    monkeypatch.setattr(
        "app.candidates.router.parse_resume",
        lambda raw_text: {"full_name": "Jane Doe", "email": "jane@example.com", "skills": ["Python"]},
    )
    job = _make_job(db_session, jd_text="Needs Python.")

    resume_bytes = _make_docx_bytes("Jane Doe\njane@example.com")
    upload_response = client.post(
        "/candidates/upload",
        files={"file": ("resume.docx", resume_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    candidate_id = upload_response.json()["id"]

    # Application created before the resume is parsed (mirrors the career-portal path:
    # apply first, background-parse afterward).
    application_response = client.post(
        "/applications", json={"job_role_id": str(job.id), "candidate_id": candidate_id}
    )
    assert application_response.json()["status"] == "received"  # not parsed yet, so no auto-screen at creation time

    parse_response = client.post(f"/candidates/{candidate_id}/parse-resume")
    assert parse_response.status_code == 200

    application_id = application_response.json()["id"]
    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(application_id), AuditLog.action == "ai_screening_scored")
        .one_or_none()
    )
    assert audit_entry is not None
    refreshed = db_session.get(Application, uuid.UUID(application_id))
    assert refreshed.status == "screened"
