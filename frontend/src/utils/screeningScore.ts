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
