import { http } from "./client";

// Part 15.6 People (Core HR) screens. Read helpers live in backend/app/experience/ui_people_router.py
// (/api/v1/ui/people/*); every write goes to the existing Core HR API (/api/v1/core-hr/*).

export interface PersonRow {
  id: string;
  employee_code: string;
  name: string;
  first_name: string;
  last_name: string | null;
  status: string;
  worker_type: string;
  photo_url: string | null;
  designation?: string | null;
  department_id?: string | null;
  department?: string | null;
  location_id?: string | null;
  location?: string | null;
  manager_id?: string | null;
  manager_name?: string | null;
  grade?: string | null;
  work_mode?: string | null;
  joined_on?: string | null;
  work_email?: string | null;
  personal_email?: string | null;
  personal_phone?: string | null;
  skills?: string[] | string;
}

export interface PeopleList {
  items: PersonRow[];
  total: number;
  truncated: boolean;
}

export interface PeopleFilters {
  departments: { id: string; name: string; count: number }[];
  locations: { id: string; name: string; count: number }[];
  skills: { name: string; count: number }[];
  statuses: Record<string, number>;
  total: number;
}

export interface JobInfo {
  record_id?: string;
  effective_from?: string | null;
  effective_to?: string | null;
  event_type?: string;
  event_reason?: string | null;
  designation?: string | null;
  department_id?: string | null;
  department?: string | null;
  location_id?: string | null;
  location?: string | null;
  position_id?: string | null;
  position?: string | null;
  manager_id?: string | null;
  manager_name?: string | null;
  cost_center?: string | null;
  grade?: string | null;
  employment_type?: string | null;
  work_mode?: string | null;
  probation_end?: string | null;
  confirmation_date?: string | null;
  notice_period_days?: number | null;
  created_by?: string | null;
}

export interface PendingChange {
  id: string;
  event_type: string | null;
  effective_from: string | null;
  changes: string[];
  reason: string | null;
  requested_by: string | null;
  requested_at: string | null;
}

export type SensitiveField = "pan" | "aadhaar" | "passport" | "visa" | "driving_licence" | "bank_account";

export interface PersonDetail {
  id: string;
  employee_code: string;
  name: string;
  status: string;
  worker_type: string;
  photo_url: string | null;
  first_name: string;
  last_name: string | null;
  preferred_name?: string | null;
  pronouns?: string | null;
  dob?: string | null;
  gender?: string | null;
  marital_status?: string | null;
  nationality?: string | null;
  blood_group?: string | null;
  personal_email?: string | null;
  personal_phone?: string | null;
  work_email?: string | null;
  joined_on?: string | null;
  addresses?: unknown;
  emergency_contacts?: unknown;
  family?: unknown;
  education?: unknown;
  prior_employment?: unknown;
  skills?: unknown;
  certifications?: unknown;
  languages?: unknown;
  bank_verification_status?: string | null;
  custom_fields?: Record<string, unknown>;
}

export interface EmployeeSummary {
  person: PersonDetail;
  job: JobInfo | null;
  sensitive: Partial<Record<SensitiveField, { present: boolean; masked: string | null }>>;
  pending_changes: PendingChange[];
  direct_reports: number;
  can: {
    edit_job: boolean;
    edit_sensitive: boolean;
    reveal: boolean;
    view_history: boolean;
    letters_view: boolean;
    letters_create: boolean;
    add_document: boolean;
  };
}

export interface HistoryActivity {
  id: string;
  action: string;
  actor: string | null;
  at: string | null;
  field?: string | null;
  letter?: string | null;
  event_type?: string | null;
  applied?: boolean | null;
}

export interface EmployeeHistory {
  records: JobInfo[];
  activity: HistoryActivity[];
  pending_changes: PendingChange[];
}

export interface LetterTemplateOption {
  key: string;
  name: string;
  version: number;
}

export interface LetterRow {
  id: string;
  template_key: string;
  generated_at: string | null;
  verification_token: string;
}

export interface DocumentRow {
  id: string;
  type: string;
  issued_date: string | null;
  expiry_date: string | null;
  visibility: string;
}

export interface OrgHolder {
  employee_id: string;
  name: string;
  photo_url: string | null;
  status: string;
}

export interface OrgNode {
  id: string;
  code: string;
  title: string;
  status: string;
  is_critical: boolean;
  has_children: boolean;
  department?: string | null;
  location?: string | null;
  holders?: OrgHolder[];
  children_count?: number;
}

const qs = (params: Record<string, string | undefined | null>) => {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v) s.set(k, v);
  });
  const out = s.toString();
  return out ? `?${out}` : "";
};

export const peopleApi = {
  list: (params: { q?: string; status?: string; department_id?: string; location_id?: string; skill?: string; view?: "hr" | "directory" } = {}) =>
    http.get<PeopleList>(`/api/v1/ui/people/employees${qs(params)}`),
  filters: (view: "hr" | "directory" = "hr") => http.get<PeopleFilters>(`/api/v1/ui/people/filters?view=${view}`),
  summary: (id: string) => http.get<EmployeeSummary>(`/api/v1/ui/people/employees/${id}/summary`),
  history: (id: string) => http.get<EmployeeHistory>(`/api/v1/ui/people/employees/${id}/history`),
  letterTemplates: () => http.get<LetterTemplateOption[]>("/api/v1/ui/people/letter-templates"),
  letter: (letterId: string) => http.get<{ id: string; template_key: string; rendered_html: string; generated_at: string | null }>(`/api/v1/ui/people/letters/${letterId}`),
  orgChart: (rootPositionId?: string) => http.get<{ nodes: OrgNode[] }>(`/api/v1/ui/people/org-chart${qs({ root_position_id: rootPositionId })}`),
  /** The plain Core HR org chart (no position holders) -- fallback if the helper isn't available. */
  orgChartBasic: (rootPositionId?: string) =>
    http.get<OrgNode[]>(`/api/v1/core-hr/org-chart${qs({ root_position_id: rootPositionId })}`),

  // ---- writes: existing Core HR API ----
  /** Audited on the server: every reveal writes an audit entry. */
  reveal: (id: string, field: SensitiveField) => http.get<{ field: string; value: string | null }>(`/api/v1/core-hr/employees/${id}/encrypted-field/${field}`),
  setSensitive: (id: string, field: SensitiveField, value: string) => http.put<{ ok: boolean }>(`/api/v1/core-hr/employees/${id}/encrypted-field`, { field, value }),
  requestJobChange: (id: string, payload: { event_type: string; effective_from: string; changes: Record<string, unknown>; reason?: string }) =>
    http.post<{ applied: boolean; employment_record_id?: string; workflow_instance_id?: string }>(`/api/v1/core-hr/employees/${id}/lifecycle-events`, payload),
  documents: (id: string) => http.get<DocumentRow[]>(`/api/v1/core-hr/employees/${id}/documents`),
  addDocument: (id: string, payload: { doc_type: string; issued_date?: string; expiry_date?: string; visibility?: string }) =>
    http.post<{ id: string; type: string; expiry_date: string | null }>(`/api/v1/core-hr/employees/${id}/documents`, payload),
  letters: (id: string) => http.get<LetterRow[]>(`/api/v1/core-hr/employees/${id}/letters`),
  generateLetter: (id: string, templateKey: string, context: Record<string, unknown>) =>
    http.post<{ id: string; verification_token: string; rendered_html: string }>(`/api/v1/core-hr/employees/${id}/letters`, { template_key: templateKey, context }),
};

/** Skills may come back as a list, or as the masked marker when a role can't see them. */
export function skillList(v: PersonRow["skills"] | unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.map((s) => (typeof s === "string" ? s : (s as { skill?: string; name?: string })?.skill ?? (s as { name?: string })?.name ?? "")).filter(Boolean) as string[];
}
