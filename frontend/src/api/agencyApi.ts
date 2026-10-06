// Part 15.6 -- agency portal. HR side wraps /api/v1/agencies (Agencies page), agency side
// wraps /api/v1/agency-portal (the /agency page an agency's own users see).
// backend/app/recruitment/agency_router.py.
import { http } from "./client";

export interface AgencyRow {
  id: string;
  name: string;
  contact_email: string | null;
  notes: string | null;
  active: boolean;
  created_at: string | null;
  jobs: number;
  members: number;
  submissions: number;
  // Part 21.5
  agency_type: AgencyType; contact_person: string | null; phone: string | null; address: string | null; gst_pan: string | null;
  contract_start: string | null; contract_end: string | null; fee_type: string | null; fee_value: number | null; payment_terms: string | null;
  bgv_checks: { check: string; price: number | null }[]; turnaround_days: number | null; report_format: string | null;
}

export type AgencyType = "recruitment" | "bgv" | "both";
export const BGV_CHECKS = ["education", "employment", "address", "criminal", "identity", "reference", "drug"];
export interface AgencyInput {
  name: string; contact_email?: string | null; notes?: string | null; agency_type: AgencyType; contact_person?: string | null; phone?: string | null;
  address?: string | null; gst_pan?: string | null; contract_start?: string | null; contract_end?: string | null; fee_type?: string | null;
  fee_value?: number | null; payment_terms?: string | null; bgv_checks?: { check: string; price: number | null }[]; turnaround_days?: number | null;
  report_format?: string | null; active?: boolean;
}
export interface AgencyStats {
  recruitment?: { submitted: number; hired: number; fees_due: number; fees_unknown: number };
  bgv?: { cases: number; open: number; average_turnaround_days: number | null; overdue: number; cost_so_far: number };
}

export interface AgencyDetail extends AgencyRow {
  stats?: AgencyStats;
  job_list: { id: string; title: string; location: string | null; status: string; open: boolean }[];
  member_list: { user_id: string; email: string; full_name: string | null; added_at: string | null }[];
  submission_list: { application_id: string; candidate_id: string; candidate_name: string | null; job_title: string; status: string; submitted_at: string | null }[];
}

export interface InviteResult {
  user_id: string;
  email_sent: boolean;
  link: string | null;
}

export type AgencyStage = "received" | "shortlisted" | "interviewing" | "final_stages" | "offer" | "hired" | "not_selected" | "on_hold";

export interface PortalJob {
  id: string;
  title: string;
  department: string | null;
  location: string | null;
  job_type: string | null;
  experience_min_years: number | null;
  experience_max_years: number | null;
  positions: number | null;
  deadline: string | null;
  jd_text: string | null;
  sent: number;
}

export interface PortalMe {
  agency: { id: string; name: string; active: boolean };
  user: { full_name: string | null; email: string };
  jobs: PortalJob[];
}

export interface PortalSubmission {
  id: string;
  candidate_name: string | null;
  candidate_email: string | null;
  job_title: string;
  stage: AgencyStage;
  submitted_at: string | null;
  submitted_by: string | null;
}

const HR = "/api/v1/agencies";
const PORTAL = "/api/v1/agency-portal";

export const agencyApi = {
  list: (type?: "recruitment" | "bgv") => http.get<AgencyRow[]>(`${HR}${type ? `?agency_type=${type}` : ""}`),
  create: (payload: AgencyInput) => http.post<AgencyRow>(HR, payload),
  update: (id: string, payload: Partial<AgencyInput>) => http.patch<AgencyRow>(`${HR}/${id}`, payload),
  importSample: () => http.fetchBlob(`${HR}/import-sample`),
  importFile: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http.postForm<{ results: { row: number; name: string; result: string; error?: string }[] }>(`${HR}/import`, form);
  },
  detail: (id: string) => http.get<AgencyDetail>(`${HR}/${id}`),
  setJobs: (id: string, jobIds: string[]) => http.put<{ jobs: number }>(`${HR}/${id}/jobs`, { job_ids: jobIds }),
  invite: (id: string, payload: { email: string; full_name?: string }) => http.post<InviteResult>(`${HR}/${id}/members`, payload),
  removeMember: (id: string, userId: string) => http.del<void>(`${HR}/${id}/members/${userId}`),
};

export const agencyPortalApi = {
  me: () => http.get<PortalMe>(`${PORTAL}/me`),
  submissions: () => http.get<PortalSubmission[]>(`${PORTAL}/submissions`),
  submit: (payload: { jobId: string; fullName: string; email: string; phone?: string; consent: boolean; resume: File }) => {
    const form = new FormData();
    form.append("job_id", payload.jobId);
    form.append("full_name", payload.fullName);
    form.append("email", payload.email);
    if (payload.phone) form.append("phone", payload.phone);
    form.append("consent_confirmed", String(payload.consent));
    form.append("resume", payload.resume);
    return http.postForm<{ id: string; application_id: string; stage: AgencyStage }>(`${PORTAL}/submit`, form);
  },
};
