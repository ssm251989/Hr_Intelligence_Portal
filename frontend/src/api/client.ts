import type {
  ApplicationCreate,
  ApplicationRead,
  ApplicationTimelineResponse,
  AuditLogPage,
  BgvClearRequest,
  BgvDocumentRead,
  CandidateApplicationDetail,
  CandidateApplicationRow,
  CandidateMessageRequest,
  CandidateMessageResponse,
  CandidateRead,
  CandidatesDashboardStatsResponse,
  CandidatesListPage,
  CandidateTimelineResponse,
  CandidateUpdate,
  DocuSignAuthUrl,
  GoogleAuthUrl,
  HrInboundEmailRead,
  HrInboxListPage,
  HrIntegrationRead,
  HrIntegrationUpdate,
  HrMailboxValidateRequest,
  HrMailboxValidateResult,
  IntegrationStatus,
  InterviewCreate,
  InterviewFeedbackUpdate,
  InterviewQuestionsResponse,
  InterviewRead,
  InterviewsDashboardStatsResponse,
  InterviewsListPage,
  JobFieldSuggestionsResponse,
  JobRoleCreate,
  JobRoleRead,
  JobRoleUpdate,
  JobsDashboardStatsResponse,
  JobStatusOverviewResponse,
  JobSummaryResponse,
  LabeledCount,
  LinkedInAuthUrl,
  LocalImportSettings,
  LocalImportSettingsSaveResult,
  LocalImportSettingsUpdate,
  NextAction,
  OfferGenerateRequest,
  OfferRead,
  OfferSendRequest,
  PipelineResponse,
  PublicApplicationSubmitResponse,
  PublicJobRead,
  PublishPlatformsRequest,
  ReEvaluateAllResult,
  RecentActivityResponse,
  SalaryApprovalRequest,
  SalaryStatusResponse,
  ScreeningDashboardStatsResponse,
  ScreeningSettings,
  ScreeningSettingsUpdate,
  SendTestEmailResult,
  ShortlistBulkDecisionRequest,
  ShortlistBulkDecisionResult,
  InterviewSchedulingSettings,
  InterviewSchedulingSettingsSaveResult,
  InterviewSchedulingSettingsUpdate,
  RetryNegotiationResponse,
  ShortlistDecisionRequest,
  ShortlistFeedbackSuggestionResponse,
  ShortlistingDashboardStatsResponse,
  ShortlistStatus,
  ShortlistStatusUpdateRequest,
  TestImapConnectionResult,
  TokenResponse,
  UserLogin,
  UserRead,
  UserRegister,
  UUID,
} from "./types";

// Part 13: build-time API origin. Dev default unchanged; the Docker/nginx image builds with
// VITE_API_BASE_URL="/_api" (same-origin reverse proxy, so the tenant Host header is kept).
const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed with status ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Turn a caught error into a user-displayable string.
 *
 * FastAPI returns `detail` as a plain string for hand-raised HTTPExceptions, but as an
 * array of `{loc, msg, type}` objects for its own request-validation (422) errors --
 * `String(err.detail)` on that array renders the literal text "[object Object]". This
 * handles both shapes (plus any other unexpected shape) and always falls back to
 * `fallback` for non-ApiError failures (network errors, etc).
 */
export function extractErrorMessage(err: unknown, fallback: string): string {
  if (!(err instanceof ApiError)) {
    return fallback;
  }
  const { detail } = err;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : null))
      .filter((msg): msg is string => Boolean(msg));
    if (messages.length > 0) {
      return messages.join("; ");
    }
  }
  if (detail && typeof detail === "object" && "msg" in detail) {
    return String((detail as { msg: unknown }).msg);
  }
  // Part 14 section 8: friendly config errors -- {code, message, fix, fix_path}.
  if (detail && typeof detail === "object" && "message" in detail) {
    const { message, fix } = detail as { message: unknown; fix?: unknown };
    return fix ? `${String(message)} ${String(fix)}` : String(message);
  }
  return fallback;
}

/** Part 14 section 8: the settings page that fixes a friendly config error, if any. */
export function errorFixPath(err: unknown): string | null {
  if (!(err instanceof ApiError) || !err.detail || typeof err.detail !== "object") return null;
  const path = (err.detail as { fix_path?: unknown }).fix_path;
  return typeof path === "string" && path ? path : null;
}

/**
 * True for the one HTTPException detail shape a hand-raised backend error uses to signal a
 * specific, actionable failure code rather than free text -- currently only
 * {code: "TRACKER_LOCKED", message} from POST .../retry-negotiation (see
 * app/interview_scheduling/router.py), so a caller can show a fixed, specific message
 * instead of whatever string extractErrorMessage would otherwise surface.
 */
export function hasErrorCode(err: unknown, code: string): boolean {
  if (!(err instanceof ApiError) || !err.detail || typeof err.detail !== "object") {
    return false;
  }
  return (err.detail as { code?: unknown }).code === code;
}

let authToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isFormData = options.body instanceof FormData;
  const headers: Record<string, string> = isFormData
    ? { ...(options.headers as Record<string, string> | undefined) }
    : { "Content-Type": "application/json", ...(options.headers as Record<string, string> | undefined) };

  const hadToken = Boolean(authToken);
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  const response = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  if (response.status === 401 && hadToken) {
    onUnauthorized?.();
  }

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

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
const patch = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined });
const put = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined });
const del = <T>(path: string) => request<T>(path, { method: "DELETE" });
const postForm = <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form });

// For endpoints that return a file rather than JSON (e.g. a candidate's photo) and are
// rendered as an <img>/<Avatar> src -- a plain <img src="..."> can never attach the
// Authorization header this app's Bearer-token auth requires, so the browser's native
// image load would silently 401 and whatever renders it would just fall back to its
// placeholder. Fetching the bytes through the same authenticated path as every other
// request, then handing back a blob, is what actually lets the image load.
async function fetchBlob(path: string): Promise<Blob | null> {
  const headers: Record<string, string> = {};
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }
  const response = await fetch(`${BASE_URL}${path}`, { headers });
  if (!response.ok) return null;
  return response.blob();
}

// Executes a "one_click" NextAction (see api/types.ts) exactly as the backend described
// it -- the method/endpoint/body all come from app/candidates/pipeline_actions.py's
// lookup, so this is a dispatcher, not a place that invents its own request shape.
export function runNextAction<T>(action: NextAction): Promise<T> {
  if (!action.endpoint) {
    throw new Error(`NextAction "${action.key}" has no endpoint to call`);
  }
  if (action.method === "PATCH") {
    return patch<T>(action.endpoint, action.body ?? undefined);
  }
  return post<T>(action.endpoint, action.body ?? undefined);
}

// ---- auth ----

export const authApi = {
  register: (payload: UserRegister) => post<UserRead>("/auth/register", payload),
  login: (payload: UserLogin) => post<TokenResponse>("/auth/login", payload),
  me: () => get<UserRead>("/auth/me"),
};

// ---- users ----

export const usersApi = {
  list: (role?: string) => get<UserRead[]>(`/users${role ? `?role=${role}` : ""}`),
};

// ---- integrations ----

// ---- Platform settings (Part 2: Settings Registry) ----

export interface SettingDefinition {
  key: string;
  type: string;
  default: unknown;
  module: string;
  group: string;
  label_i18n_key: string;
  help_i18n_key: string;
  scopes_allowed: string[];
  sensitive: boolean;
  requires_restart: boolean;
  help?: string | null;
  affects?: string | null;
}

export interface SettingValueRow {
  key: string;
  value: unknown;
  scope_type: string;
  scope_id: string | null;
}

export interface SettingHistoryEntry {
  value: unknown;
  version: number;
  updated_by: string | null;
  updated_at: string | null;
  scope_type: string;
  scope_id: string | null;
}

export const platformSettingsApi = {
  definitions: (module?: string) => get<SettingDefinition[]>(`/api/v1/settings/definitions${module ? `?module=${module}` : ""}`),
  values: () => get<SettingValueRow[]>("/api/v1/settings"),
  update: (key: string, value: unknown) => put<SettingValueRow>(`/api/v1/settings/${key}`, { value, scope_type: "tenant" }),
  history: (key: string) => get<SettingHistoryEntry[]>(`/api/v1/settings/${key}/history`),
};

// ---- Connections framework (Part 3) ----

export interface ProviderCatalogEntry {
  code: string;
  capabilities: string[];
  config_schema: Record<string, unknown>;
  secret_fields: string[];
  oauth: Record<string, unknown> | null;
  implemented: boolean;
}

export interface ConnectionRow {
  id: UUID;
  name: string;
  provider_code: string;
  capability: string[];
  config_json: Record<string, unknown>;
  status: string;
  last_tested_at: string | null;
  last_test_result: { success: boolean; error?: string | null } | null;
  health_status: string | null;
}

export interface PurposeStatus {
  purpose: string;
  routed: boolean;
}

export const connectorsApi = {
  providers: () => get<ProviderCatalogEntry[]>("/api/v1/connectors/providers"),
  purposes: () => get<PurposeStatus[]>("/api/v1/connectors/purposes"),
  connections: () => get<ConnectionRow[]>("/api/v1/connections"),
  createConnection: (payload: { name: string; provider_code: string; config: Record<string, unknown>; secrets: Record<string, string> }) =>
    post<ConnectionRow>("/api/v1/connections", payload),
  testConnection: (id: UUID) => post<{ success: boolean; error?: string | null }>(`/api/v1/connections/${id}/test`),
  deleteConnection: (id: UUID) => del<void>(`/api/v1/connections/${id}`),
};

// ---- Communication Engine (Part 4) ----

export interface MessageTemplateRow {
  id: UUID;
  key: string;
  channel: string;
  locale: string;
  version: number;
  status: string;
  subject_tpl: string | null;
  html_tpl: string | null;
  text_tpl: string | null;
  variables_schema_json: { required?: string[] };
  published_by: string | null;
  published_at: string | null;
}

export interface NotificationRuleRow {
  id: UUID;
  name: string;
  event_type: string;
  condition_jsonlogic: Record<string, unknown> | null;
  recipients_json: Record<string, unknown>;
  channels: string[];
  template_key: string;
  delay_spec: Record<string, unknown> | null;
  quiet_hours_respect: boolean;
  digest_mode: string;
  priority: number;
  enabled: boolean;
}

export interface BrandThemeRow {
  id: UUID;
  name: string;
  primary_color: string | null;
  secondary_color: string | null;
  gradient_from: string | null;
  gradient_to: string | null;
  font_family: string | null;
  email_footer_html: string | null;
  legal_disclaimer: string | null;
}

export interface OutboundMessageRow {
  id: UUID;
  channel: string;
  purpose: string | null;
  to_addresses: string[];
  subject: string | null;
  status: string;
  attempts: number;
  error: string | null;
  sent_at: string | null;
  created_at: string | null;
}

export interface SuppressionRow {
  address: string;
  reason: string;
  created_at: string | null;
}

export const commsApi = {
  templates: () => get<MessageTemplateRow[]>("/api/v1/comms/templates"),
  templateVersions: (key: string) => get<MessageTemplateRow[]>(`/api/v1/comms/templates/${encodeURIComponent(key)}/versions`),
  createTemplateDraft: (payload: { key: string; channel?: string; locale?: string; subject_tpl?: string; html_tpl?: string; text_tpl?: string; variables_schema?: { required?: string[] } }) =>
    post<MessageTemplateRow>("/api/v1/comms/templates", payload),
  publishTemplate: (id: UUID) => post<MessageTemplateRow>(`/api/v1/comms/templates/${id}/publish`),
  previewTemplate: (id: UUID, sampleContext: Record<string, unknown>) =>
    post<{ subject: string; html: string; text: string }>(`/api/v1/comms/templates/${id}/preview`, { sample_context: sampleContext }),

  rules: () => get<NotificationRuleRow[]>("/api/v1/comms/rules"),
  createRule: (payload: Omit<NotificationRuleRow, "id">) => post<NotificationRuleRow>("/api/v1/comms/rules", payload),
  updateRule: (id: UUID, payload: Partial<Omit<NotificationRuleRow, "id">>) => patch<NotificationRuleRow>(`/api/v1/comms/rules/${id}`, payload),
  deleteRule: (id: UUID) => del<void>(`/api/v1/comms/rules/${id}`),

  brandTheme: () => get<BrandThemeRow | null>("/api/v1/comms/brand-theme"),
  upsertBrandTheme: (payload: Partial<Omit<BrandThemeRow, "id">> & { name: string }) => put<BrandThemeRow>("/api/v1/comms/brand-theme", payload),

  outbound: (params?: { status?: string; channel?: string }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.channel) qs.set("channel", params.channel);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return get<OutboundMessageRow[]>(`/api/v1/comms/outbound${suffix}`);
  },
  resendOutbound: (id: UUID) => post<OutboundMessageRow>(`/api/v1/comms/outbound/${id}/resend`),

  suppression: () => get<SuppressionRow[]>("/api/v1/comms/suppression"),
  removeSuppression: (address: string) => del<void>(`/api/v1/comms/suppression/${encodeURIComponent(address)}`),
};

// ---- Candidate/employee preferences page (public, token-based -- Part 4 section 6) ----

export interface PreferenceEntryRow {
  event_group: string;
  channel: string;
  opted_in: boolean;
}

export const publicCommsApi = {
  preferences: (token: string) => get<{ org_display_name: string; preferences: PreferenceEntryRow[] }>(`/api/v1/public/comms/preferences?token=${encodeURIComponent(token)}`),
  setPreference: (payload: { token: string; event_group: string; channel: string; opted_in: boolean }) =>
    post<PreferenceEntryRow>("/api/v1/public/comms/preferences", payload),
};

export const integrationsApi = {
  connectGoogle: () => get<GoogleAuthUrl>("/integrations/google/connect"),
  googleStatus: (userId?: UUID) =>
    get<IntegrationStatus>(`/integrations/google/status${userId ? `?user_id=${userId}` : ""}`),
  connectDocusign: () => get<DocuSignAuthUrl>("/integrations/docusign/connect"),
  docusignStatus: (userId?: UUID) =>
    get<IntegrationStatus>(`/integrations/docusign/status${userId ? `?user_id=${userId}` : ""}`),
  connectLinkedin: () => get<LinkedInAuthUrl>("/integrations/linkedin/connect"),
  linkedinStatus: (userId?: UUID) =>
    get<IntegrationStatus>(`/integrations/linkedin/status${userId ? `?user_id=${userId}` : ""}`),
};

// ---- HR mailbox (shared, org-level SMTP/IMAP settings + inbound mail list) ----

export interface HrInboxListParams {
  page?: number;
  pageSize?: number;
  search?: string;
  matched?: boolean;
}

export const hrInboxApi = {
  getSettings: () => get<HrIntegrationRead>("/hr-inbox/settings"),
  updateSettings: (payload: HrIntegrationUpdate) => put<HrIntegrationRead>("/hr-inbox/settings", payload),
  validateSettings: (payload: HrMailboxValidateRequest) =>
    post<HrMailboxValidateResult>("/hr-inbox/settings/validate", payload),
  sendTestEmail: (to: string) => post<SendTestEmailResult>("/hr-inbox/settings/send-test-email", { to }),
  testImapConnection: () => post<TestImapConnectionResult>("/hr-inbox/settings/test-imap-connection"),
  list: (params: HrInboxListParams = {}) => {
    const query = new URLSearchParams();
    query.set("page", String(params.page ?? 1));
    query.set("page_size", String(params.pageSize ?? 10));
    if (params.search) query.set("search", params.search);
    if (params.matched !== undefined) query.set("matched", String(params.matched));
    return get<HrInboxListPage>(`/hr-inbox/list?${query.toString()}`);
  },
  export: (params: Omit<HrInboxListParams, "page" | "pageSize"> = {}) => {
    const query = new URLSearchParams();
    if (params.search) query.set("search", params.search);
    if (params.matched !== undefined) query.set("matched", String(params.matched));
    return get<HrInboundEmailRead[]>(`/hr-inbox/export?${query.toString()}`);
  },
};

// ---- jobs ----

export const jobsApi = {
  list: () => get<JobRoleRead[]>("/jobs"),
  get: (jobId: UUID) => get<JobRoleRead>(`/jobs/${jobId}`),
  create: (payload: JobRoleCreate) => post<JobRoleRead>("/jobs", payload),
  update: (jobId: UUID, payload: JobRoleUpdate) => patch<JobRoleRead>(`/jobs/${jobId}`, payload),
  delete: (jobId: UUID) => del<void>(`/jobs/${jobId}`),
  generateJd: (jobId: UUID) => post<JobRoleRead>(`/jobs/${jobId}/generate-jd`),
  publishPlatforms: (jobId: UUID, payload: PublishPlatformsRequest) =>
    post<JobRoleRead>(`/jobs/${jobId}/publish`, payload),
  hold: (jobId: UUID) => post<JobRoleRead>(`/jobs/${jobId}/hold`),
  resume: (jobId: UUID) => post<JobRoleRead>(`/jobs/${jobId}/resume`),
  fieldSuggestions: () => get<JobFieldSuggestionsResponse>("/jobs/field-suggestions"),
};

// ---- candidates ----

export interface CandidateApplicationsListParams {
  page?: number;
  pageSize?: number;
  search?: string;
  jobRoleId?: UUID;
  status?: string;
  source?: string;
  location?: string;
  experienceMin?: number;
  experienceMax?: number;
  appliedAfter?: string;
  appliedBefore?: string;
  matchScoreMin?: number;
  matchScoreMax?: number;
  // Which column matchScoreMin/Max filter -- omit for the Candidates List's "Match Score"
  // filter (raw Resume Matcher score, the backend default); "composite_score" for the
  // Screening List's "Screening Score" filter, targeting the same column that page's
  // primary score column shows (see utils/screeningScore.ts).
  scoreField?: "match_score" | "composite_score";
}

// Same filters as the list above minus pagination -- the export endpoint is unpaginated
// on purpose (see backend app/candidates/router.py export_candidate_applications). When
// applicationIds is given (row checkboxes checked on the List page), every other filter
// is ignored server-side -- export exactly those rows regardless of what's currently
// filtered/visible.
export type CandidateApplicationsExportParams = Omit<CandidateApplicationsListParams, "page" | "pageSize"> & {
  applicationIds?: UUID[];
};

export const candidatesApi = {
  list: () => get<CandidateRead[]>("/candidates"),
  get: (candidateId: UUID) => get<CandidateRead>(`/candidates/${candidateId}`),
  update: (candidateId: UUID, payload: CandidateUpdate) => patch<CandidateRead>(`/candidates/${candidateId}`, payload),
  // source defaults to "manual" server-side (the single-candidate "Upload Resume" flow);
  // the Import wizard's "Import from Local" step passes "local_import" explicitly so
  // those candidates are distinguishable/filterable afterward.
  upload: (file: File, source?: "manual" | "local_import") => {
    const form = new FormData();
    form.append("file", file);
    if (source) form.append("source", source);
    return postForm<CandidateRead>("/candidates/upload", form);
  },
  photoDownloadUrl: (candidateId: UUID) => `${BASE_URL}/candidates/${candidateId}/photo`,
  fetchPhotoBlob: (candidateId: UUID) => fetchBlob(`/candidates/${candidateId}/photo`),
  fetchResumeBlob: (candidateId: UUID) => fetchBlob(`/candidates/${candidateId}/resume`),
  parseResume: (candidateId: UUID) => post<CandidateRead>(`/candidates/${candidateId}/parse-resume`),
  // One row per (candidate, application) pairing -- the Candidates List page's data source.
  listApplications: (params: CandidateApplicationsListParams = {}) => {
    const query = new URLSearchParams();
    query.set("page", String(params.page ?? 1));
    query.set("page_size", String(params.pageSize ?? 10));
    if (params.search) query.set("search", params.search);
    if (params.jobRoleId) query.set("job_role_id", params.jobRoleId);
    if (params.status) query.set("status", params.status);
    if (params.source) query.set("source", params.source);
    if (params.location) query.set("location", params.location);
    if (params.experienceMin != null) query.set("experience_min", String(params.experienceMin));
    if (params.experienceMax != null) query.set("experience_max", String(params.experienceMax));
    if (params.appliedAfter) query.set("applied_after", params.appliedAfter);
    if (params.appliedBefore) query.set("applied_before", params.appliedBefore);
    if (params.matchScoreMin != null) query.set("match_score_min", String(params.matchScoreMin));
    if (params.matchScoreMax != null) query.set("match_score_max", String(params.matchScoreMax));
    if (params.scoreField) query.set("score_field", params.scoreField);
    return get<CandidatesListPage>(`/candidates/applications?${query.toString()}`);
  },
  // Unpaginated -- returns every matching row (or exactly the given applicationIds) for
  // the List page's Export button. Never used to render the table itself.
  exportApplications: (params: CandidateApplicationsExportParams = {}) => {
    const query = new URLSearchParams();
    if (params.applicationIds && params.applicationIds.length > 0) {
      params.applicationIds.forEach((id) => query.append("application_ids", id));
      return get<CandidateApplicationRow[]>(`/candidates/applications/export?${query.toString()}`);
    }
    if (params.search) query.set("search", params.search);
    if (params.jobRoleId) query.set("job_role_id", params.jobRoleId);
    if (params.status) query.set("status", params.status);
    if (params.source) query.set("source", params.source);
    if (params.location) query.set("location", params.location);
    if (params.experienceMin != null) query.set("experience_min", String(params.experienceMin));
    if (params.experienceMax != null) query.set("experience_max", String(params.experienceMax));
    if (params.appliedAfter) query.set("applied_after", params.appliedAfter);
    if (params.appliedBefore) query.set("applied_before", params.appliedBefore);
    if (params.matchScoreMin != null) query.set("match_score_min", String(params.matchScoreMin));
    if (params.matchScoreMax != null) query.set("match_score_max", String(params.matchScoreMax));
    if (params.scoreField) query.set("score_field", params.scoreField);
    return get<CandidateApplicationRow[]>(`/candidates/applications/export?${query.toString()}`);
  },
  timeline: (candidateId: UUID) => get<CandidateTimelineResponse>(`/candidates/${candidateId}/timeline`),
};

// ---- applications ----

export const applicationsApi = {
  list: (jobRoleId?: UUID) =>
    get<ApplicationRead[]>(`/applications${jobRoleId ? `?job_role_id=${jobRoleId}` : ""}`),
  create: (payload: ApplicationCreate) => post<ApplicationRead>("/applications", payload),
  candidateDetail: (applicationId: UUID) =>
    get<CandidateApplicationDetail>(`/applications/${applicationId}/candidate-detail`),
  message: (applicationId: UUID, payload: CandidateMessageRequest) =>
    post<CandidateMessageResponse>(`/applications/${applicationId}/message`, payload),
  hold: (applicationId: UUID) => post<ApplicationRead>(`/applications/${applicationId}/hold`),
  resume: (applicationId: UUID) => post<ApplicationRead>(`/applications/${applicationId}/resume`),
  delete: (applicationId: UUID) => del<void>(`/applications/${applicationId}`),
};

// ---- screening ----

export const screeningApi = {
  screen: (applicationId: UUID) => post<ApplicationRead>(`/applications/${applicationId}/screen`),
  rank: (applicationId: UUID) => post<ApplicationRead>(`/applications/${applicationId}/rank`),
  // Part D: the Candidates Dashboard's configurable auto-advance-to-'screened' threshold.
  getSettings: () => get<ScreeningSettings>("/screening/settings"),
  updateSettings: (payload: ScreeningSettingsUpdate) => put<ScreeningSettings>("/screening/settings", payload),
  reEvaluateAll: () => post<ReEvaluateAllResult>("/screening/re-evaluate-all"),
};

// ---- local-folder auto-import (Part G) ----

export const localImportApi = {
  getSettings: () => get<LocalImportSettings>("/local-import/settings"),
  // Saving immediately syncs job folders under both roots -- see backend
  // app/local_import/router.py update_settings.
  updateSettings: (payload: LocalImportSettingsUpdate) =>
    put<LocalImportSettingsSaveResult>("/local-import/settings", payload),
};

// ---- interview scheduling automation (Part 3: email + secure-link confirmation --
// replaces the earlier WhatsApp/Twilio plan entirely, which was dropped before any of it
// was built) ----

export const interviewSchedulingApi = {
  getSettings: () => get<InterviewSchedulingSettings>("/interview-scheduling/settings"),
  // Saving immediately ensures the tracker workbook exists with the expected sheets/
  // columns -- see backend app/interview_scheduling/router.py update_settings.
  updateSettings: (payload: InterviewSchedulingSettingsUpdate) =>
    put<InterviewSchedulingSettingsSaveResult>("/interview-scheduling/settings", payload),
  // Manual escape hatch for an application stuck at Shortlisted after
  // attempt_auto_negotiate_interview_slots failed (e.g. a send error) -- bypasses
  // shortlisting's own terminal-SHORTLISTED rule entirely since this isn't a status change,
  // see backend app/interview_scheduling/router.py retry_negotiation_endpoint.
  retryNegotiation: (applicationId: UUID) =>
    post<RetryNegotiationResponse>(`/interview-scheduling/applications/${applicationId}/retry-negotiation`),
};

// ---- shortlisting (redesign) ----

// Same filter shape as CandidateApplicationsListParams, minus `status` (replaced by
// `shortlistStatus`, one of the 4 named shortlist states -- see api/types.ts
// ShortlistStatus) since this list is always scoped to the shortlisting stage itself, never
// the raw underlying Application.status.
export interface ShortlistingListParams {
  page?: number;
  pageSize?: number;
  search?: string;
  jobRoleId?: UUID;
  shortlistStatus?: ShortlistStatus;
  source?: string;
  location?: string;
  experienceMin?: number;
  experienceMax?: number;
  appliedAfter?: string;
  appliedBefore?: string;
  matchScoreMin?: number;
  matchScoreMax?: number;
}

export type ShortlistingExportParams = Omit<ShortlistingListParams, "page" | "pageSize"> & {
  applicationIds?: UUID[];
};

function _shortlistingQuery(params: ShortlistingListParams): URLSearchParams {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.jobRoleId) query.set("job_role_id", params.jobRoleId);
  if (params.shortlistStatus) query.set("shortlist_status", params.shortlistStatus);
  if (params.source) query.set("source", params.source);
  if (params.location) query.set("location", params.location);
  if (params.experienceMin != null) query.set("experience_min", String(params.experienceMin));
  if (params.experienceMax != null) query.set("experience_max", String(params.experienceMax));
  if (params.appliedAfter) query.set("applied_after", params.appliedAfter);
  if (params.appliedBefore) query.set("applied_before", params.appliedBefore);
  if (params.matchScoreMin != null) query.set("match_score_min", String(params.matchScoreMin));
  if (params.matchScoreMax != null) query.set("match_score_max", String(params.matchScoreMax));
  return query;
}

export const shortlistingApi = {
  // The pre-redesign single-job queue/decision endpoints -- still used by the Candidate
  // Detail page's "Move Stage" quick actions (see backend app/candidates/pipeline_actions.py),
  // untouched by this redesign.
  list: (jobId: UUID) => get<ApplicationRead[]>(`/jobs/${jobId}/shortlist`),
  decide: (applicationId: UUID, payload: ShortlistDecisionRequest) =>
    post<ApplicationRead>(`/applications/${applicationId}/shortlist-decision`, payload),
  // One row per (candidate, application) pairing, scoped to the shortlisting stage -- the
  // Shortlisting List page's data source (see backend app/shortlisting/router.py list_shortlisting).
  listShortlisting: (params: ShortlistingListParams = {}) => {
    const query = _shortlistingQuery(params);
    query.set("page", String(params.page ?? 1));
    query.set("page_size", String(params.pageSize ?? 10));
    return get<CandidatesListPage>(`/shortlisting/list?${query.toString()}`);
  },
  exportShortlisting: (params: ShortlistingExportParams = {}) => {
    const query = new URLSearchParams();
    if (params.applicationIds && params.applicationIds.length > 0) {
      params.applicationIds.forEach((id) => query.append("application_ids", id));
      return get<CandidateApplicationRow[]>(`/shortlisting/export?${query.toString()}`);
    }
    return get<CandidateApplicationRow[]>(`/shortlisting/export?${_shortlistingQuery(params).toString()}`);
  },
  updateStatus: (applicationId: UUID, payload: ShortlistStatusUpdateRequest) =>
    post<ApplicationRead>(`/applications/${applicationId}/shortlist-status`, payload),
  suggestFeedback: (applicationId: UUID) =>
    post<ShortlistFeedbackSuggestionResponse>(`/applications/${applicationId}/shortlist-feedback-suggestion`),
  // Bulk select-and-decide: still a fully human-triggered decision for every application
  // (the recruiter selected each one and confirmed the batch in a dialog listing them by
  // name) -- same per-application transition validation as updateStatus, just applied to
  // many applications in one call. See backend app/shortlisting/router.py bulk_shortlist_decision.
  bulkDecision: (payload: ShortlistBulkDecisionRequest) =>
    post<ShortlistBulkDecisionResult>("/shortlisting/bulk-decision", payload),
};

// ---- scheduling / interviews ----

export interface InterviewsListParams {
  page?: number;
  pageSize?: number;
  jobRoleId?: UUID;
  interviewerId?: UUID;
  status?: "upcoming" | "awaiting_feedback" | "selected" | "rejected";
  schedulingMethod?: "manual" | "auto";
  scheduledAfter?: string;
  scheduledBefore?: string;
}

export const schedulingApi = {
  schedule: (applicationId: UUID, payload: InterviewCreate) =>
    post<InterviewRead>(`/applications/${applicationId}/interviews`, payload),
  list: (applicationId: UUID) => get<InterviewRead[]>(`/applications/${applicationId}/interviews`),
  get: (interviewId: UUID) => get<InterviewRead>(`/interviews/${interviewId}`),
  submitFeedback: (interviewId: UUID, payload: InterviewFeedbackUpdate) =>
    patch<InterviewRead>(`/interviews/${interviewId}/feedback`, payload),
  generateQuestions: (applicationId: UUID) =>
    post<InterviewQuestionsResponse>(`/applications/${applicationId}/interview-questions`),
  // One row per interview, across every job -- the Interview List page's data source.
  listAll: (params: InterviewsListParams = {}) => {
    const query = new URLSearchParams();
    query.set("page", String(params.page ?? 1));
    query.set("page_size", String(params.pageSize ?? 10));
    if (params.jobRoleId) query.set("job_role_id", params.jobRoleId);
    if (params.interviewerId) query.set("interviewer_id", params.interviewerId);
    if (params.status) query.set("status", params.status);
    if (params.schedulingMethod) query.set("scheduling_method", params.schedulingMethod);
    if (params.scheduledAfter) query.set("scheduled_after", params.scheduledAfter);
    if (params.scheduledBefore) query.set("scheduled_before", params.scheduledBefore);
    return get<InterviewsListPage>(`/interviews?${query.toString()}`);
  },
};

// ---- salary ----

export const salaryApi = {
  validate: (applicationId: UUID) => post<ApplicationRead>(`/applications/${applicationId}/validate-salary`),
  confirm: (applicationId: UUID) => post<ApplicationRead>(`/applications/${applicationId}/salary/confirm`),
  approve: (applicationId: UUID, payload: SalaryApprovalRequest) =>
    post<ApplicationRead>(`/applications/${applicationId}/approve-salary`, payload),
  status: (applicationId: UUID) => get<SalaryStatusResponse>(`/applications/${applicationId}/salary-status`),
};

// ---- bgv ----

export const bgvApi = {
  request: (applicationId: UUID) => post<ApplicationRead>(`/applications/${applicationId}/bgv/request`),
  uploadDocument: (applicationId: UUID, docType: string, file: File) => {
    const form = new FormData();
    form.append("doc_type", docType);
    form.append("file", file);
    return postForm<BgvDocumentRead>(`/applications/${applicationId}/bgv/documents`, form);
  },
  listDocuments: (applicationId: UUID) =>
    get<BgvDocumentRead[]>(`/applications/${applicationId}/bgv/documents`),
  validateDocument: (applicationId: UUID, docId: UUID) =>
    post<BgvDocumentRead>(`/applications/${applicationId}/bgv/documents/${docId}/validate`),
  clear: (applicationId: UUID, payload: BgvClearRequest) =>
    post<ApplicationRead>(`/applications/${applicationId}/bgv/clear`, payload),
};

// ---- offers ----

export const offersApi = {
  generate: (applicationId: UUID, payload: OfferGenerateRequest) =>
    post<OfferRead>(`/applications/${applicationId}/offer/generate`, payload),
  markSigned: (applicationId: UUID, payload: OfferSendRequest) =>
    post<OfferRead>(`/applications/${applicationId}/offer/mark-signed`, payload),
  completeOnboarding: (applicationId: UUID) =>
    post<OfferRead>(`/applications/${applicationId}/offer/complete-onboarding`),
  get: (applicationId: UUID) => get<OfferRead>(`/applications/${applicationId}/offer`),
};

// ---- reports ----

export const reportsApi = {
  pipeline: (jobRoleId?: UUID) =>
    get<PipelineResponse>(`/reports/pipeline${jobRoleId ? `?job_role_id=${jobRoleId}` : ""}`),
  jobSummary: (jobId: UUID) => get<JobSummaryResponse>(`/reports/jobs/${jobId}/summary`),
  jobsDashboardStats: (compareMonth?: string) =>
    get<JobsDashboardStatsResponse>(
      `/reports/jobs-dashboard-stats${compareMonth ? `?compare_month=${compareMonth}` : ""}`
    ),
  jobStatusOverview: (period?: string) =>
    get<JobStatusOverviewResponse>(`/reports/job-status-overview${period ? `?period=${period}` : ""}`),
  recentActivity: (limit?: number) =>
    get<RecentActivityResponse>(`/reports/recent-activity${limit ? `?limit=${limit}` : ""}`),
  auditLog: (params: { entityType?: string; entityId?: UUID; action?: string; limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.entityType) query.set("entity_type", params.entityType);
    if (params.entityId) query.set("entity_id", params.entityId);
    if (params.action) query.set("action", params.action);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    const qs = query.toString();
    return get<AuditLogPage>(`/reports/audit${qs ? `?${qs}` : ""}`);
  },
  applicationTimeline: (applicationId: UUID) =>
    get<ApplicationTimelineResponse>(`/applications/${applicationId}/timeline`),
  candidatesDashboardStats: (compareMonth?: string) =>
    get<CandidatesDashboardStatsResponse>(
      `/reports/candidates-dashboard-stats${compareMonth ? `?compare_month=${compareMonth}` : ""}`
    ),
  // Omit `limit` for every distinct skill -- backs "View all skills".
  candidatesTopSkills: (limit?: number) =>
    get<LabeledCount[]>(`/reports/candidates-top-skills${limit ? `?limit=${limit}` : ""}`),
  screeningDashboardStats: (compareMonth?: string) =>
    get<ScreeningDashboardStatsResponse>(
      `/reports/screening-dashboard-stats${compareMonth ? `?compare_month=${compareMonth}` : ""}`
    ),
  shortlistingDashboardStats: (compareMonth?: string) =>
    get<ShortlistingDashboardStatsResponse>(
      `/reports/shortlisting-dashboard-stats${compareMonth ? `?compare_month=${compareMonth}` : ""}`
    ),
  interviewsDashboardStats: (compareMonth?: string) =>
    get<InterviewsDashboardStatsResponse>(
      `/reports/interviews-dashboard-stats${compareMonth ? `?compare_month=${compareMonth}` : ""}`
    ),
};

// ---- IAM: roles, role assignments, delegations, access review (Part 5A) ----

export interface PermissionRow {
  code: string;
  module: string;
  resource: string;
  action: string;
}

export interface RoleRow {
  id: UUID;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
}

export interface RoleAssignmentRow {
  id: UUID;
  user_id: UUID;
  role_id: UUID;
  scope_type: string;
  scope_ids: UUID[];
  valid_from: string | null;
  valid_to: string | null;
}

export interface DelegationRow {
  id: UUID;
  from_user_id: UUID;
  to_user_id: UUID;
  permissions: string[] | null;
  starts_at: string;
  ends_at: string;
}

export interface AccessReviewRow {
  user_id: UUID;
  email: string;
  full_name: string | null;
  role_names: string[];
}

export const iamApi = {
  permissions: () => get<PermissionRow[]>("/api/v1/iam/permissions"),
  roles: () => get<RoleRow[]>("/api/v1/iam/roles"),
  createRole: (payload: { name: string; description?: string; permissions: string[] }) => post<RoleRow>("/api/v1/iam/roles", payload),
  updateRole: (id: UUID, payload: { description?: string; permissions?: string[] }) => patch<RoleRow>(`/api/v1/iam/roles/${id}`, payload),
  deleteRole: (id: UUID) => del<void>(`/api/v1/iam/roles/${id}`),

  roleAssignments: (userId?: UUID) => get<RoleAssignmentRow[]>(`/api/v1/iam/role-assignments${userId ? `?user_id=${userId}` : ""}`),
  createRoleAssignment: (payload: { user_id: UUID; role_id: UUID; scope_type?: string }) => post<RoleAssignmentRow>("/api/v1/iam/role-assignments", payload),
  deleteRoleAssignment: (id: UUID) => del<void>(`/api/v1/iam/role-assignments/${id}`),

  delegations: () => get<DelegationRow[]>("/api/v1/iam/delegations"),
  createDelegation: (payload: { to_user_id: UUID; starts_at: string; ends_at: string; permissions?: string[] }) => post<DelegationRow>("/api/v1/iam/delegations", payload),
  deleteDelegation: (id: UUID) => del<void>(`/api/v1/iam/delegations/${id}`),

  accessReview: (permission: string) => get<AccessReviewRow[]>(`/api/v1/iam/access-review?permission=${encodeURIComponent(permission)}`),
  resetMfa: (userId: UUID) => post<void>(`/api/v1/iam/users/${userId}/mfa/reset`),
};

// ---- MFA self-service (Part 5A) -- for an already-logged-in user enrolling
// voluntarily; the stored session token is attached automatically by request(), same as
// every other authenticated call in this file. The login-time "forced enrollment before
// a real session exists" flow (iam.auth.mfa_required on, not yet enrolled) is a real,
// tested backend capability (auth/router.py's mfa_enrollment_token) with no frontend UI
// yet -- not exercised while mfa_required stays off for this tenant (see docs/
// build_log.md's own Part 5 note on why it defaults off).

export const mfaApi = {
  enrollTotpStart: () => post<{ secret: string; provisioning_uri: string }>("/auth/mfa/enroll/totp/start"),
  enrollTotpConfirm: (code: string) => post<{ recovery_codes: string[] }>("/auth/mfa/enroll/totp/confirm", { code }),
};

// ---- Workflow & Approval Engine (Part 5B) ----

export interface WorkflowDefinitionRow {
  id: UUID;
  key: string;
  name: string;
  module: string | null;
  version: number;
  status: string;
  graph_json: Record<string, unknown>;
  published_at: string | null;
}

export interface WorkflowStepRow {
  id: UUID;
  node_id: string;
  node_type: string;
  status: string;
  assignee_user_id: UUID | null;
  due_at: string | null;
  acted_by: string | null;
  action: string | null;
  comment: string | null;
}

export interface WorkflowInstanceRow {
  id: UUID;
  definition_id: UUID;
  entity_type: string;
  entity_id: UUID;
  status: string;
  current_node_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  steps: WorkflowStepRow[];
}

export interface InboxRow {
  step_id: UUID;
  instance_id: UUID;
  entity_type: string;
  entity_id: UUID;
  node_id: string;
  due_at: string | null;
  definition_name: string;
}

export const workflowApi = {
  definitions: () => get<WorkflowDefinitionRow[]>("/api/v1/workflow/definitions"),
  simulate: (id: UUID, sampleContext: Record<string, unknown>) => post<{ path: { node_id: string; type: string }[] }>(`/api/v1/workflow/definitions/${id}/simulate`, { sample_context: sampleContext }),
  instances: (params?: { entity_type?: string; status?: string }) => {
    const qs = new URLSearchParams();
    if (params?.entity_type) qs.set("entity_type", params.entity_type);
    if (params?.status) qs.set("status", params.status);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return get<WorkflowInstanceRow[]>(`/api/v1/workflow/instances${suffix}`);
  },
  actOnStep: (stepId: UUID, action: string, comment?: string) => post<WorkflowStepRow>(`/api/v1/workflow/steps/${stepId}/act`, { action, comment }),
  inbox: () => get<InboxRow[]>("/api/v1/inbox"),
};

// ---- Metadata: custom fields, form layouts, masters, sequences (Part 6 sections 1-4) ----

export interface CustomFieldDefRow {
  id: UUID;
  entity: string;
  code: string;
  label_i18n: Record<string, string>;
  type: string;
  validation_json: { options?: string[]; min?: number; max?: number; pattern?: string } | null;
  default: unknown;
  section: string | null;
  order: number;
  sensitive: boolean;
  is_active: boolean;
}

export interface MasterTypeRow {
  code: string;
  name: string;
  hierarchical: boolean;
}

export interface MasterValueRow {
  id: UUID;
  type_code: string;
  code: string;
  label_i18n: Record<string, string>;
  parent_id: UUID | null;
  sort: number;
  is_active: boolean;
}

export const metadataApi = {
  effectiveLayout: (entity: string, context: string) => get<{ entity: string; context: string; sections: unknown[]; custom_fields: unknown[] }>(`/api/v1/metadata/form-layouts/${entity}/${context}`),

  customFields: (entity?: string) => get<CustomFieldDefRow[]>(`/api/v1/metadata/custom-fields${entity ? `?entity=${entity}` : ""}`),
  createCustomField: (payload: { entity: string; code: string; type: string; label_i18n?: Record<string, string>; section?: string; order?: number; validation_json?: object }) =>
    post<CustomFieldDefRow>("/api/v1/metadata/custom-fields", payload),
  setCustomFieldActive: (id: UUID, isActive: boolean) => patch<CustomFieldDefRow>(`/api/v1/metadata/custom-fields/${id}?is_active=${isActive}`),
  deleteCustomField: (id: UUID) => del<void>(`/api/v1/metadata/custom-fields/${id}`),

  masterTypes: () => get<MasterTypeRow[]>("/api/v1/metadata/master-types"),
  masterValues: (typeCode: string) => get<MasterValueRow[]>(`/api/v1/metadata/master-values/${typeCode}`),
  createMasterValue: (typeCode: string, payload: { code: string; label_i18n: Record<string, string>; sort?: number }) =>
    post<MasterValueRow>(`/api/v1/metadata/master-values/${typeCode}`, payload),
  deactivateMasterValue: (id: UUID) => del<void>(`/api/v1/metadata/master-values/${id}`),

  defineSequence: (payload: { key: string; pattern: string; scope?: string; reset?: string }) => post<{ id: UUID; key: string; pattern: string; current: number }>("/api/v1/metadata/sequences", payload),
  nextSequenceValue: (key: string) => post<{ value: string }>(`/api/v1/metadata/sequences/${key}/next`),
};

// ---- Branding / bootstrap (Part 6 section 5+7) ----

export interface BrandingRead {
  product_name: string;
  logo_file_id: string | null;
  primary_color: string;
  secondary_color: string | null;
  gradient_from: string;
  gradient_to: string;
  font_family: string;
  support_contact: string | null;
  legal_links: string[];
  custom_css: string | null;
}

export interface BootstrapRead {
  tenant: { id: UUID; slug: string };
  branding: BrandingRead;
  locale: string;
  tz: string;
  permissions: string[];
  feature_flags: Record<string, boolean>;
  nav: { label_key: string; path: string }[];
  custom_labels: Record<string, string>;
  ai?: { enabled: boolean; features: Record<string, boolean> };
  home_path?: string;
  modules?: string[];
  ux?: { reduce_motion: boolean; page_size: number; direction: "ltr" | "rtl" };
}

export const brandingApi = {
  // Public (no-auth) -- works pre-login, on the login page itself.
  public: () => get<BrandingRead>("/api/v1/public/branding"),
  meBootstrap: () => get<BootstrapRead>("/api/me/bootstrap"),
  updateCustomCss: (customCss: string) => request<{ custom_css: string }>("/api/v1/branding/custom-css", { method: "PUT", body: JSON.stringify({ custom_css: customCss }) }),
};

// ---- Core HR (Part 7): org model, employee master, lifecycle, documents, letters ----

export interface DepartmentRow {
  id: UUID;
  name: string;
  business_unit_id: UUID | null;
  parent_id: UUID | null;
}

export interface PositionRow {
  id: UUID;
  code: string;
  title: string;
  department_id: UUID | null;
  location_id: UUID | null;
  grade: string | null;
  reports_to_position_id: UUID | null;
  status: string;
  is_critical: boolean;
}

export interface EmployeeRow {
  id: UUID;
  employee_code: string;
  status: string;
  worker_type: string;
  first_name: string;
  last_name: string | null;
  personal_email: string | null;
  pan: string | null;
  aadhaar: string | null;
  bank_account: string | null;
}

export interface EmploymentRecordRow {
  id: UUID;
  employee_id: UUID;
  effective_from: string;
  effective_to: string | null;
  event_type: string;
  event_reason: string | null;
  designation: string | null;
  grade: string | null;
  work_mode: string | null;
}

export const coreHrApi = {
  departments: () => get<DepartmentRow[]>("/api/v1/core-hr/departments"),
  createDepartment: (payload: { name: string; business_unit_id?: UUID; parent_id?: UUID }) => post<DepartmentRow>("/api/v1/core-hr/departments", payload),

  positions: () => get<PositionRow[]>("/api/v1/core-hr/positions"),
  createPosition: (payload: { code: string; title: string; department_id?: UUID; grade?: string }) => post<PositionRow>("/api/v1/core-hr/positions", payload),
  setReportsTo: (positionId: UUID, reportsToPositionId: UUID | null) =>
    patch<PositionRow>(`/api/v1/core-hr/positions/${positionId}/reports-to`, { reports_to_position_id: reportsToPositionId }),
  orgChart: (rootPositionId?: UUID) => get<{ id: UUID; code: string; title: string; status: string; is_critical: boolean; has_children: boolean }[]>(`/api/v1/core-hr/org-chart${rootPositionId ? `?root_position_id=${rootPositionId}` : ""}`),

  employees: (status?: string) => get<EmployeeRow[]>(`/api/v1/core-hr/employees${status ? `?status=${status}` : ""}`),
  createEmployee: (payload: { first_name: string; last_name?: string; status?: string; worker_type?: string; personal_email?: string }) => post<EmployeeRow>("/api/v1/core-hr/employees", payload),
  getEmployee: (id: UUID) => get<EmployeeRow>(`/api/v1/core-hr/employees/${id}`),
  setEncryptedField: (id: UUID, field: string, value: string) => request<{ ok: boolean }>(`/api/v1/core-hr/employees/${id}/encrypted-field`, { method: "PUT", body: JSON.stringify({ field, value }) }),
  revealEncryptedField: (id: UUID, field: string) => get<{ field: string; value: string | null }>(`/api/v1/core-hr/employees/${id}/encrypted-field/${field}`),

  requestLifecycleEvent: (employeeId: UUID, payload: { event_type: string; effective_from: string; changes?: Record<string, unknown>; reason?: string }) =>
    post<{ applied: boolean; employment_record_id?: UUID; workflow_instance_id?: UUID }>(`/api/v1/core-hr/employees/${employeeId}/lifecycle-events`, payload),
  employmentHistory: (employeeId: UUID) => get<EmploymentRecordRow[]>(`/api/v1/core-hr/employees/${employeeId}/employment-history`),

  documents: (employeeId: UUID) => get<{ id: UUID; type: string; issued_date: string | null; expiry_date: string | null; visibility: string }[]>(`/api/v1/core-hr/employees/${employeeId}/documents`),
  addDocument: (employeeId: UUID, payload: { doc_type: string; expiry_date?: string; visibility?: string }) =>
    post<{ id: UUID; type: string; expiry_date: string | null }>(`/api/v1/core-hr/employees/${employeeId}/documents`, payload),

  createLetterTemplate: (payload: { key: string; name: string; html_tpl: string; variables_schema?: object }) => post<{ id: UUID; key: string; version: number; status: string }>("/api/v1/core-hr/letter-templates", payload),
  publishLetterTemplate: (id: UUID) => post<{ id: UUID; status: string }>(`/api/v1/core-hr/letter-templates/${id}/publish`),
  generateLetter: (employeeId: UUID, payload: { template_key: string; context?: Record<string, unknown> }) =>
    post<{ id: UUID; verification_token: string; rendered_html: string }>(`/api/v1/core-hr/employees/${employeeId}/letters`, payload),
  letters: (employeeId: UUID) => get<{ id: UUID; template_key: string; generated_at: string | null; verification_token: string }[]>(`/api/v1/core-hr/employees/${employeeId}/letters`),
};

// ---- Recruitment platform (Part 8): pipeline, requisitions, availability, offer components ----

export interface PipelineTemplateRow {
  id: UUID;
  name: string;
  is_default: boolean;
}

export interface PipelineStageRow {
  id: UUID;
  code: string;
  name_i18n: Record<string, string>;
  order: number;
  category: string;
  sla_days: number | null;
}

export interface JobRequisitionRow {
  id: UUID;
  title: string;
  reason: string;
  headcount: number;
  status: string;
}

export interface InterviewerAvailabilityRow {
  id: UUID;
  interviewer_email: string;
  interviewer_name: string | null;
  max_interviews_per_day: number | null;
  max_interviews_per_week: number | null;
  source: string;
}

export interface OfferComponentRow {
  id: UUID;
  code: string;
  name: string;
  type: string;
  value: number;
}

export const recruitmentApi = {
  seedDefaultPipelineTemplate: () => post<{ id: UUID; name: string; is_default: boolean }>("/api/v1/recruitment/pipeline-templates/seed-default"),
  pipelineTemplates: () => get<PipelineTemplateRow[]>("/api/v1/recruitment/pipeline-templates"),
  pipelineStages: (templateId: UUID) => get<PipelineStageRow[]>(`/api/v1/recruitment/pipeline-templates/${templateId}/stages`),

  requisitions: (status?: string) => get<JobRequisitionRow[]>(`/api/v1/recruitment/requisitions${status ? `?status=${status}` : ""}`),
  createRequisition: (payload: { title: string; reason?: string; headcount?: number; justification?: string }) =>
    post<{ id: UUID; status: string }>("/api/v1/recruitment/requisitions", payload),
  requestRequisitionApproval: (id: UUID) => post<{ applied: boolean; status?: string; workflow_instance_id?: UUID }>(`/api/v1/recruitment/requisitions/${id}/request-approval`),

  interviewerAvailability: () => get<InterviewerAvailabilityRow[]>("/api/v1/recruitment/interviewer-availability"),
  upsertInterviewerAvailability: (payload: { interviewer_email: string; interviewer_name?: string; max_interviews_per_day?: number; max_interviews_per_week?: number }) =>
    put<{ id: UUID; interviewer_email: string }>("/api/v1/recruitment/interviewer-availability", payload),

  offerComponents: () => get<OfferComponentRow[]>("/api/v1/recruitment/offer-components"),
  createOfferComponent: (payload: { code: string; name: string; type: string; value: number }) => post<{ id: UUID; code: string }>("/api/v1/recruitment/offer-components", payload),
};

// ---- public careers portal (no auth) ----

export const publicApi = {
  listJobs: () => get<PublicJobRead[]>("/public/jobs"),
  getJob: (jobId: UUID) => get<PublicJobRead>(`/public/jobs/${jobId}`),
  apply: (payload: { jobId: UUID; fullName: string; email: string; phone?: string; resume: File; consent: boolean; knockoutAnswers?: Record<string, string> }) => {
    const form = new FormData();
    form.append("job_id", payload.jobId);
    form.append("full_name", payload.fullName);
    form.append("email", payload.email);
    if (payload.phone) form.append("phone", payload.phone);
    form.append("resume", payload.resume);
    form.append("consent", String(payload.consent));
    if (payload.knockoutAnswers) form.append("knockout_answers", JSON.stringify(payload.knockoutAnswers));
    return postForm<PublicApplicationSubmitResponse>("/public/apply", form);
  },
};

// ---- Part 9: pre-boarding & onboarding ----

export interface PreboardingCaseRow {
  id: UUID;
  email: string;
  joining_date: string;
  status: string;
  employee_id: UUID | null;
  offer_id: UUID | null;
}

export interface OnboardingDashboard {
  upcoming_joiners: { case_id: UUID; email: string; joining_date: string; status: string; readiness_percent: number }[];
  overdue_tasks_by_owner: Record<string, number>;
  bgv_status: Record<string, number>;
  documents_pending_verification: number;
  cases_by_status: Record<string, number>;
  offer_to_join_drop_off_percent: number;
}

export interface BgvCaseRow {
  id: UUID;
  subject_type: string;
  status: string;
  decision: string;
  checks: { type: string; status: string; notes?: string }[];
}

export const onboardingApi = {
  dashboard: () => get<OnboardingDashboard>("/api/v1/onboarding/dashboard"),
  cases: (status?: string) => get<PreboardingCaseRow[]>(`/api/v1/onboarding/cases${status ? `?status=${status}` : ""}`),
  createCase: (payload: { email?: string; first_name?: string; last_name?: string; joining_date?: string; offer_id?: UUID }) =>
    post<PreboardingCaseRow & { portal_token: string }>("/api/v1/onboarding/cases", payload),
  convert: (caseId: UUID) => post<{ employee_code: string; already_converted: boolean }>(`/api/v1/onboarding/cases/${caseId}/convert`, { confirm_joined: true }),
  noShow: (caseId: UUID, reason?: string) => post<PreboardingCaseRow>(`/api/v1/onboarding/cases/${caseId}/no-show`, { reason }),
  revoke: (caseId: UUID, reason?: string) => post<PreboardingCaseRow>(`/api/v1/onboarding/cases/${caseId}/revoke`, { reason }),
  bgvCases: () => get<BgvCaseRow[]>("/api/v1/onboarding/bgv"),
};

// ---- Part 10: performance, compensation, succession ----

export interface ReviewCycleRow {
  id: UUID;
  name: string;
  cycle_type: string;
  period_start: string;
  period_end: string;
  status: string;
}

export interface GoalTreeNode {
  id: UUID;
  title: string;
  level: string;
  progress_pct: number;
  rolled_up_progress_pct?: number;
  children: GoalTreeNode[];
}

export interface CriticalPositionRow {
  position_id: UUID;
  title: string;
  coverage: "covered" | "at_risk" | "uncovered";
  successors: { employee_id: UUID; readiness: string }[];
}

export const performanceApi = {
  cycles: () => get<ReviewCycleRow[]>("/api/v1/performance/cycles"),
  createCycle: (payload: { name: string; cycle_type: string; period_start: string; period_end: string; stages: { stage: string; weight: number }[]; sections: { key: string; weight: number }[] }) =>
    post<ReviewCycleRow>("/api/v1/performance/cycles", payload),
  eligibilityPreview: (cycleId: UUID) => get<{ eligible_count: number }>(`/api/v1/performance/cycles/${cycleId}/eligibility-preview`),
  launchCycle: (cycleId: UUID) => post<{ eligible: number; reviews_created: number }>(`/api/v1/performance/cycles/${cycleId}/launch`),
  goalTree: () => get<GoalTreeNode[]>("/api/v1/performance/goals/tree"),
  criticalPositions: () => get<CriticalPositionRow[]>("/api/v1/performance/succession/critical-positions"),
};

// ---- Part 11: helpdesk, assets, separation ----

export interface TicketRow {
  id: UUID;
  number: string;
  subject: string;
  category_code: string;
  priority: string;
  status: string;
  confidential: boolean;
  sla: { has_sla: boolean; resolution_breached?: boolean; resolution_elapsed_pct?: number } | null;
}

export interface AssetRow {
  id: UUID;
  asset_tag: string;
  name: string;
  category_code: string;
  status: string;
  allocated_to: UUID | null;
  book_value: number | null;
}

export interface SeparationSummary {
  separation_id: UUID;
  employee_id: UUID;
  type: string;
  status: string;
  last_working_day: string | null;
  clearance_pending: number;
  assets_pending: number;
}

export const serviceDeskApi = {
  tickets: (status?: string) => get<{ total: number; items: TicketRow[] }>(`/api/v1/service-desk/tickets?page_size=25${status ? `&status=${status}` : ""}`),
  assets: () => get<{ total: number; items: AssetRow[] }>("/api/v1/service-desk/assets?page_size=25"),
  separations: () => get<SeparationSummary[]>("/api/v1/service-desk/separations"),
  exportSeparationsUrl: "/api/v1/service-desk/separations-export",
};

// ---- Part 12: analytics, report builder, HR Copilot, agents ----

export interface DatasetField {
  key: string;
  label: string;
  type: string;
}

export interface DatasetRead {
  code: string;
  label: string;
  module: string;
  as_of_supported: boolean;
  fields: DatasetField[];
}

export interface ReportResult {
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  offset: number;
  limit: number;
}

export interface ReportDefinition {
  columns?: string[];
  filters?: { field: string; op: string; value?: unknown }[];
  group_by?: string[];
  measures?: { field: string; agg: string; as?: string }[];
  sort?: { field: string; dir: "asc" | "desc" }[];
  limit?: number;
  as_of?: string;
}

export interface CopilotAnswer {
  conversation_id: UUID;
  answer: string;
  citations: { n: number; title: string; heading: string | null; excerpt: string }[];
  draft: { id: UUID; action: string; payload: Record<string, unknown> } | null;
  handover?: boolean;
}

export interface AgentSuggestionRow {
  id: UUID;
  agent: string;
  kind: string;
  title: string;
  payload: Record<string, unknown>;
  status: string;
  created_at: string | null;
}

export const intelligenceApi = {
  datasets: () => get<DatasetRead[]>("/api/v1/intelligence/datasets"),
  runReport: (dataset: string, definition: ReportDefinition, offset = 0) => post<ReportResult>("/api/v1/intelligence/reports/run", { dataset, definition, offset }),
  saveReport: (payload: { name: string; dataset: string; definition: ReportDefinition; shared_role_names?: string[] }) => post<{ id: UUID }>("/api/v1/intelligence/reports", payload),
  reports: () => get<{ id: UUID; name: string; dataset: string }[]>("/api/v1/intelligence/reports"),
  exportUrl: (reportId: UUID, format: "csv" | "xlsx") => `/api/v1/intelligence/reports/${reportId}/export?format=${format}`,
  metric: (code: string) => get<{ metric: string; value: unknown; unit?: string; reason?: string }>(`/api/v1/intelligence/metrics/${code}`),
  ask: (question: string, language: string, conversationId?: UUID) =>
    post<CopilotAnswer>("/api/v1/intelligence/copilot/ask", { question, language, conversation_id: conversationId }),
  confirmDraft: (draftId: UUID, overrides: Record<string, unknown> = {}) => post<{ status: string; result: string | null; error: string | null }>(`/api/v1/intelligence/copilot/drafts/${draftId}/confirm`, { overrides }),
  discardDraft: (draftId: UUID) => post<{ ok: boolean }>(`/api/v1/intelligence/copilot/drafts/${draftId}/discard`),
  agentInbox: () => get<AgentSuggestionRow[]>("/api/v1/intelligence/agents/inbox"),
  decideSuggestion: (id: UUID, action: "approve" | "edit" | "reject", editedPayload?: Record<string, unknown>) =>
    post<AgentSuggestionRow>(`/api/v1/intelligence/agents/suggestions/${id}/decision`, { action, edited_payload: editedPayload }),
};

// ---- Part 13: set-password invites, privacy (DPDP), Super-Admin console ----

export const accountApi = {
  setPassword: (token: string, password: string) => post<void>("/auth/set-password", { token, password }),
};

export interface PrivacyRequestRow {
  id: UUID;
  type: string;
  subject_type: string;
  subject_email: string;
  status: string;
  due_at: string;
  identity_verified: boolean;
  legal_hold: boolean;
}

export interface BreachRow {
  id: UUID;
  title: string;
  severity: string;
  status: string;
  detected_at: string;
}

export const privacyApi = {
  requests: () => get<PrivacyRequestRow[]>("/api/v1/privacy/requests"),
  verify: (id: UUID) => post<PrivacyRequestRow>(`/api/v1/privacy/requests/${id}/verify`),
  breaches: () => get<BreachRow[]>("/api/v1/privacy/breaches"),
};

// The console is a separate identity: its own token, never the tenant session's.
async function consoleRequest<T>(path: string, token: string | null, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const response = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? body;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export interface ConsoleTenantRow {
  id: UUID;
  slug: string;
  name: string;
  status: string;
  isolation: string;
  region: string | null;
  plan: string | null;
  domains: string[];
}

export const superAdminApi = {
  login: (email: string, password: string, totp_code: string) =>
    consoleRequest<{ access_token: string; expires_in_minutes: number }>("/api/v1/superadmin/login", null, { method: "POST", body: JSON.stringify({ email, password, totp_code }) }),
  tenants: (token: string) => consoleRequest<ConsoleTenantRow[]>("/api/v1/superadmin/tenants", token),
  setStatus: (token: string, slug: string, status: string, reason?: string) =>
    consoleRequest<{ status: string }>(`/api/v1/superadmin/tenants/${slug}/status`, token, { method: "POST", body: JSON.stringify({ status, reason }) }),
  health: (token: string, slug: string) => consoleRequest<{ database: { ok: boolean }; connections?: { name: string; ok: boolean }[] }>(`/api/v1/superadmin/tenants/${slug}/health`, token),
};

// ---- Part 14: setup wizard, config health, search, unified inbox, views, drafts, versions ----

export interface SetupStep {
  step: string;
  done: boolean;
  skipped: boolean;
  skippable: boolean;
  detail: string;
  fix_path: string;
}

export interface SetupProgress {
  steps: SetupStep[];
  percent: number;
  complete: boolean;
}

export interface HealthIssue {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  fix: string;
  fix_path: string;
}

export interface InboxItem {
  kind: string;
  id: string;
  title: string;
  subtitle: string;
  due_at: string | null;
  path: string;
  actions: string[];
}

export interface SavedViewRow {
  id: UUID;
  name: string;
  config: Record<string, unknown>;
  is_default: boolean;
  mine: boolean;
}

export const experienceApi = {
  search: (q: string) => get<{ groups: { type: string; label_key: string; items: { id: string; title: string; subtitle?: string | null; path: string }[] }[] }>(`/api/v1/search?q=${encodeURIComponent(q)}`),
  setupProgress: () => get<SetupProgress>("/api/v1/setup/progress"),
  setCompany: (payload: { display_name: string; legal_name?: string; timezone: string; locale?: string; currency?: string }) => post<SetupProgress>("/api/v1/setup/company", payload),
  setModules: (modules: string[]) => post<SetupProgress>("/api/v1/setup/modules", { modules }),
  applyConfigPack: (pack: unknown, dryRun: boolean) => post<Record<string, unknown>>("/api/v1/setup/config-pack", { pack, dry_run: dryRun }),
  inviteAdmin: (email: string, fullName?: string) => post<{ email_sent: boolean; link: string | null }>("/api/v1/setup/invite-admin", { email, full_name: fullName }),
  skipStep: (step: string, undo = false) => post<SetupProgress>(`/api/v1/setup/steps/${step}/skip`, { undo }),
  configHealth: () => get<{ healthy: boolean; issues: HealthIssue[]; counts: Record<string, number> }>("/api/v1/setup/config-health"),
  inbox: () => get<InboxItem[]>("/api/v1/inbox/all"),
  views: (listKey: string) => get<SavedViewRow[]>(`/api/v1/views/${listKey}`),
  saveView: (listKey: string, payload: { name: string; config: Record<string, unknown>; is_default?: boolean }) => put<SavedViewRow>(`/api/v1/views/${listKey}`, payload),
  deleteView: (listKey: string, id: UUID) => request<void>(`/api/v1/views/${listKey}/${id}`, { method: "DELETE" }),
  getDraft: (formKey: string, entityRef = "") => get<{ data: Record<string, unknown> | null; updated_at: string | null }>(`/api/v1/drafts/${formKey}?entity_ref=${encodeURIComponent(entityRef)}`),
  saveDraft: (formKey: string, data: Record<string, unknown>, entityRef = "") => put<{ updated_at: string }>(`/api/v1/drafts/${formKey}?entity_ref=${encodeURIComponent(entityRef)}`, { data }),
  discardDraft: (formKey: string, entityRef = "") => request<void>(`/api/v1/drafts/${formKey}?entity_ref=${encodeURIComponent(entityRef)}`, { method: "DELETE" }),
  versions: (kind: string, key: string) => get<{ id: UUID; version: number; status: string; created_at: string | null }[]>(`/api/v1/versions/${kind}/${key}`),
  revertVersion: (kind: string, key: string, version: number) => post<{ version: number; next_step: string }>(`/api/v1/versions/${kind}/${key}/revert`, { version }),
  updatePreferences: (payload: { reduce_motion?: boolean; page_size?: number; locale?: string; timezone?: string }) => put<{ ok: boolean }>("/api/v1/me/preferences", payload),
  myLetters: () => get<{ id: UUID; template_key: string; html: string }[]>("/api/v1/me/letters"),
  myDocuments: () => get<{ id: UUID; type: string; issued_date: string | null; expiry_date: string | null }[]>("/api/v1/me/documents"),
};
