import type { CandidateApplicationRow } from "../api/types";

// Shared by the Candidates List and Screening List "Screening Score" columns -- one
// definition so the two pages can never quietly drift apart on what that column means.
// Prefers Part A's composite_score (the same number Remarks' "Strong fit (score X)" text
// quotes -- see backend app/screening/service.py describe_screening_audit_entry) so the
// column and Remarks never show different numbers with no explanation. Falls back to the
// original Resume Matcher match_score only for applications screened before Part A existed
// (which never got a composite_score); the tooltip always says which one is being shown so
// the two scores are never confused for each other.
export function screeningScoreDisplay(row: CandidateApplicationRow): { value: number | null; tooltip: string } {
  if (row.composite_score != null) {
    return {
      value: row.composite_score,
      tooltip:
        row.match_score != null
          ? `Composite screening score (skills, experience, location, certificates, resume match). Resume Match score: ${Math.round(row.match_score)}%`
          : "Composite screening score (skills, experience, location, certificates, resume match)",
    };
  }
  if (row.match_score != null) {
    return { value: row.match_score, tooltip: "Resume Match score -- this application predates composite screening" };
  }
  return { value: null, tooltip: "" };
}

// Candidates List's primary score column -- deliberately the OTHER score from
// screeningScoreDisplay above: the raw Resume Matcher match_score, not Part A's composite.
// A job's required/preferred skill lists can legitimately contain things a resume match
// alone doesn't evidence (see app/screening/service.py's compute_skills_score), so a
// composite score and a resume-match score for the same candidate can differ a lot -- the
// tooltip always names which one this is, and the other, so the two are never confused for
// each other the way an unlabeled single "Score" column let them be before.
export function resumeMatchScoreDisplay(row: CandidateApplicationRow): { value: number | null; tooltip: string } {
  if (row.match_score == null) {
    return { value: null, tooltip: "" };
  }
  return {
    value: row.match_score,
    tooltip:
      row.composite_score != null
        ? `Resume Match score (raw AI resume-to-JD match). Screening score (composite, incl. skills/experience/location/certificates): ${Math.round(row.composite_score)}%`
        : "Resume Match score (raw AI resume-to-JD match) -- this application hasn't been screened yet",
  };
}
