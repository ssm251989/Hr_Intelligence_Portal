import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import { http } from "../../api/client";
import type { CandidateApplicationRow } from "../../api/types";
import { useT } from "../../i18n";
import { StatusChip } from "../../ui-kit";

// Part 17.6: the Shortlisting queue's own pieces -- tab sorting, per-job Shortlist threshold,
// the Match score chip and the hard-rules (knock-out) chip.

/** Row from GET /shortlisting/list; knocked_out/knockout_reasons were added in Part 17.6. */
export type QueueRow = CandidateApplicationRow & { knocked_out?: boolean; knockout_reasons?: string[] };

export const QUEUE_TABS = ["suggested", "needs_look", "shortlisted", "rejected"] as const;
export type QueueTab = (typeof QUEUE_TABS)[number];

export function matchScoreOf(row: QueueRow): number | null {
  return row.composite_score ?? null;
}

/**
 * Which waiting tab a "screened" row belongs in: knocked out -> "needs_look" (never auto-rejected),
 * at/above the job's threshold -> "suggested", otherwise "below" (stays in Screening).
 */
export function waitingBucket(row: QueueRow, threshold: number | null | undefined): "suggested" | "needs_look" | "below" {
  if (row.knocked_out) return "needs_look";
  const score = matchScoreOf(row);
  if (score == null || threshold == null) return "below";
  return score >= threshold ? "suggested" : "below";
}

interface ShortlistingConfig {
  threshold?: number | null;
  company_threshold?: number | null;
}

// One request per job for the whole session (cleared by clearThresholdCache on refresh).
const thresholdCache = new Map<string, Promise<number | null>>();

export function clearThresholdCache() {
  thresholdCache.clear();
}

function jobThreshold(jobId: string): Promise<number | null> {
  let hit = thresholdCache.get(jobId);
  if (!hit) {
    hit = http
      .get<ShortlistingConfig>(`/api/v1/scoring/shortlisting?job_id=${encodeURIComponent(jobId)}`)
      .then((r) => r.threshold ?? r.company_threshold ?? null)
      .catch(() => {
        thresholdCache.delete(jobId);
        return null;
      });
    thresholdCache.set(jobId, hit);
  }
  return hit;
}

/** Each job's Shortlist threshold, for the job ids given. `ready` is false until all have answered. */
export function useJobThresholds(jobIds: string[], refreshKey = 0): { thresholds: Map<string, number | null>; ready: boolean } {
  const key = Array.from(new Set(jobIds)).sort().join(",");
  const [state, setState] = useState<{ key: string; thresholds: Map<string, number | null> }>({ key: "", thresholds: new Map() });
  useEffect(() => {
    let alive = true;
    const ids = key ? key.split(",") : [];
    Promise.all(ids.map(async (id) => [id, await jobThreshold(id)] as const)).then((pairs) => {
      if (alive) setState({ key, thresholds: new Map(pairs) });
    });
    return () => {
      alive = false;
    };
  }, [key, refreshKey]);
  return { thresholds: state.thresholds, ready: state.key === key };
}

/** Match score against the job's Shortlist threshold. */
export function MatchScoreChip({ score, threshold }: { score: number | null; threshold: number | null | undefined }) {
  const t = useT();
  if (score == null) return <Typography variant="body2" color="text.secondary">{t("shortlistQueue.score.none")}</Typography>;
  const rounded = Math.round(score);
  const known = threshold != null;
  const above = known && score >= threshold;
  const tip = !known
    ? t("shortlistQueue.score.no_threshold")
    : t(above ? "shortlistQueue.score.tip_above" : "shortlistQueue.score.tip_below", { score: rounded, threshold });
  return (
    <Tooltip title={tip}>
      <Stack spacing={0.25} alignItems="flex-start" tabIndex={0} sx={{ outline: "none" }}>
        <StatusChip tone={!known ? "muted" : above ? "ok" : "sun"} emoji={above ? "star" : "bar_chart"} label={String(rounded)} />
        <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: "nowrap" }}>
          {known ? t("shortlistQueue.score.threshold", { threshold }) : t("shortlistQueue.score.no_threshold")}
        </Typography>
      </Stack>
    </Tooltip>
  );
}

/** Hard rules: flagged (with the plain reason) or all passed. */
export function KnockoutChip({ row }: { row: QueueRow }) {
  const t = useT();
  if (!row.knocked_out) {
    return matchScoreOf(row) == null ? <>—</> : <StatusChip tone="muted" emoji="check" label={t("shortlistQueue.knockout.passed")} />;
  }
  const reasons = row.knockout_reasons && row.knockout_reasons.length > 0 ? row.knockout_reasons : [t("shortlistQueue.knockout.no_reason")];
  return (
    <Stack spacing={0.5} alignItems="flex-start">
      <StatusChip tone="coral" emoji="warning" label={t("shortlistQueue.knockout.flagged")} />
      <Box>
        {reasons.map((reason) => (
          <Typography key={reason} variant="caption" color="text.secondary" sx={{ display: "block", maxWidth: 260 }}>
            {reason}
          </Typography>
        ))}
      </Box>
    </Stack>
  );
}
