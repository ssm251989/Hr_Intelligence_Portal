// Part 15.4: the restyled Screening / Shortlisting pages' extra reads (backend
// app/experience/ui_screening_router.py). Every caller falls back to the original endpoints
// when these aren't available, so the pages keep working exactly as before.
import { ApiError, http } from "./client";
import type { CandidatesListPage, ShortlistStatus, UUID } from "./types";

const BASE = "/api/v1/ui/screening";

export interface ScoreListParams {
  scope: "screening" | "shortlisting";
  sort?: "score" | "newest";
  page?: number;
  pageSize?: number;
  search?: string;
  jobRoleId?: UUID;
  status?: string;
  shortlistStatus?: ShortlistStatus;
  source?: string;
  location?: string;
  experienceMin?: number;
  experienceMax?: number;
  appliedAfter?: string;
  appliedBefore?: string;
  matchScoreMin?: number;
  matchScoreMax?: number;
}

function query(params: Partial<ScoreListParams>): URLSearchParams {
  const q = new URLSearchParams();
  const map: [keyof ScoreListParams, string][] = [
    ["scope", "scope"], ["sort", "sort"], ["page", "page"], ["pageSize", "page_size"], ["search", "search"],
    ["jobRoleId", "job_role_id"], ["status", "status"], ["shortlistStatus", "shortlist_status"], ["source", "source"],
    ["location", "location"], ["experienceMin", "experience_min"], ["experienceMax", "experience_max"],
    ["appliedAfter", "applied_after"], ["appliedBefore", "applied_before"], ["matchScoreMin", "match_score_min"],
    ["matchScoreMax", "match_score_max"],
  ];
  for (const [key, name] of map) {
    const value = params[key];
    if (value !== undefined && value !== null && value !== "") q.set(name, String(value));
  }
  return q;
}

export interface ScoreCounts {
  total: number;
  scored: number;
  /** counts[s] = candidates whose rounded score is exactly s (0..100). */
  counts: number[];
}

export type ScoreFactor = "skills" | "experience" | "location" | "certificates" | "resume_match";

export interface EvidenceLine {
  kind: "skill" | "experience" | "certificate" | "education" | "gap";
  text: string;
}

export interface AutoShortlistInfo {
  at: string;
  undo_until: string;
  can_undo: boolean;
  recruiter_notified: boolean;
  notified_to?: string | null;
  breakdown: Partial<Record<ScoreFactor, number | null>>;
  undone: boolean;
}

export interface ScreeningDetail {
  application_id: UUID;
  score: number | null;
  recommendation: string | null;
  breakdown: Partial<Record<ScoreFactor, number | null>>;
  matched_skills: string[];
  missing_skills: string[];
  missing_required_skills: string[];
  experience_years: number | null;
  current_title: string | null;
  evidence: EvidenceLine[];
  screened_at: string | null;
  auto_shortlist?: AutoShortlistInfo | null;
}

export interface RejectReason {
  code: string;
  label: string;
  label_i18n?: Record<string, string>;
}

/** True when the helper endpoints aren't there yet (router not registered) -- callers fall back. */
export function isMissingEndpoint(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 405);
}

export const screeningExtraApi = {
  list: (params: ScoreListParams) => http.get<CandidatesListPage>(`${BASE}/list?${query(params).toString()}`),
  scoreCounts: (params: Omit<ScoreListParams, "page" | "pageSize" | "sort" | "matchScoreMin" | "matchScoreMax">) =>
    http.get<ScoreCounts>(`${BASE}/score-counts?${query(params).toString()}`),
  details: (applicationIds: UUID[]) => {
    const q = new URLSearchParams();
    applicationIds.slice(0, 50).forEach((id) => q.append("application_ids", id));
    return http.get<ScreeningDetail[]>(`${BASE}/details?${q.toString()}`);
  },
  rejectReasons: () => http.get<RejectReason[]>(`${BASE}/reject-reasons`),
  undoAutoShortlist: (applicationId: UUID) =>
    http.post<{ application_id: UUID; status: string }>(`${BASE}/applications/${applicationId}/undo-auto-shortlist`),
};

/** Count of candidates scoring at or above `min` (and at or below `max`) from a histogram. */
export function passCount(counts: number[] | undefined, min: number, max = 100): number {
  if (!counts) return 0;
  let n = 0;
  for (let s = Math.max(0, Math.ceil(min)); s <= Math.min(100, Math.floor(max)); s++) n += counts[s] ?? 0;
  return n;
}
