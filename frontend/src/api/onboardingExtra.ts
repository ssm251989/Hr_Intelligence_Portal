import { ApiError, http } from "./client";
import type { UUID } from "./types";

// Part 15.6: Onboarding HR dashboard + pre-joiner portal (/welcome).
// HR calls use the signed-in helpers; the portal calls below use a plain fetch with NO
// staff Authorization header -- the joiner is identified only by their portal link, and a
// 401 there must never sign a staff user (sharing the browser) out.

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// ---- HR ----

export interface JoinerCard {
  case_id: UUID;
  name: string;
  email: string;
  role: string | null;
  department: string | null;
  candidate_id: UUID | null;
  joining_date: string;
  days_to_join: number;
  status: string;
  readiness_percent: number;
  readiness: { done: number; total: number };
  not_ready_soon: boolean;
  documents_waiting: number;
  overdue_tasks: number;
  has_plan: boolean;
  link_expires_at: string | null;
  link_expired: boolean;
  can_mark_joined: boolean;
  // fix 2026-10-05: the stage and exactly the actions the server accepts (backend joiner_stage.py)
  stage: JoinerStage;
  allowed_actions: JoinerActionKey[];
}

export type JoinerStage = "before_joining" | "joining_due" | "joined" | "closed";
export type JoinerActionKey = "withdraw_offer" | "candidate_declined" | "mark_joined" | "no_show" | "not_reporting" | "stop_not_reporting"
  | "absconded" | "resigned" | "terminated";
export type ExitKind = "absconded" | "resigned" | "terminated";

export interface RecentJoiner {
  case_id: UUID;
  name: string;
  email: string;
  role: string | null;
  department: string | null;
  candidate_id: UUID | null;
  joining_date: string;
  days_since_joining: number;
  status: string;
  stage: JoinerStage;
  allowed_actions: JoinerActionKey[];
  not_reporting: { status: string; last_seen: string; notices: string[] } | null;
}

export interface JoinerReasons {
  declined: Record<string, string>;
  no_show: Record<string, string>;
  exit: Record<ExitKind, Record<string, string>>;
}

export interface DropoutRow { key: string; offer_dropout: number; no_show: number; early_leaver: number; absconding: number; total: number }
export interface DropoutReport {
  since: string | null;
  early_days: number;
  totals: { offer_dropout: number; no_show: number; early_leaver: number; absconding: number };
  by_job: DropoutRow[];
  by_department: DropoutRow[];
  by_recruiter: DropoutRow[];
  by_reason: DropoutRow[];
  rows: { category: string; kind: string; job: string; department: string; recruiter: string; reason: string; date: string | null; name: string;
          application_id: string | null; days_after_joining: number | null }[];
}

export interface WaitingDocument {
  id: UUID;
  case_id: UUID;
  name: string;
  document_type: string;
  label: string;
  uploaded_at: string | null;
  extracted: Record<string, unknown> | null;
}

export interface OverdueTaskRow {
  id: UUID;
  case_id: UUID | null;
  name: string;
  title: string;
  owner_role: string;
  due_date: string;
  days_late: number;
  status: string;
}

export interface ReadyOffer {
  offer_id: UUID;
  name: string;
  email: string;
  role: string | null;
  joining_date: string | null;
}

export interface OnboardingBoard {
  today: string;
  cards: JoinerCard[];
  recent_joiners: RecentJoiner[];
  documents_waiting: WaitingDocument[];
  overdue_tasks: OverdueTaskRow[];
  digest: { enabled: boolean; last_found_at: string | null; reminders_waiting: number };
  ready_offers: ReadyOffer[];
  can: { create: boolean; edit: boolean; approve: boolean; tasks: boolean; plans: boolean };
}

export interface WelcomeContent {
  message: string | null;
  buddy: { name: string; title: string | null; note: string | null; email: string | null } | null;
  agenda: { time: string | null; title: string; emoji: string | null }[];
}

export interface PlanTask {
  id: UUID;
  key: string;
  title: string;
  kind: string;
  owner_role: string;
  due_date: string;
  status: string;
  depends_on: string[];
}

export interface JoinerDetail {
  case_id: UUID;
  name: string;
  first_name: string;
  role: string | null;
  department: string | null;
  email: string;
  joining_date: string;
  status: string;
  readiness_percent: number;
  readiness: { done: number; total: number };
  checklist: { kind: "form" | "document" | "policy"; code: string; label: string; done: boolean; status?: string }[];
  documents: { id: UUID; document_type: string; label: string; status: string; rejection_reason: string | null; uploaded_at: string | null; has_file: boolean }[];
  tasks: PlanTask[];
  history: { event: string; at: string | null; actor: string | null; reason: string | null; old: string | null; new: string | null }[];
  welcome: WelcomeContent;
  link_expires_at: string | null;
  joining_details?: JoiningDetailsHr | null;
}

export interface PlanTemplateRow {
  id: UUID;
  code: string;
  name: string;
  is_active: boolean;
}

export const onboardingExtraApi = {
  board: (lang: string) => http.get<OnboardingBoard>(`/api/v1/ui/onboarding/board?lang=${encodeURIComponent(lang)}`),
  detail: (caseId: UUID, lang: string) => http.get<JoinerDetail>(`/api/v1/ui/onboarding/cases/${caseId}/detail?lang=${encodeURIComponent(lang)}`),
  documentFile: (documentId: UUID) => http.fetchBlob(`/api/v1/ui/onboarding/documents/${documentId}/file`),
  saveWelcome: (caseId: UUID, payload: WelcomeContent) => http.put<WelcomeContent>(`/api/v1/ui/onboarding/cases/${caseId}/welcome`, payload),
  // change 2026-10-05: joining details -- remind / lock, and the form settings
  remindDetails: (caseId: UUID) => http.post<{ sent: boolean; status: string; missing: string[] }>(`/api/v1/ui/onboarding/cases/${caseId}/joining-details/remind`, {}),
  lockDetails: (caseId: UUID, locked: boolean) => http.post<JoiningDetailsHr>(`/api/v1/ui/onboarding/cases/${caseId}/joining-details/lock`, { locked }),
  joiningForm: () => http.get<JoiningFormSettings>("/api/v1/ui/onboarding/joining-form"),
  saveJoiningForm: (body: { fields: Record<string, { show: FieldShow; help: Record<string, string>; check: boolean }>; documents: Record<string, FieldShow> }) =>
    http.put<JoiningFormSettings>("/api/v1/ui/onboarding/joining-form", body),
  revertJoiningForm: (version: number) => http.post<JoiningFormSettings>("/api/v1/ui/onboarding/joining-form/revert", { version }),

  // existing /api/v1/onboarding endpoints not wrapped in client.ts
  createCase: (payload: { email?: string; first_name?: string; last_name?: string; joining_date?: string; offer_id?: UUID }) =>
    http.post<{ id: UUID; portal_token: string }>("/api/v1/onboarding/cases", payload),
  changeJoiningDate: (caseId: UUID, joiningDate: string, reason?: string) =>
    http.post<{ id: UUID }>(`/api/v1/onboarding/cases/${caseId}/joining-date`, { joining_date: joiningDate, reason }),
  noShow: (caseId: UUID, body: { reason_code: string; notes?: string; contacted_on?: string | null }) =>
    http.post<{ id: UUID }>(`/api/v1/onboarding/cases/${caseId}/no-show`, body),
  revoke: (caseId: UUID, body: { reason: string; notes?: string }) => http.post<{ id: UUID }>(`/api/v1/onboarding/cases/${caseId}/revoke`, body),
  // fix 2026-10-05: the rest of the joiner actions
  declined: (caseId: UUID, body: { reason_code: string; notes?: string }) => http.post<{ id: UUID }>(`/api/v1/onboarding/cases/${caseId}/declined`, body),
  notReporting: (caseId: UUID, body: { last_seen: string; notes?: string }) => http.post<unknown>(`/api/v1/onboarding/cases/${caseId}/not-reporting`, body),
  stopNotReporting: (caseId: UUID, note: string) => http.post<unknown>(`/api/v1/onboarding/cases/${caseId}/not-reporting/stop`, { note }),
  recordExit: (caseId: UUID, body: { kind: ExitKind; last_working_day: string; reason_code: string; notes: string; rehire_eligible: boolean; confirm: true }) =>
    http.post<{ separation_id: string; clearance: { title: string; kind: string }[] }>(`/api/v1/onboarding/cases/${caseId}/exit`, body),
  joinerReasons: () => http.get<JoinerReasons>(`/api/v1/onboarding/joiner-reasons`),
  dropoutReport: (since?: string) => http.get<DropoutReport>(`/api/v1/onboarding/dropout-report${since ? `?since=${since}` : ""}`),
  rotateLink: (caseId: UUID) => http.post<{ portal_token: string; expires_at: string }>(`/api/v1/onboarding/cases/${caseId}/rotate-token`),
  convert: (caseId: UUID) => http.post<{ employee_code: string; already_converted: boolean }>(`/api/v1/onboarding/cases/${caseId}/convert`, { confirm_joined: true }),
  verifyDocument: (documentId: UUID, approve: boolean, reason?: string) =>
    http.post<{ id: UUID; status: string }>(`/api/v1/onboarding/documents/${documentId}/verify`, { approve, reason }),
  completeTask: (taskId: UUID, skip = false) => http.post<PlanTask>(`/api/v1/onboarding/tasks/${taskId}/complete`, { skip }),
  planTemplates: () => http.get<PlanTemplateRow[]>("/api/v1/onboarding/plan-templates"),
  generatePlan: (caseId: UUID, templateCode: string) => http.post<{ plan_id: UUID }>(`/api/v1/onboarding/cases/${caseId}/plan`, { template_code: templateCode }),
};

/** The link a joiner opens. Matches the /welcome route (?token=...). */
export function welcomeLink(token: string): string {
  return `${window.location.origin}/welcome?token=${encodeURIComponent(token)}`;
}

// ---- public: pre-joiner portal (no staff login) ----

export interface PortalField {
  key: string;
  label: string;
  type: string;
  format: string | null;
  options: string[] | null;
  required: boolean;
  hint: string | null;
  placeholder: string | null;
}

export interface JoiningField {
  key: string; label: string; required: boolean; kind: string; sensitive: boolean;
  /** change 2026-10-05: from Settings > Onboarding & employees > Joining details form */
  section?: string; help?: Partial<Record<"en" | "hi" | "ta", string>>; check?: boolean;
}
/** change 2026-10-05: HR's view of a joiner's details -- empty fields are listed, not errors */
export interface JoiningDetailsHr {
  status: string; submitted_at: string | null; updated_at: string | null; locked: boolean; locked_by: string | null; locked_at: string | null;
  fields: { key: string; label: string; section: string; required: boolean; value: string }[];
  missing_required: string[]; missing_optional: string[]; last_reminder_at: string | null;
}
export type FieldShow = "required" | "optional" | "hidden";
export interface JoiningFormSettings {
  version: number;
  sections: { key: string; label: string }[];
  fields: { key: string; label: string; kind: string; section: string; checkable: boolean; show: FieldShow; help: Record<"en" | "hi" | "ta", string>; check: boolean }[];
  documents: { code: string; label: string; default: FieldShow; show: FieldShow }[];
  history: { version: number; updated_by: string | null; updated_at: string | null; changes: string[] }[];
}
export interface JoiningDoc { code: string; label: string; required: boolean; status: "missing" | "uploaded" | "verified" | "rejected" | "received_earlier"; rejection_reason: string | null; types?: string[] | null; max_mb?: number | null }
export interface DayOneInfo {
  date: string; start_time: string | null; address: string | null; map_url: string | null; meet: string | null;
  what_to_bring: string[]; agenda: { time: string | null; title: string; emoji: string | null }[]; acknowledged_at: string | null;
}
export interface PortalContact { name: string; role: string | null; email: string | null; phone: string | null }

// fix 2026-10-04: built-in steps (offer / joining details / documents / day one) -- "locked_reason" until the offer is signed
// fix 2026-10-05: every step has its own state + English label / description / status text from the server,
// so a step type this page doesn't know still has a title (the page's own i18n wins for types it knows).
export type StepState = "locked" | "not_started" | "in_progress" | "done";
interface StepBase { code: string; done: boolean; counted?: boolean; state: StepState; status_text: string; description?: string | null; locked_reason?: string | null }
export type PortalStep =
  | (StepBase & { kind: "offer"; label: string; version_no: number; signed_at?: string | null; sign_url?: string | null; pdf_url?: string | null; expiry_date?: string | null; method: "docusign" | "in_app" })
  | (StepBase & { kind: "joining_details"; label: string; fields?: JoiningField[]; saved?: Record<string, string>; status?: string;
      form_version?: number; locked?: boolean; missing_required?: string[]; missing_optional?: string[] })
  | (StepBase & { kind: "joining_documents"; label: string; documents: JoiningDoc[] })
  | (StepBase & { kind: "day_one"; label: string; info: DayOneInfo | null })
  | (StepBase & { kind: "form"; label: string; fields: PortalField[]; saved: Record<string, unknown> })
  | (StepBase & { kind: "document"; label: string; status: "missing" | "pending" | "verified" | "rejected"; rejection_reason: string | null })
  | (StepBase & { kind: "policy"; label: string });

/** Bump together with backend welcome_steps.PORTAL_SCHEMA. */
export const PORTAL_SCHEMA = 2;

export interface PortalSummary {
  portal_schema?: number;
  first_name: string;
  role: string | null;
  joining_date: string;
  days_to_join: number;
  status: string;
  steps: PortalStep[];
  done: number;
  total: number;
  welcome: WelcomeContent;
  welcome_media: { content_type: string; title: string | null } | null;
  contacts?: PortalContact[];
}

async function publicRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: isForm ? undefined : { "Content-Type": "application/json" },
  });
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

const enc = encodeURIComponent;

export const welcomePortalApi = {
  summary: (token: string, lang: string) => publicRequest<PortalSummary>(`/api/v1/public/ui/onboarding/portal/${enc(token)}?lang=${enc(lang)}`),
  submitForm: (token: string, formKey: string, data: Record<string, unknown>) =>
    publicRequest<unknown>(`/api/v1/public/onboarding/portal/${enc(token)}/forms/${enc(formKey)}`, { method: "POST", body: JSON.stringify({ data }) }),
  acknowledgePolicy: (token: string, policyCode: string) =>
    publicRequest<unknown>(`/api/v1/public/onboarding/portal/${enc(token)}/policies/${enc(policyCode)}/acknowledge`, { method: "POST" }),
  saveJoiningDetails: (token: string, data: Record<string, string>, submit: boolean, formVersion?: number) =>
    publicRequest<{ saved: Record<string, string>; status: string; errors: Record<string, string>; missing_required: string[]; missing_optional: string[] }>(
      `/api/v1/public/ui/onboarding/portal/${enc(token)}/joining-details`, { method: "PUT", body: JSON.stringify({ data, submit, form_version: formVersion }) }),
  uploadJoiningDocument: (token: string, code: string, file: Blob, filename: string) => {
    const form = new FormData();
    form.append("code", code);
    form.append("file", file, filename);
    return publicRequest<{ code: string; status: string }>(`/api/v1/public/ui/onboarding/portal/${enc(token)}/joining-documents`, { method: "POST", body: form });
  },
  reportProblem: (token: string, kind: string, code: string) =>
    publicRequest<{ ok: boolean }>(`/api/v1/public/ui/onboarding/portal/${enc(token)}/problem`, { method: "POST", body: JSON.stringify({ kind, code, portal_schema: PORTAL_SCHEMA }) }),
  acknowledgeDayOne: (token: string) => publicRequest<{ ok: boolean }>(`/api/v1/public/ui/onboarding/portal/${enc(token)}/day-one`, { method: "POST" }),
  uploadDocument: (token: string, documentType: string, file: Blob, filename: string) => {
    const form = new FormData();
    form.append("document_type", documentType);
    form.append("file", file, filename);
    return publicRequest<{ id: UUID; status: string }>(`/api/v1/public/onboarding/portal/${enc(token)}/documents`, { method: "POST", body: form });
  },
};
