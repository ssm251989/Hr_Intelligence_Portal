// Part 17.15 -- removing candidates: Recycle bin, restore, delete permanently
// (backend/app/experience/ui_candidate_removal_router.py + app/recruitment/removal.py).
import { http } from "./client";

export const REMOVAL_REASONS = ["duplicate", "test_data", "privacy_request", "withdrawn", "other"] as const;
export type RemovalReason = (typeof REMOVAL_REASONS)[number];

export interface DeleteSummary {
  candidates: number;
  applications: number;
  interviews: number;
  files: number;
  related_rows: Record<string, number>;
  blocked: string | null;
}

export interface RecycleBinItem {
  candidate_id: string;
  name: string | null;
  email: string | null;
  reason: RemovalReason | null;
  note: string | null;
  removed_by: string | null;
  removed_at: string;
  deleted_permanently_on: string;
  jobs: string[];
}

export interface RemovalRun {
  id: string;
  mode: "remove" | "delete";
  status: "running" | "finished" | "failed";
  total: number;
  done: number;
  skipped: { candidate_id: string | null; why: string }[];
  finished_at: string | null;
}

const base = "/api/v1/ui/candidates";

export const removalApi = {
  recycleBin: () => http.get<{ recycle_days: number; items: RecycleBinItem[] }>(`${base}/recycle-bin`),
  summary: (candidateId: string) => http.get<DeleteSummary>(`${base}/${candidateId}/delete-summary`),
  remove: (candidateId: string, body: { reason: RemovalReason; note?: string; confirm?: string }) =>
    http.post<{ removed?: boolean; deleted?: boolean; restore_until?: string }>(`${base}/${candidateId}/remove`, body),
  restore: (candidateId: string) => http.post<{ restored: boolean; applications?: number }>(`${base}/${candidateId}/restore`, {}),
  deletePermanently: (candidateId: string, body: { reason: RemovalReason; confirm: string }) =>
    http.post<{ deleted: boolean }>(`${base}/${candidateId}/delete-permanently`, body),
  bulk: (body: { candidate_ids: string[]; mode: "remove" | "delete"; reason: RemovalReason; note?: string; confirm?: string }) =>
    http.post<{ run_id: string; total: number; mode: "remove" | "delete" }>(`${base}/bulk-remove`, body),
  run: (runId: string) => http.get<RemovalRun>(`${base}/removal-runs/${runId}`),
};
