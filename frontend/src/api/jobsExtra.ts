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
}

export interface JobPipelineSummary {
  items: JobPipelineRow[];
  just_closed: string[];
  stages: JobStage[];
}

export const jobsExtraApi = {
  pipelineSummary: () => http.get<JobPipelineSummary>("/api/v1/ui/jobs/pipeline-summary"),
  reopen: (jobId: string, payload: { application_deadline?: string | null; positions_count?: number | null }) =>
    http.post<{ job_id: string; status: string }>(`/api/v1/ui/jobs/${jobId}/reopen`, payload),
};
