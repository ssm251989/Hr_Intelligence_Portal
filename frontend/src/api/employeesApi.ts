// Part 20.1 -- the Employees tab (backend/app/experience/ui_employees_router.py).
import { http } from "./client";

export type EmpStatus = "active" | "notice" | "exited" | "absconded";
export type AppAccount = "active" | "invited" | "disabled" | "none";

export interface EmployeeRow {
  id: string; employee_code: string; name: string; first_name: string; last_name: string | null;
  designation: string | null; department: string | null; department_id: string | null; manager: string | null; manager_id: string | null;
  location: string | null; location_id: string | null; joined_on: string | null;
  experience_company_months: number | null; experience_company: string; previous_experience_months: number | null;
  experience_total_months: number | null; experience_total: string;
  company_email: string | null; company_email_test: boolean; phone: string | null; personal_email: string | null; employment_type: string | null;
  status: EmpStatus; raw_status: string; exited_on: string | null; app_account: AppAccount; login: string | null; user_id: string | null;
  roles: string[]; rehire_eligible: boolean | null; demo: boolean;
}
export interface EmployeeFacets { departments: { id: string; name: string }[]; locations: { id: string; name: string }[]; statuses: EmpStatus[]; roles: string[] }
export interface EmployeeList { items: EmployeeRow[]; facets: EmployeeFacets; test_mode: boolean; can_edit: boolean }
export interface EmployeeFilters { q?: string; department_id?: string; location_id?: string; status?: string; joined_from?: string; joined_to?: string; role?: string }

export interface EmployeeProfile extends EmployeeRow {
  personal: {
    first_name: string; last_name: string | null; preferred_name: string | null; dob: string | null; gender: string | null; personal_email: string | null;
    phone: string | null; addresses: Record<string, string>[]; emergency_contacts: Record<string, string>[]; pan: string | null; aadhaar: string | null;
    bank_account: string | null;
  };
  job: { designation: string | null; department: string | null; department_id: string | null; manager: string | null; manager_id: string | null;
    location: string | null; location_id: string | null; employment_type: string | null; joined_on: string | null; notice_period_days: number | null;
    grade: string | null; work_mode: string | null };
  documents: { kind: string; id: string; label: string; date: string | null; status?: string; expiry?: string | null }[];
  assets: { allocation_id: string; asset_id: string; tag: string; name: string; category_code: string | null; given_on: string | null;
    returned_on: string | null; condition: string | null; acknowledged: boolean }[];
  history: { at: string | null; action: string; actor: string | null; details: Record<string, unknown> | null }[];
  case_id: string | null; candidate_id: string | null; can_edit: boolean; test_mode: boolean;
}

export interface InviteResult { user_id: string; login: string; sent_to: string[]; email_status: string | null; link: string | null }
export interface IdFormat { prefix: string; padding: number; pattern: string; last_number: number; next_id: string }

const BASE = "/api/v1/ui/employees";
const qs = (f: Record<string, string | undefined>) => {
  const p = Object.entries(f).filter(([, v]) => v);
  return p.length ? `?${p.map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`).join("&")}` : "";
};

export const employeesApi = {
  list: (f: EmployeeFilters = {}) => http.get<EmployeeList>(`${BASE}${qs(f as Record<string, string | undefined>)}`),
  exportXlsx: (f: EmployeeFilters, columns: string[]) => http.fetchBlob(`${BASE}/export.xlsx${qs({ ...(f as Record<string, string | undefined>), columns: columns.join(",") })}`),
  get: (id: string) => http.get<EmployeeProfile>(`${BASE}/${id}`),
  update: (id: string, body: Record<string, unknown>) => http.patch<EmployeeProfile>(`${BASE}/${id}`, body),
  invite: (id: string) => http.post<InviteResult>(`${BASE}/${id}/invite`, {}),
  invites: (ids: string[]) => http.post<{ results: (Partial<InviteResult> & { id: string; name: string; error?: string })[] }>(`${BASE}/invites`, { ids }),
  inStock: (category?: string) => http.get<{ id: string; tag: string; name: string; category_code: string }[]>(`${BASE}/assets/in-stock${qs({ category })}`),
  giveAsset: (id: string, body: { asset_id?: string; category_code?: string; asset_tag?: string; name?: string; serial_number?: string }) =>
    http.post<{ allocation_id: string; tag: string; name: string }>(`${BASE}/${id}/assets`, body),
  returnAsset: (id: string, allocationId: string, condition: string, notes?: string) =>
    http.post<{ ok: boolean }>(`${BASE}/${id}/assets/${allocationId}/return`, { condition, notes }),
  idFormat: () => http.get<IdFormat>(`${BASE}/settings/id-format`),
  saveIdFormat: (prefix: string, padding: number) => http.put<IdFormat>(`${BASE}/settings/id-format`, { prefix, padding }),
};
