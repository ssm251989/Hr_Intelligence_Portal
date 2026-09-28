import { ApiError, http } from "./client";
import type { UUID } from "./types";

// Part 17.8: the Salary queue (HR, signed in) and the candidate's own
// "Salary & joining details" form (public magic link, no login -> never sends the auth header).

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type SalaryChip = "waiting_for_candidate" | "in_band" | "needs_approval" | "flagged" | "approved" | "declined" | "no_band";
export const SALARY_CHIPS: SalaryChip[] = ["waiting_for_candidate", "needs_approval", "flagged", "in_band", "no_band", "approved", "declined"];

export interface SalaryCheck {
  state?: "waiting" | "in_band" | "needs_approval" | "flagged" | "no_band";
  expected?: number | null;
  current?: number | null;
  notice_days?: number | null;
  band_min?: number | null;
  band_max?: number | null;
  margin_pct?: number | null;
  position_pct?: number | null;
  over_pct?: number | null;
  suggestion?: number | null;
  missing?: string[];
  checked_at?: string;
}

export interface SalaryFormStatus {
  sent_at: string | null;
  answered_at: string | null;
  reminded: boolean;
}

export interface SalaryQueueItem {
  application_id: UUID;
  candidate_id: UUID;
  candidate_name: string | null;
  job_title: string;
  job_id: UUID;
  status: string;
  chip: SalaryChip;
  check: SalaryCheck;
  current_ctc: number | null;
  expected_ctc: number | null;
  notice_period_days: number | null;
  approved_salary: number | null;
  form: SalaryFormStatus | null;
}

export interface SalaryQueue {
  items: SalaryQueueItem[];
  counts: Partial<Record<SalaryChip, number>>;
  total: number;
}

export interface SalaryFigures {
  current_ctc?: number;
  expected_ctc?: number;
  notice_period_days?: number;
  willing_to_relocate?: boolean;
}

export const salaryQueueApi = {
  queue: (params: { state?: string; jobId?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.state) q.set("state", params.state);
    if (params.jobId) q.set("job_id", params.jobId);
    const qs = q.toString();
    return http.get<SalaryQueue>(`/api/v1/ui/salary/queue${qs ? `?${qs}` : ""}`);
  },
  sendForm: (applicationId: UUID) => http.post<{ sent: boolean; link?: string | null; reason?: string }>(`/api/v1/ui/salary/applications/${applicationId}/send-form`),
  setFigures: (applicationId: UUID, figures: SalaryFigures) => http.put<SalaryCheck>(`/api/v1/ui/salary/applications/${applicationId}/figures`, figures),
  recheck: (applicationId: UUID) => http.post<SalaryCheck>(`/api/v1/ui/salary/applications/${applicationId}/check`),
};

// ---- public form (no login) ----

async function publicRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { ...init, headers: { "Content-Type": "application/json" } });
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
  return response.json() as Promise<T>;
}

export interface SalaryFormView {
  candidate_first_name: string;
  job_title: string;
  current_ctc: number | null;
  expected_ctc: number | null;
  notice_period_days: number | null;
  willing_to_relocate: boolean | null;
  ask_offers?: boolean; // Part 18.12
  ask_payslip?: boolean;
  payslips?: number;
}

export interface SalaryFormAnswers {
  current_ctc: number;
  expected_ctc: number;
  notice_period_days: number;
  willing_to_relocate?: boolean | null;
  earliest_joining_date?: string | null;
  offers_in_hand?: number | null; // Part 18.12
  best_offer_ctc?: number | null;
}

const enc = encodeURIComponent;

export const salaryFormApi = {
  view: (token: string) => publicRequest<SalaryFormView>(`/api/v1/public/salary-details/${enc(token)}`),
  submit: (token: string, answers: SalaryFormAnswers) =>
    publicRequest<{ ok: boolean }>(`/api/v1/public/salary-details/${enc(token)}`, { method: "POST", body: JSON.stringify(answers) }),
  // Part 18.12: optional payslip (PDF/PNG/JPG, 5 MB)
  payslip: async (token: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${BASE_URL}/api/v1/public/salary-details/${enc(token)}/payslip`, { method: "POST", body: form });
    if (!response.ok) {
      let detail: unknown = response.statusText;
      try { detail = (await response.json()).detail; } catch { /* keep status text */ }
      throw new ApiError(response.status, detail);
    }
    return response.json() as Promise<{ uploaded: boolean; count: number }>;
  },
};

/** "1200000" -> "12,00,000" (Indian grouping) for the helper line under a money field. */
export function indianNumber(raw: string | number | null | undefined): string {
  if (raw == null || raw === "") return "";
  const n = Number(raw);
  if (Number.isNaN(n)) return "";
  return n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
