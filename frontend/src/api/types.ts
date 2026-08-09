// Types inferred from backend/app/schemas/*.py pydantic schemas.

export type UUID = string;

// ---- auth ----

export type UserRole = "recruiter" | "hiring_manager" | "interviewer" | "admin";

export const USER_ROLES: UserRole[] = ["recruiter", "hiring_manager", "interviewer", "admin"];

// Roles a user may pick for themselves on the public Register page.
// "admin" accounts can only be created by an existing admin (see users/router.py POST /users).
export const PUBLIC_REGISTRABLE_ROLES: UserRole[] = ["recruiter", "hiring_manager", "interviewer"];

export interface UserRegister {
  email: string;
  password: string;
  full_name?: string | null;
  role: UserRole;
}

export interface UserLogin {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserRead {
  id: UUID;
  email: string;
  full_name?: string | null;
  role: UserRole;
  created_at: string;
}

// ---- jobs ----

export interface JobRoleBase {
  title: string;
  department?: string | null;
  location?: string | null;
  experience_level?: string | null;
  skills?: string[] | null;
  salary_band_min?: number | null;
  salary_band_max?: number | null;
  positions_count: number;
  benefits?: string | null;
  additional_notes?: string | null;
}

export interface JobRoleCreate extends JobRoleBase {
  hiring_manager_id?: UUID | null;
  created_by?: UUID | null;
}

export interface JobRoleUpdate {
  title?: string;
  department?: string | null;
  location?: string | null;
  experience_level?: string | null;
  skills?: string[] | null;
  salary_band_min?: number | null;
  salary_band_max?: number | null;
  positions_count?: number;
  status?: string;
  jd_text?: string | null;
  benefits?: string | null;
  additional_notes?: string | null;
  posting_url_naukri?: string | null;
  posting_url_linkedin?: string | null;
}

export interface JobRoleRead extends JobRoleBase {
  id: UUID;
  hiring_manager_id?: UUID | null;
  jd_text?: string | null;
  status: string;
  published_platforms: Record<string, boolean>;
  publish_settings: Record<string, unknown>;
  posting_url_naukri?: string | null;
  posting_url_linkedin?: string | null;
  // Set only when a real LinkedIn post was created via the API. Null means either
  // LinkedIn wasn't enabled, the publishing user wasn't connected, or the post attempt
  // failed -- in all those cases posting_url_linkedin (manual fallback) is used instead.
  linkedin_post_urn?: string | null;
  created_by?: UUID | null;
  created_at: string;
}

// Final step of the create-job wizard. Naukri.com has no real posting API access (no
// business partnership) -- checking it only records intent server-side, plus an
// optional URL pasted in after posting manually. LinkedIn is real when the publishing
// user has connected their account: a real post is created via the API instead of
// asking for a manual URL. career_portal is always real: it's what flips
// job_roles.status to "published". application_deadline is enforced on read
// (see backend/app/jobs/service.py); email_notifications is real when the
// publishing user has Google connected.
export interface PublishPlatformsRequest {
  naukri: boolean;
  linkedin: boolean;
  career_portal: boolean;
  posting_url_naukri?: string | null;
  posting_url_linkedin?: string | null;
  email_notifications?: boolean;
  application_deadline?: string | null;
}

export interface JobFieldSuggestionsResponse {
  departments: string[];
  locations: string[];
  skills: string[];
}

// ---- candidates ----

export interface CandidateRead {
  id: UUID;
  full_name?: string | null;
  email?: string | null;
  phone?: string | null;
  resume_path?: string | null;
  parsed_fields?: ParsedResumeFields | null;
  created_at: string;
}

// shape of app.ai_services.resume_parser.ResumeParserOutput, stored as candidates.parsed_fields
export interface EducationItem {
  degree?: string | null;
  institution?: string | null;
  year?: number | null;
}

export interface WorkHistoryItem {
  company?: string | null;
  title?: string | null;
  start?: string | null;
  end?: string | null;
}

export interface ParsedResumeFields {
  full_name?: string | null;
  email?: string | null;
  phone?: string | null;
  total_experience_years?: number | null;
  skills: string[];
  education: EducationItem[];
  work_history: WorkHistoryItem[];
}

// ---- applications ----

export interface ApplicationCreate {
  job_role_id: UUID;
  candidate_id: UUID;
  expected_salary?: number | null;
}

export interface ApplicationRead {
  id: UUID;
  job_role_id: UUID;
  candidate_id: UUID;
  match_score?: number | null;
  skill_match_pct?: number | null;
  missing_skills?: string[] | null;
  ranking_score?: number | null;
  ranking_rationale?: string | null;
  status: string;
  expected_salary?: number | null;
  approved_salary?: number | null;
  created_at: string;
  updated_at: string;
}

export interface ShortlistDecisionRequest {
  decision: "select" | "reject";
  notes?: string | null;
  decided_by?: string | null;
}

// ---- interviews / scheduling ----

export interface InterviewCreate {
  interviewer_id?: UUID | null;
  scheduled_at: string;
  meeting_link?: string | null;
}

// ---- integrations ----

export interface GoogleAuthUrl {
  auth_url: string;
}

export interface DocuSignAuthUrl {
  auth_url: string;
}

export interface LinkedInAuthUrl {
  auth_url: string;
}

export interface IntegrationStatus {
  connected: boolean;
  connected_at?: string | null;
  // Only meaningful when connected=true and the provider's credential actually expires
  // (LinkedIn) -- null for providers that don't track expiry (Google, DocuSign).
  expired?: boolean | null;
}

export interface InterviewFeedbackUpdate {
  technical_rating?: number | null;
  communication_rating?: number | null;
  overall_rating?: number | null;
  comments?: string | null;
  decision?: "selected" | "rejected" | null;
}

export interface InterviewRead {
  id: UUID;
  application_id: UUID;
  interviewer_id?: UUID | null;
  scheduled_at?: string | null;
  meeting_link?: string | null;
  calendar_event_id?: string | null;
  calendar_link?: string | null;
  technical_rating?: number | null;
  communication_rating?: number | null;
  overall_rating?: number | null;
  comments?: string | null;
  decision?: string | null;
  created_at: string;
}

export interface InterviewQuestionsResponse {
  technical_questions: string[];
  behavioral_questions: string[];
  questions_to_probe_gaps: string[];
}

// ---- salary ----

export interface SalaryApprovalRequest {
  decision: "approve" | "reject";
  approved_salary?: number | null;
  notes?: string | null;
  approved_by?: string | null;
}

export interface SalaryStatusResponse {
  application_id: UUID;
  status: string;
  expected_salary?: number | null;
  approved_salary?: number | null;
  salary_band_min?: number | null;
  salary_band_max?: number | null;
}

// ---- bgv ----

export const BGV_DOC_TYPES = ["aadhaar", "pan", "degree", "experience"] as const;
export type BgvDocType = (typeof BGV_DOC_TYPES)[number];

export interface BgvDocumentRead {
  id: UUID;
  application_id: UUID;
  doc_type: string;
  file_path?: string | null;
  validation_status: string;
  validator_output?: BgvValidatorOutput | null;
  created_at: string;
}

// shape of app.ai_services.document_validator.DocumentValidatorOutput
export interface BgvExtractedFields {
  name?: string | null;
  id_number?: string | null;
  date?: string | null;
}

export interface BgvValidatorOutput {
  doc_type_detected: string;
  matches_expected_type: boolean;
  extracted_fields: BgvExtractedFields;
  validation_status: string;
  issues: string[];
}

export interface BgvClearRequest {
  decision: "clear" | "reject";
  notes?: string | null;
  cleared_by?: string | null;
}

// ---- offers ----

export interface OfferGenerateRequest {
  start_date: string;
  reporting_manager_name?: string | null;
}

export interface OfferSendRequest {
  docusign_envelope_id?: string | null;
}

export interface OfferRead {
  id: UUID;
  application_id: UUID;
  offer_letter_text?: string | null;
  docusign_envelope_id?: string | null;
  // Set only when docusign_envelope_id was created for real via the DocuSign API, as
  // opposed to a manually-pasted envelope ID.
  docusign_sender_id?: UUID | null;
  signed: boolean;
  onboarding_status: string;
  created_at: string;
}

// ---- reports ----

export interface StatusCount {
  status: string;
  count: number;
}

export interface PipelineResponse {
  total: number;
  by_status: StatusCount[];
}

export interface JobSummaryResponse {
  job_role_id: UUID;
  total_applications: number;
  by_status: StatusCount[];
  average_match_score?: number | null;
  average_ranking_score?: number | null;
}

export interface LabeledCount {
  label: string;
  count: number;
}

export interface TopJobItem {
  job_id: UUID;
  title: string;
  application_count: number;
}

export interface JobsDashboardStatsResponse {
  total_jobs: number;
  active_jobs: number;
  open_positions: number;
  total_applications: number;
  hires_this_month: number;
  avg_time_to_hire_days?: number | null;
  by_department: LabeledCount[];
  by_location: LabeledCount[];
  top_jobs: TopJobItem[];
}

export interface RecentActivityItem {
  id: UUID;
  created_at: string;
  message: string;
  entity_type?: string | null;
  entity_id?: UUID | null;
}

export interface RecentActivityResponse {
  items: RecentActivityItem[];
}

export interface AuditLogRead {
  id: UUID;
  entity_type?: string | null;
  entity_id?: UUID | null;
  action?: string | null;
  actor?: string | null;
  details?: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogPage {
  total: number;
  limit: number;
  offset: number;
  items: AuditLogRead[];
}

export interface ApplicationTimelineResponse {
  application_id: UUID;
  events: AuditLogRead[];
}

// ---- public careers portal ----

export interface PublicJobRead {
  id: UUID;
  title: string;
  department?: string | null;
  location?: string | null;
  experience_level?: string | null;
  skills?: string[] | null;
  jd_text?: string | null;
}

export interface PublicApplicationSubmitResponse {
  application_id: UUID;
  status: string;
}
