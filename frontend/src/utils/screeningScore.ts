import type { CandidateApplicationRow } from "../api/types";
import { t as globalT, type TFunction } from "../i18n";

// Part 17.4: the ONE score shown everywhere -- the "Match score" (0-100) = composite_score.
// match_score (the AI resume-fit) is only a factor inside it ("Skills match (AI)") and is
// used here as a fallback only for applications scored before composite_score existed; the
// tooltip says so. Every list, card, chart and export uses this one definition.
export function matchScoreDisplay(
  row: Pick<CandidateApplicationRow, "composite_score" | "match_score">,
  t: TFunction = globalT,
): { value: number | null; tooltip: string } {
  if (row.composite_score != null) {
    return {
      value: row.composite_score,
      tooltip:
        row.match_score != null
          ? t("screening.score.tip", { ai: Math.round(row.match_score) })
          : t("screening.score.tip_no_ai"),
    };
  }
  if (row.match_score != null) {
    return { value: row.match_score, tooltip: t("screening.score.tip_legacy") };
  }
  return { value: null, tooltip: "" };
}

/** @deprecated Kept so older callers keep working; same as matchScoreDisplay. */
export const screeningScoreDisplay = matchScoreDisplay;
