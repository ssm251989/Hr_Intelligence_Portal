import { useEffect, useState } from "react";

import { metadataApi } from "../../api/client";
import { isMissingEndpoint, screeningExtraApi, type RejectReason, type ScoreCounts, type ScoreListParams, type ScreeningDetail } from "../../api/screeningExtra";
import { useI18n } from "../../i18n";
import { en as screeningEn } from "../../i18n/pages/screening";

export interface RejectReasonOption {
  code: string;
  /** What gets saved on the decision (the company's own wording). */
  value: string;
  /** What the user sees, in their language. */
  label: string;
}

/** Score breakdown + evidence for the rows on screen (one request per page). Empty map if unavailable. */
export function useScreeningDetails(applicationIds: string[], refreshKey = 0): Map<string, ScreeningDetail> {
  const [map, setMap] = useState<Map<string, ScreeningDetail>>(new Map());
  const key = applicationIds.join(",");
  useEffect(() => {
    if (!key) {
      setMap(new Map());
      return;
    }
    let alive = true;
    screeningExtraApi
      .details(key.split(","))
      .then((rows) => alive && setMap(new Map(rows.map((r) => [r.application_id, r]))))
      .catch(() => alive && setMap(new Map()));
    return () => {
      alive = false;
    };
  }, [key, refreshKey]);
  return map;
}

/** Histogram of scores for the slider's live "N candidates pass"; null when unavailable. */
export function useScoreCounts(params: Parameters<typeof screeningExtraApi.scoreCounts>[0] | null, refreshKey = 0): ScoreCounts | null {
  const [counts, setCounts] = useState<ScoreCounts | null>(null);
  const key = params ? JSON.stringify(params) : "";
  useEffect(() => {
    if (!key) return;
    let alive = true;
    screeningExtraApi
      .scoreCounts(JSON.parse(key) as Omit<ScoreListParams, "page">)
      .then((c) => alive && setCounts(c))
      .catch(() => alive && setCounts(null));
    return () => {
      alive = false;
    };
  }, [key, refreshKey]);
  return counts;
}

// Last-resort list, only when neither the company's master nor the helper endpoint answers.
const FALLBACK_CODES = ["skills_gap", "experience_low", "experience_high", "salary_mismatch", "location", "notice_period", "role_filled", "other"];

/** S7: the company's Rejection Reason master list, labels in the user's language. */
export function useRejectReasons(t: (key: string) => string): { reasons: RejectReasonOption[]; loading: boolean } {
  const { locale } = useI18n();
  const [raw, setRaw] = useState<RejectReason[] | null>(null);
  useEffect(() => {
    let alive = true;
    screeningExtraApi
      .rejectReasons()
      .then((r) => alive && setRaw(r))
      .catch(async (err) => {
        if (!isMissingEndpoint(err)) {
          if (alive) setRaw([]);
          return;
        }
        try {
          const values = await metadataApi.masterValues("rejection_reason");
          if (alive) setRaw(values.map((v) => ({ code: v.code, label: v.label_i18n.en ?? v.code, label_i18n: v.label_i18n })));
        } catch {
          if (alive) setRaw([]);
        }
      });
    return () => {
      alive = false;
    };
  }, []);
  const english = screeningEn as Record<string, string>;
  const list: RejectReason[] =
    raw && raw.length > 0 ? raw : FALLBACK_CODES.map((code) => ({ code, label: english[`screening.reject_reason.${code}`] ?? code }));
  const reasons = list.map((r) => {
    const key = `screening.reject_reason.${r.code}`;
    const own = r.label_i18n?.[locale];
    // Company-named reasons keep their own wording; the built-in starter list is translated.
    const label = own || (!r.label_i18n?.en && key in english ? t(key) : r.label);
    return { code: r.code, value: r.label, label };
  });
  return { reasons, loading: raw === null };
}
