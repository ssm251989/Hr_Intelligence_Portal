import { ApiError, http } from "./client";

// Part 19.1 / 19.2: "Choose what you use" (backend/app/experience/modules_router.py) and the
// CTD Techs console's activation requests (backend/app/superadmin/router.py).

export type ModuleStatus = "active" | "pending" | "off";

export interface ModuleCard {
  key: string;
  emoji: string;
  name: string;
  line: string;
  gets: string[];
  needs: string[];
  ai: boolean;
  included: boolean; // GenAI usage: comes with any AI module, not chosen on its own
  pages: string[];
  status: ModuleStatus;
  requested_at: string | null;
  requested_by: string | null;
  activated_at: string | null;
  activated_by: string | null;
}

export interface ActivationRequestInfo {
  id: string;
  number: string | null; // ACT-2026-00012 -- quote it to CTD Techs
  modules: string[];
  status: "pending" | "expired" | "activated" | "cancelled" | "replaced";
  requested_at: string | null;
  requested_by: string | null;
  expires_at: string;
  email_sent: boolean;
  delivery: "sent" | "sending" | "not_sent"; // never the technical reason
  sent_at: string | null;
  first_sent_at: string | null;
  resend_count: number;
  resend_available_at: string | null;
  resends_left_today: number;
  locked_until: string | null;
  tries_left: number;
  support: { phone: string | null; email: string | null; hours: string | null };
}

export interface ModulesState {
  modules: ModuleCard[];
  request: ActivationRequestInfo | null;
  can_manage: boolean;
}

export const modulesApi19 = {
  list: () => http.get<ModulesState>("/api/v1/modules"),
  request: (modules: string[], withNeeds = false) =>
    http.post<ModulesState & { requested: ActivationRequestInfo }>("/api/v1/modules/request", { modules, with_needs: withNeeds }),
  activate: (code: string) => http.post<ModulesState & { activated: string[]; names: string }>("/api/v1/modules/activate", { code }),
  resend: () => http.post<ModulesState & { resent: ActivationRequestInfo }>("/api/v1/modules/request/resend"),
  cancelRequest: () => http.post<ModulesState>("/api/v1/modules/request/cancel"),
  off: (modules: string[], withDependents = false) =>
    http.post<ModulesState & { switched_off: string[] }>("/api/v1/modules/off", { modules, with_dependents: withDependents }),
};

/** {code, message, needs?, dependents?} from a 4xx of the endpoints above. */
export function moduleErrorDetail(err: unknown): { code?: string; message?: string; needs?: string[]; dependents?: string[] } | null {
  if (!(err instanceof ApiError) || !err.detail || typeof err.detail !== "object") return null;
  return err.detail as { code?: string; message?: string; needs?: string[]; dependents?: string[] };
}

/** Which module an app page belongs to (bootstrap.company_modules.pages). */
export function moduleKeyForPath(pathname: string, pages: Record<string, string[]> | undefined): string | null {
  for (const [key, list] of Object.entries(pages ?? {})) {
    if (list.some((p) => pathname === p || pathname.startsWith(p + "/"))) return key;
  }
  return null;
}

// ---- CTD Techs console ----

export interface ConsoleActivationRequest extends ActivationRequestInfo {
  tenant: string;
  company: string | null;
  installation: string | null;
  module_names: string;
  requested_by_name: string | null;
  emailed_to: string[];
  email_error: string | null;
  delivery_raw: "sending" | "sent" | "retrying" | "failed" | "not_actioned";
  current_priority: number | null;
  retry_count: number;
  next_retry_at: string | null;
  attention: boolean;
  has_code: boolean;
  activated_at: string | null;
  activated_by: string | null;
}

export interface ApproverRow { priority: number; name: string | null; email: string; active: boolean; updated_by: string | null; updated_at: string | null }

export interface MailboxHealth {
  ok: boolean;
  reason: string | null;
  mailbox: { host: string; port?: number; user?: string; starttls?: boolean; from_name?: string; from_address?: string; source: "hr_admin" | "console" | "env" | "none"; password_set: boolean; connection?: string; problem?: string };
  last: { ok: boolean; reason: string | null; at: string } | null;
}

export interface MailboxIn { host: string; port: number; user: string; starttls: boolean; from_name: string; from_address: string; password?: string | null }

export interface ConsoleActivationState {
  requests: ConsoleActivationRequest[];
  approvers: ApproverRow[];
  mailbox: MailboxHealth;
  settings: Record<string, string | number | boolean>;
}

export interface ActivationEventRow { at: string | null; kind: string; sent_to: string[]; by: string | null; status: "sent" | "failed" | "done"; reason: string | null }

// ---- Part 19.1: Screening against a pasted job description (no Jobs module needed) ----

export interface JdResult {
  candidate_id: string;
  name: string;
  email: string | null;
  location: string | null;
  match_score: number | null;
  recommendation: "strong_fit" | "possible_fit" | "weak_fit" | null;
  error: string | null;
}

export interface JdRun {
  id: string;
  title: string;
  jd_text: string;
  created_by: string | null;
  created_at: string | null;
  results: JdResult[];
}

export interface JdRunRow {
  id: string;
  title: string;
  created_by: string | null;
  created_at: string | null;
  candidates: number;
}

export const jdScreeningApi = {
  textFromFile: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http.postForm<{ text: string }>("/api/v1/ui/screening/jd/text", form);
  },
  run: (title: string, jdText: string, candidateIds?: string[]) =>
    http.post<JdRun>("/api/v1/ui/screening/jd", { title, jd_text: jdText, candidate_ids: candidateIds?.length ? candidateIds : null }),
  list: () => http.get<JdRunRow[]>("/api/v1/ui/screening/jd"),
  get: (id: string) => http.get<JdRun>(`/api/v1/ui/screening/jd/${id}`),
};
