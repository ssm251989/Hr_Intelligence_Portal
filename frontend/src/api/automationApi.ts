import { ApiError, http } from "./client";
import type { UUID } from "./types";

// Part 17.13: talent pool re-match, job health, system health (staff) and the candidate's
// own status page (public -- no login, no auth header).

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface TalentPoolItem {
  candidate_id: UUID;
  name: string | null;
  location: string | null;
  score: number;
  knocked_out: boolean;
  years: number | null;
  last_seen: string | null;
}

export interface TalentPoolResponse {
  job_id?: UUID;
  threshold: number;
  checked: number;
  matching: number;
  items: TalentPoolItem[];
}

export interface AddedFromPool {
  application_id: UUID;
  status: string;
  score: number | null;
}

export interface JobHealthRow {
  job_id: UUID;
  title: string;
  applicants_7d: number;
  applicants_total: number;
  age_days: number;
  healthy: boolean;
  issues: { kind: string; text: string }[];
  suggestions: string[];
}

export type HealthLight = "green" | "amber" | "red";

export interface SystemHealthItem {
  key: string;
  status: HealthLight;
  message: string;
  checked_at: string;
  detail: Record<string, unknown>;
}

export interface SystemHealth {
  overall: HealthLight;
  checked_at: string;
  items: SystemHealthItem[];
}

export type StatusStepKey = "applied" | "reviewed" | "shortlisted" | "interview" | "offer" | "joined";
export type StatusStepState = "done" | "current" | "todo" | "closed";

export interface CandidateStatusView {
  first_name: string;
  job_title: string;
  steps: { key: StatusStepKey; state: StatusStepState }[];
  closed: boolean;
  applied_on: string | null;
}

const enc = encodeURIComponent;

export const automationApi = {
  talentPool: (jobId: UUID) => http.get<TalentPoolResponse>(`/api/v1/ui/jobs/${enc(jobId)}/talent-pool`),
  addFromPool: (jobId: UUID, candidateId: UUID) => http.post<AddedFromPool>(`/api/v1/ui/jobs/${enc(jobId)}/talent-pool/${enc(candidateId)}`),
  jobsHealth: () => http.get<JobHealthRow[]>("/api/v1/ui/jobs-health"),
  systemHealth: (fresh = false) => http.get<SystemHealth>(`/api/v1/ui/system-health${fresh ? "?fresh=true" : ""}`),
};

// ---- public (no login): the candidate's own progress page ----

export async function fetchCandidateStatus(token: string): Promise<CandidateStatusView> {
  const response = await fetch(`${BASE_URL}/api/v1/public/status/${enc(token)}`, { headers: { "Content-Type": "application/json" } });
  if (!response.ok) {
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail ?? body;
    } catch {
      detail = response.statusText;
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<CandidateStatusView>;
}
