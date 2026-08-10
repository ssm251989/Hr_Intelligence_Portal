import type {
  ApplicationCreate,
  ApplicationRead,
  ApplicationTimelineResponse,
  AuditLogPage,
  BgvClearRequest,
  BgvDocumentRead,
  CandidateApplicationDetail,
  CandidateMessageRequest,
  CandidateMessageResponse,
  CandidateRead,
  CandidatesDashboardStatsResponse,
  CandidatesListPage,
  CandidateTimelineResponse,
  CsvImportSummary,
  DocuSignAuthUrl,
  GoogleAuthUrl,
  IntegrationStatus,
  InterviewCreate,
  InterviewFeedbackUpdate,
  InterviewQuestionsResponse,
  InterviewRead,
  JobFieldSuggestionsResponse,
  JobRoleCreate,
  JobRoleRead,
  JobRoleUpdate,
  JobsDashboardStatsResponse,
  JobStatusOverviewResponse,
  JobSummaryResponse,
  LabeledCount,
  LinkedInAuthUrl,
  NextAction,
  OfferGenerateRequest,
  OfferRead,
  OfferSendRequest,
  PipelineResponse,
  PublicApplicationSubmitResponse,
  PublicJobRead,
  PublishPlatformsRequest,
  RecentActivityResponse,
  SalaryApprovalRequest,
  SalaryStatusResponse,
  ShortlistDecisionRequest,
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
const del = <T>(path: string) => request<T>(path, { method: "DELETE" });
const postForm = <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form });

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
}

export const candidatesApi = {
  list: () => get<CandidateRead[]>("/candidates"),
  get: (candidateId: UUID) => get<CandidateRead>(`/candidates/${candidateId}`),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return postForm<CandidateRead>("/candidates/upload", form);
  },
  resumeDownloadUrl: (candidateId: UUID) => `${BASE_URL}/candidates/${candidateId}/resume`,
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
    return get<CandidatesListPage>(`/candidates/applications?${query.toString()}`);
  },
  importCsv: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return postForm<CsvImportSummary>("/candidates/import-csv", form);
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
};

// ---- screening ----

export const screeningApi = {
  screen: (applicationId: UUID) => post<ApplicationRead>(`/applications/${applicationId}/screen`),
  rank: (applicationId: UUID) => post<ApplicationRead>(`/applications/${applicationId}/rank`),
};

// ---- shortlisting ----

export const shortlistingApi = {
  list: (jobId: UUID) => get<ApplicationRead[]>(`/jobs/${jobId}/shortlist`),
  decide: (applicationId: UUID, payload: ShortlistDecisionRequest) =>
    post<ApplicationRead>(`/applications/${applicationId}/shortlist-decision`, payload),
};

// ---- scheduling / interviews ----

export const schedulingApi = {
  schedule: (applicationId: UUID, payload: InterviewCreate) =>
    post<InterviewRead>(`/applications/${applicationId}/interviews`, payload),
  list: (applicationId: UUID) => get<InterviewRead[]>(`/applications/${applicationId}/interviews`),
  get: (interviewId: UUID) => get<InterviewRead>(`/interviews/${interviewId}`),
  submitFeedback: (interviewId: UUID, payload: InterviewFeedbackUpdate) =>
    patch<InterviewRead>(`/interviews/${interviewId}/feedback`, payload),
  generateQuestions: (applicationId: UUID) =>
    post<InterviewQuestionsResponse>(`/applications/${applicationId}/interview-questions`),
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
