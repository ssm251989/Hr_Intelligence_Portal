// Fix 2026-10-05 -- Settings > Company > Policies & handbook (backend/app/experience/ui_policies_router.py).
import { http } from "./client";

export type PolicyStatus = "processing" | "ready" | "failed";
export interface PolicyRow {
  id: string; title: string; category: string; version: string | null; status: PolicyStatus; effective_date: string | null;
  error: string | null; file_name: string | null; content_type: string | null; size_bytes: number | null; has_file: boolean;
  uploaded_by: string | null; created_at: string | null; processed_at: string | null;
  older_versions: { id: string; version: string | null; effective_date: string | null; file_name: string | null; has_file: boolean; created_at: string | null }[];
}
export interface PolicyList { policies: PolicyRow[]; ready: number; assistant_on: boolean; categories: string[]; max_mb: number }
export interface PolicyMeta { title?: string; category?: string; version?: string; effective_date?: string }

function form(file: File, meta: PolicyMeta): FormData {
  const f = new FormData();
  f.append("file", file);
  Object.entries(meta).forEach(([k, v]) => { if (v) f.append(k, v); });
  return f;
}

const BASE = "/api/v1/ui/policies";
export const policiesApi = {
  list: () => http.get<PolicyList>(BASE),
  upload: (file: File, meta: PolicyMeta) => http.postForm<PolicyRow>(BASE, form(file, meta)),
  newVersion: (id: string, file: File, meta: PolicyMeta) => http.postForm<PolicyRow>(`${BASE}/${id}/new-version`, form(file, meta)),
  update: (id: string, meta: PolicyMeta) => http.patch<PolicyRow>(`${BASE}/${id}`, meta),
  retry: (id: string) => http.post<PolicyRow>(`${BASE}/${id}/retry`, {}),
  remove: (id: string) => http.del<void>(`${BASE}/${id}`),
  file: (id: string) => http.fetchBlob(`${BASE}/${id}/file`),
  text: (id: string) => http.get<{ id: string; title: string; status: PolicyStatus; passages: { heading: string | null; text: string }[] }>(`${BASE}/${id}/text`),
  sample: () => http.fetchBlob(`${BASE}/sample`),
};
