import { http } from "./client";

// Part 15.4 Jobs screen helpers (backend/app/experience/ui_jobs_router.py).

export type JobStage = "new" | "screening" | "shortlisted" | "interview" | "offer" | "hired" | "not_selected" | "paused" | "dropped";

export const PIPELINE_STAGES: JobStage[] = ["new", "screening", "shortlisted", "interview", "offer", "hired"];

export interface JobPipelineRow {
  job_id: string;
  status: string;
  stages: Record<JobStage, number>;
  total: number;
  in_progress: number;
  hired: number;
  positions_count: number;
  positions_left: number;
  closes_on: string | null;
  days_to_close: number | null;
  auto_closed: { reason: "deadline" | "positions_filled"; at: string | null } | null;
  recycle?: { moves_on: string } | null;  // Part 21.1
}

export interface JobPipelineSummary {
  items: JobPipelineRow[];
  just_closed: string[];
  stages: JobStage[];
}

// Part 21.1: closed jobs and the Recycle bin
export interface BinnedJob { id: string; title: string; department: string | null; closed_on: string; moved_on: string; by: string | null;
  applications: number; deleted_permanently_on: string }

export const jobsExtraApi = {
  keepJob: (jobId: string) => http.post<{ ok: boolean }>(`/api/v1/ui/jobs/${jobId}/keep`, {}),
  jobsBin: () => http.get<{ items: BinnedJob[]; settings: { enabled: boolean; days: number; keep_in_pool: boolean; bin_days: number } }>("/api/v1/ui/jobs/recycle-bin"),
  restoreJob: (jobId: string) => http.post<{ applications: number }>(`/api/v1/ui/jobs/recycle-bin/${jobId}/restore`, {}),
  deleteJob: (jobId: string) => http.post<{ applications: number }>(`/api/v1/ui/jobs/recycle-bin/${jobId}/delete-permanently`, { confirm: "DELETE" }),
  pipelineSummary: () => http.get<JobPipelineSummary>("/api/v1/ui/jobs/pipeline-summary"),
  reopen: (jobId: string, payload: { application_deadline?: string | null; positions_count?: number | null }) =>
    http.post<{ job_id: string; status: string }>(`/api/v1/ui/jobs/${jobId}/reopen`, payload),
};
