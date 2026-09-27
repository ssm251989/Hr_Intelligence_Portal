// Part 17.5/17.6: scoring rules (company default + per-job), live preview, versions, recalculation
// progress, export/import, "Why this score" and the shortlisting rules. See
// backend/app/recruitment/scoring/api_router.py.
import { http } from "./client";

const BASE = "/api/v1/scoring";

export type FactorKey =
  | "skills_ai" | "must_have" | "nice_to_have" | "experience" | "domain" | "location" | "notice" | "salary"
  | "education" | "certifications" | "stability" | "recent_skills" | "languages" | "custom";

export const FACTOR_KEYS: FactorKey[] = [
  "skills_ai", "must_have", "nice_to_have", "experience", "domain", "location", "notice", "salary",
  "education", "certifications", "stability", "recent_skills", "languages", "custom",
];

export type KnockoutType = "must_have_skill" | "max_notice_days" | "location_in" | "min_experience" | "max_expected_salary";
export const KNOCKOUT_TYPES: KnockoutType[] = ["must_have_skill", "max_notice_days", "location_in", "min_experience", "max_expected_salary"];

export interface FactorRule {
  enabled: boolean;
  weight: number;
  params: Record<string, unknown>;
}

export interface Knockout {
  type: KnockoutType;
  skill?: string;
  days?: number | null;
  places?: string[];
  allow_relocation?: boolean;
  years?: number | null;
  amount?: number | null;
}

export interface ScoringRules {
  factors: Record<string, FactorRule>;
  knockouts: Knockout[];
  shortlist_threshold: number | null;
}

export interface ScoringCatalog {
  factors: { key: FactorKey; name: string }[];
  knockout_types: KnockoutType[];
  presets: { key: string; name: string; rules: ScoringRules }[];
  company_threshold: number;
}

export interface RuleVersion {
  id: string;
  version: number;
  note: string | null;
  created_by: string | null;
  created_at: string | null;
}

export interface RulesResponse {
  rules: ScoringRules;
  source: "job" | "company" | "preset";
  version: number | null;
  threshold: number;
  threshold_from: "job" | "company";
  versions: RuleVersion[];
  can_edit: boolean;
}

export interface RecalcRun {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  total: number;
  done: number;
  changed: number;
  error: string | null;
}

export interface SaveResponse {
  version: number;
  id: string;
  run: RecalcRun;
}

export interface FactorBreakdown {
  key: string;
  name: string;
  weight: number;
  score: number;
  value: string | null;
  points: number;
  evidence: string[];
  known: boolean;
}

export interface KnockoutResult {
  type: string;
  label: string;
  passed: boolean;
  reason: string;
}

export interface PreviewCandidate {
  application_id: string;
  candidate_name: string | null;
  current_score: number | null;
  new_score: number;
  knocked_out: boolean;
  above_threshold: boolean;
  factors: FactorBreakdown[];
}

export interface PreviewResponse {
  threshold: number;
  weights_total: number;
  candidates: PreviewCandidate[];
}

export interface WhyThisScore {
  score: number | null;
  stored_score: number | null;
  threshold: number;
  threshold_from: "job" | "company";
  above_threshold: boolean;
  knocked_out: boolean;
  rules_version: number | null;
  rules_scope: "job" | "company" | "preset";
  scored_at: string | null;
  not_saved?: boolean;
  factors: FactorBreakdown[];
  knockouts: KnockoutResult[];
}

export interface ShortlistingRules {
  auto_shortlist: boolean;
  threshold: number | null;
  max_size: number;
  undo_hours: number;
  notify: string[];
  own: Record<string, unknown> | null;
  company_threshold: number;
}

export interface ShortlistingIn {
  auto_shortlist?: boolean;
  threshold?: number | null;
  max_size?: number;
  undo_hours?: number;
  notify?: string[];
  use_company?: boolean;
}

const q = (jobId?: string | null) => (jobId ? `?job_id=${encodeURIComponent(jobId)}` : "");

export const scoringApi = {
  catalog: () => http.get<ScoringCatalog>(`${BASE}/catalog`),
  rules: (jobId?: string | null) => http.get<RulesResponse>(`${BASE}/rules${q(jobId)}`),
  save: (rules: ScoringRules, note: string | null, jobId?: string | null) =>
    http.put<SaveResponse>(`${BASE}/rules${q(jobId)}`, { rules, note: note || null }),
  revert: (version: number, jobId?: string | null) => http.post<SaveResponse>(`${BASE}/rules/revert`, { version, job_id: jobId || null }),
  useCompany: (jobId: string) => http.del<{ removed: number; run: RecalcRun }>(`${BASE}/rules${q(jobId)}`),
  balance: (rules: ScoringRules) => http.post<{ rules: ScoringRules }>(`${BASE}/balance`, { rules }),
  preview: (jobId: string, rules: ScoringRules, applicationIds?: string[]) =>
    http.post<PreviewResponse>(`${BASE}/preview`, { job_id: jobId, rules, application_ids: applicationIds ?? [] }),
  run: (runId: string) => http.get<RecalcRun>(`${BASE}/runs/${runId}`),
  exportFile: (format: "json" | "xlsx", jobId?: string | null) =>
    http.fetchBlob(`${BASE}/export?format=${format}${jobId ? `&job_id=${encodeURIComponent(jobId)}` : ""}`),
  importFile: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http.postForm<{ rules: ScoringRules }>(`${BASE}/import`, form);
  },
  why: (applicationId: string) => http.get<WhyThisScore>(`${BASE}/applications/${applicationId}/why`),
  shortlisting: (jobId?: string | null) => http.get<ShortlistingRules>(`${BASE}/shortlisting${q(jobId)}`),
  saveShortlisting: (payload: ShortlistingIn, jobId?: string | null) => http.put<ShortlistingRules>(`${BASE}/shortlisting${q(jobId)}`, payload),
};

/** Save a Blob as a file in the browser. */
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
