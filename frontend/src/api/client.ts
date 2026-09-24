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

const BASE_URL = "http://localhost:8000";

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
  return fallback;
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

// ---- public careers portal (no auth) ----

export const publicApi = {
  listJobs: () => get<PublicJobRead[]>("/public/jobs"),
  getJob: (jobId: UUID) => get<PublicJobRead>(`/public/jobs/${jobId}`),
  apply: (payload: { jobId: UUID; fullName: string; email: string; phone?: string; resume: File }) => {
    const form = new FormData();
    form.append("job_id", payload.jobId);
    form.append("full_name", payload.fullName);
    form.append("email", payload.email);
    if (payload.phone) form.append("phone", payload.phone);
    form.append("resume", payload.resume);
    return postForm<PublicApplicationSubmitResponse>("/public/apply", form);
  },
};
