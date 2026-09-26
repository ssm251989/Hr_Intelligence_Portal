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

  // existing /api/v1/onboarding endpoints not wrapped in client.ts
  createCase: (payload: { email?: string; first_name?: string; last_name?: string; joining_date?: string; offer_id?: UUID }) =>
    http.post<{ id: UUID; portal_token: string }>("/api/v1/onboarding/cases", payload),
  changeJoiningDate: (caseId: UUID, joiningDate: string, reason?: string) =>
    http.post<{ id: UUID }>(`/api/v1/onboarding/cases/${caseId}/joining-date`, { joining_date: joiningDate, reason }),
  noShow: (caseId: UUID, reason?: string) => http.post<{ id: UUID }>(`/api/v1/onboarding/cases/${caseId}/no-show`, { reason }),
  revoke: (caseId: UUID, reason?: string) => http.post<{ id: UUID }>(`/api/v1/onboarding/cases/${caseId}/revoke`, { reason }),
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

export type PortalStep =
  | { kind: "offer"; code: string; label: null; done: boolean }
  | { kind: "form"; code: string; label: string; done: boolean; fields: PortalField[]; saved: Record<string, unknown> }
  | { kind: "document"; code: string; label: string; done: boolean; status: "missing" | "pending" | "verified" | "rejected"; rejection_reason: string | null }
  | { kind: "policy"; code: string; label: string; done: boolean };

export interface PortalSummary {
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
  uploadDocument: (token: string, documentType: string, file: Blob, filename: string) => {
    const form = new FormData();
    form.append("document_type", documentType);
    form.append("file", file, filename);
    return publicRequest<{ id: UUID; status: string }>(`/api/v1/public/onboarding/portal/${enc(token)}/documents`, { method: "POST", body: form });
  },
};
