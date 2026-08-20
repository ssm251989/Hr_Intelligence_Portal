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
  experience_min_years?: number | null;
  experience_max_years?: number | null;
  technical_skills_must_have?: string[] | null;
  technical_skills_good_to_have?: string[] | null;
  soft_skills_must_have?: string[] | null;
  soft_skills_good_to_have?: string[] | null;
  salary_band_min?: number | null;
  salary_band_max?: number | null;
  positions_count: number;
  benefits?: string | null;
  additional_notes?: string | null;
  job_type: string;
}

export interface JobRoleCreate extends JobRoleBase {
  hiring_manager_id?: UUID | null;
  created_by?: UUID | null;
}

export interface JobRoleUpdate {
  title?: string;
  department?: string | null;
  location?: string | null;
  experience_min_years?: number | null;
  experience_max_years?: number | null;
  technical_skills_must_have?: string[] | null;
  technical_skills_good_to_have?: string[] | null;
  soft_skills_must_have?: string[] | null;
  soft_skills_good_to_have?: string[] | null;
  salary_band_min?: number | null;
  salary_band_max?: number | null;
  positions_count?: number;
  status?: string;
  job_type?: string;
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
  // Computed per-job stats for the jobs list table -- not real columns (see
  // app/jobs/router.py list_jobs), so any other job-returning call may just carry the
  // defaults (0 / null) rather than a real number.
  application_count: number;
  applications_pct_change?: number | null;
  avg_time_to_hire_days?: number | null;
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

// Defined-but-currently-zero sources (linkedin/naukri/indeed/monster/shine) are here so
// the real sourcing integrations can slot in later with no schema/type change -- nothing
// writes them yet (see backend/app/models/candidate.py CANDIDATE_SOURCES).
export const CANDIDATE_SOURCES = [
  "career_portal", "manual", "local_import",
  "linkedin", "naukri", "indeed", "monster", "shine",
] as const;
export type CandidateSource = (typeof CANDIDATE_SOURCES)[number];

// Sources with a real, working import path today -- everything else in
// CANDIDATE_SOURCES renders as "Coming soon" in the Import wizard/dropdown.
export const CONNECTED_CANDIDATE_SOURCES: CandidateSource[] = ["career_portal", "local_import"];

export function candidateSourceLabel(source: string): string {
  const labels: Record<string, string> = {
    career_portal: "Career Portal",
    manual: "Manual",
    local_import: "Local Import",
    linkedin: "LinkedIn",
    naukri: "Naukri",
    indeed: "Indeed",
    monster: "Monster",
    shine: "Shine",
  };
  return labels[source] ?? source;
}

// Purely a fallback-avatar hint (see backend app/candidates/gender_inference.py) -- never
// used for anything about the candidate besides which generic illustration to show when
// there's no real extracted photo. null means "no confident guess", not "unspecified".
export type InferredGender = "male" | "female" | null;

export interface CandidateRead {
  id: UUID;
  full_name?: string | null;
  email?: string | null;
  phone?: string | null;
  location?: string | null;
  resume_path?: string | null;
  photo_path?: string | null;
  inferred_gender?: InferredGender;
  parsed_fields?: ParsedResumeFields | null;
  source: string;
  created_at: string;
}

// Basic contact info only -- name/email/phone. Everything else about a candidate (resume,
// photo, parsed fields, source) comes from an upload/import/parse, not manual editing.
export interface CandidateUpdate {
  full_name?: string | null;
  email?: string | null;
  phone?: string | null;
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
  certificates: string[];
}

// ---- applications ----

// backend/app/models/application.py APPLICATION_STATUSES -- the entire real pipeline
// state machine (DB-enforced by a CHECK constraint). Used for filter dropdowns; the
// actual valid *next* status for any one application comes from the backend's
// NextAction lookup, never guessed client-side.
export const APPLICATION_STATUSES = [
  "received", "screened", "hr_selected", "hr_rejected",
  "interview_scheduled", "interview_selected", "interview_rejected",
  "salary_ok", "salary_above_band", "salary_approved", "salary_rejected",
  "bgv_requested", "bgv_pending", "bgv_cleared", "bgv_rejected",
  "offer_sent", "onboarding_started", "onboarding_completed",
  "on_hold",
] as const;

// backend/app/models/application.py TERMINAL_APPLICATION_STATUSES -- no further
// transition endpoint exists for any of these. Drives the Candidates list/dashboard's
// "active" vs "inactive" reading of a pipeline stage.
export const TERMINAL_APPLICATION_STATUSES = [
  "hr_rejected", "interview_rejected", "salary_rejected", "bgv_rejected", "onboarding_completed",
] as const;

export function isTerminalApplicationStatus(status: string): boolean {
  return (TERMINAL_APPLICATION_STATUSES as readonly string[]).includes(status);
}

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
  // Only meaningful while status === "on_hold" -- the status to restore on resume. Null
  // otherwise. See backend/app/candidates/hold.py.
  previous_status?: string | null;
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

// One (candidate, application) pairing -- the row shape shared by the Candidates
// dashboard's Recent Candidates table, the full Candidates List page, and a candidate's
// "other applications" on their detail page. A candidate with N applications appears as
// N separate rows, one per job.
export interface CandidateApplicationRow {
  application_id: UUID;
  candidate_id: UUID;
  candidate_name?: string | null;
  candidate_email?: string | null;
  job_role_id: UUID;
  job_title: string;
  status: string;
  source: string;
  location?: string | null;
  applied_on: string;
  // The original Resume Matcher score (match_resume's own match_score). Distinct from
  // composite_score below -- see that field's comment.
  match_score?: number | null;
  // Part A's equal-weighted composite across skills/experience/location/certificates/
  // match_score -- the same number Remarks' "Strong fit (score X)" text quotes. Null for
  // applications screened before Part A existed (never got a composite_score).
  composite_score?: number | null;
  // One of the five composite_score inputs, surfaced on its own -- the single factor
  // Remarks' "-- missing X, Y" text is directly about. Used by the Screening List (Part E).
  skill_match_pct?: number | null;
  // The separate, later "Rank" step's own score (app/screening/router.py rank_application)
  // -- null until an application has been ranked, independent of whether it's been screened.
  ranking_score?: number | null;
  experience_years?: number | null;
  resume_path?: string | null;
  photo_path?: string | null;
  inferred_gender?: InferredGender;
  // A rendering of this application's own latest ai_screening_scored/ai_screening_failed
  // audit_log entry (see backend app/screening/service.py describe_screening_audit_entry)
  // -- never a separately maintained string. Null until the application has ever been
  // screened.
  remarks?: string | null;
  // Part F: a DIFFERENT rendering of that exact same audit_log entry (see backend
  // app/screening/service.py describe_interview_readiness), driven by the separate
  // interview_min_score threshold rather than dashboard_min_score. The Screening List's own
  // "Remarks" column; Candidates List keeps showing `remarks` above, unaffected.
  interview_remarks?: string | null;
}

export interface CandidatesListPage {
  total: number;
  page: number;
  page_size: number;
  items: CandidateApplicationRow[];
}

// Real connection status for one candidate-sourcing channel -- LinkedIn/Naukri have no
// real candidate-import access today (separate from the job-posting LinkedIn integration
// elsewhere in this app, which doesn't grant candidate import), so they always report
// connected=false.
export interface CandidateDataSourceStatus {
  source: string;
  label: string;
  connected: boolean;
  last_sync?: string | null;
}

export interface CandidatesDashboardStatsResponse {
  total_candidates: number;
  new_this_month: number;
  from_career_portal: number;
  manually_added: number;
  active_candidates: number;
  avg_match_score: number | null;
  total_candidates_trend: StatTrend;
  new_this_month_trend: StatTrend;
  from_career_portal_trend: StatTrend;
  manually_added_trend: StatTrend;
  avg_match_score_trend: StatTrend;
  by_source: LabeledCount[];
  top_skills: LabeledCount[];
  match_score_distribution: LabeledCount[];
  data_sources: CandidateDataSourceStatus[];
  recent_candidates: CandidateApplicationRow[];
}

// A shortcut into an application's real pipeline endpoints -- never a status bypass.
// "one_click" actions can be executed directly (see api/client.ts runNextAction);
// "navigate" actions need real input an existing page already collects, so they just
// carry a route to send the recruiter to instead.
export interface NextAction {
  key: string;
  label: string;
  kind: "one_click" | "navigate";
  method?: "POST" | "PATCH" | null;
  endpoint?: string | null;
  body?: Record<string, unknown> | null;
  route?: string | null;
  confirm: boolean;
  description?: string | null;
}

export interface OtherApplicationItem {
  application_id: UUID;
  job_role_id: UUID;
  job_title: string;
  status: string;
  applied_on: string;
}

export interface CandidateApplicationDetail {
  application: ApplicationRead;
  job_title: string;
  candidate: CandidateRead;
  next_actions: NextAction[];
  other_applications: OtherApplicationItem[];
}

export interface CandidateMessageRequest {
  subject: string;
  body: string;
}

export interface CandidateMessageResponse {
  sent: boolean;
  to: string;
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
  scheduling_method: SchedulingMethod;
  created_at: string;
}

// "manual" = the recruiter-driven Schedule Interview flow (POST /applications/{id}/
// interviews); "auto" = Part 3's candidate email + secure-link confirmation flow.
export type SchedulingMethod = "manual" | "auto";

export const SCHEDULING_METHOD_LABELS: Record<SchedulingMethod, string> = {
  manual: "Manually-Scheduled",
  auto: "Auto-Scheduled",
};

// Selected/Rejected are permanent once a decision is recorded; before that, an interview
// is Upcoming (still in the future) or Awaiting Feedback (occurred, no decision yet).
export type InterviewStatus = "upcoming" | "awaiting_feedback" | "selected" | "rejected";

export const INTERVIEW_STATUSES: InterviewStatus[] = ["upcoming", "awaiting_feedback", "selected", "rejected"];

export const INTERVIEW_STATUS_LABELS: Record<InterviewStatus, string> = {
  upcoming: "Upcoming",
  awaiting_feedback: "Awaiting Feedback",
  selected: "Selected",
  rejected: "Rejected",
};

// One interview, joined with its candidate/job/interviewer names -- shared by the
// Interview List page and the Interview Dashboard's Recent Interviews table.
export interface InterviewListRow {
  interview_id: UUID;
  application_id: UUID;
  candidate_id: UUID;
  candidate_name?: string | null;
  candidate_email?: string | null;
  job_role_id: UUID;
  job_title: string;
  interviewer_id?: UUID | null;
  interviewer_name?: string | null;
  scheduled_at?: string | null;
  scheduling_method: SchedulingMethod;
  status: InterviewStatus;
  decision?: string | null;
  meeting_link?: string | null;
  calendar_link?: string | null;
  created_at: string;
}

export interface InterviewsListPage {
  total: number;
  page: number;
  page_size: number;
  items: InterviewListRow[];
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

export interface MonthlyPoint {
  month: string; // "YYYY-MM"
  value: number | null;
}

export interface StatTrend {
  // Oldest -> newest, 12 points, the last of which is the current (in-progress) month.
  series: MonthlyPoint[];
  compare_month: string; // "YYYY-MM" actually used for the comparison below
  compare_value: number | null;
  pct_change: number | null;
  // True when this trend is derived from *current* status rather than a real
  // historical snapshot (active_jobs, open_positions) -- see backend app/reports/stats.py.
  is_approximate: boolean;
}

export interface JobsDashboardStatsResponse {
  total_jobs: number;
  active_jobs: number;
  open_positions: number;
  total_applications: number;
  hires_this_month: number;
  avg_time_to_hire_days?: number | null;
  total_jobs_trend: StatTrend;
  active_jobs_trend: StatTrend;
  open_positions_trend: StatTrend;
  total_applications_trend: StatTrend;
  hires_this_month_trend: StatTrend;
  avg_time_to_hire_trend: StatTrend;
  by_department: LabeledCount[];
  by_location: LabeledCount[];
  top_jobs: TopJobItem[];
}

export interface JobStatusOverviewResponse {
  period: string; // "this_month" | "last_3_months" | "this_year" | "all_time"
  total: number;
  by_status: LabeledCount[];
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

export interface CandidateTimelineResponse {
  candidate_id: UUID;
  events: AuditLogRead[];
}

// ---- public careers portal ----

export interface PublicJobRead {
  id: UUID;
  title: string;
  department?: string | null;
  location?: string | null;
  experience_min_years?: number | null;
  experience_max_years?: number | null;
  technical_skills_must_have?: string[] | null;
  technical_skills_good_to_have?: string[] | null;
  soft_skills_must_have?: string[] | null;
  soft_skills_good_to_have?: string[] | null;
  jd_text?: string | null;
}

export interface PublicApplicationSubmitResponse {
  application_id: UUID;
  status: string;
}

// ---- screening settings (Part D dashboard threshold + Part F interview threshold) ----

export interface ScreeningSettings {
  dashboard_min_score: number;
  dashboard_max_score: number;
  // Part F: the Screening Dashboard's own, independent threshold -- whether a screened
  // application is flagged "Interview ready" in the Screening List's Remarks column.
  // Never shared with dashboard_min/max_score above.
  interview_min_score: number;
  interview_max_score: number;
  updated_at?: string | null;
}

// Partial update: send ONE pair (dashboard_min/max_score OR interview_min/max_score), never
// both at once -- each pair is saved by its own panel (Candidates Dashboard vs Screening
// Dashboard) and the backend leaves whichever pair you omit completely untouched. A pair
// sent partially (only min, or only max) is rejected -- see backend
// app/schemas/screening.py ScreeningSettingsUpdate.
export interface ScreeningSettingsUpdate {
  dashboard_min_score?: number;
  dashboard_max_score?: number;
  interview_min_score?: number;
  interview_max_score?: number;
}

// Summary counts for one Re-evaluate All run -- see app/screening/service.py
// re_evaluate_all. skipped_already_decided is applications whose status is past
// received/screened (a human decision already made) or on_hold -- never touched.
export interface ReEvaluateAllResult {
  considered: number;
  skipped_already_decided: number;
  updated: number;
  advanced_to_screened: number;
  not_ready: number;
  failed: number;
}

// ---- screening dashboard (Part E) ----

// awaiting_screening/awaiting_ranking are live backlog depths, not monthly counts -- no
// trend, since an application's status isn't tracked historically (see backend
// app/reports/stats.py awaiting_screening_count). Everything else follows the same
// monthly-trend shape as the Candidates/Jobs dashboards.
export interface ScreeningDashboardStatsResponse {
  awaiting_screening: number;
  awaiting_ranking: number;
  auto_advanced_this_month: number;
  failed_this_month: number;
  avg_composite_score: number | null;
  auto_advanced_this_month_trend: StatTrend;
  failed_this_month_trend: StatTrend;
  avg_composite_score_trend: StatTrend;
  recommendation_breakdown: LabeledCount[];
  composite_score_distribution: LabeledCount[];
  top_missing_skills: LabeledCount[];
}

// ---- shortlisting (redesign) ----

// The 4 shortlisting-stage states -- each maps directly onto a real Application.status
// (backend app/shortlisting/service.py), never a separate status column of its own.
// under_review=screened, shortlisted=hr_selected, on_hold=on_hold (paused from screened
// specifically), not_shortlisted=hr_rejected.
export const SHORTLIST_STATUSES = ["under_review", "shortlisted", "on_hold", "not_shortlisted"] as const;
export type ShortlistStatus = (typeof SHORTLIST_STATUSES)[number];

export const SHORTLIST_STATUS_LABELS: Record<ShortlistStatus, string> = {
  under_review: "Under Review",
  shortlisted: "Shortlisted",
  on_hold: "On Hold",
  not_shortlisted: "Not Shortlisted",
};

export function shortlistStatusOf(applicationStatus: string): ShortlistStatus | null {
  if (applicationStatus === "screened") return "under_review";
  if (applicationStatus === "hr_selected") return "shortlisted";
  if (applicationStatus === "hr_rejected") return "not_shortlisted";
  if (applicationStatus === "on_hold") return "on_hold";
  return null;
}

export interface ShortlistFunnelStage {
  label: string;
  count: number;
}

export interface ShortlistingDashboardStatsResponse {
  total_in_shortlisting: number;
  new_this_month: number;
  moved_from_screening_this_month: number;
  shortlisted_this_month: number;
  avg_composite_score_shortlisted: number | null;
  new_this_month_trend: StatTrend;
  moved_from_screening_this_month_trend: StatTrend;
  shortlisted_this_month_trend: StatTrend;
  avg_composite_score_shortlisted_trend: StatTrend;
  funnel: ShortlistFunnelStage[];
  composite_score_distribution: LabeledCount[];
  insights: string[];
  recent_shortlisted: CandidateApplicationRow[];
}

export interface ShortlistStatusUpdateRequest {
  target_status: ShortlistStatus;
  reason?: string | null;
  feedback?: string | null;
}

export interface ShortlistFeedbackSuggestionResponse {
  suggested_feedback: string;
}

// The bulk counterpart to ShortlistStatusUpdateRequest -- deliberately restricted to the
// two terminal decisions (the List page's "Shortlist Selected"/"Reject Selected" buttons).
export interface ShortlistBulkDecisionRequest {
  application_ids: UUID[];
  target_status: Extract<ShortlistStatus, "shortlisted" | "not_shortlisted">;
  reason?: string | null;
  feedback?: string | null;
}

export interface ShortlistBulkDecisionSkipped {
  application_id: UUID;
  reason: string;
}

export interface ShortlistBulkDecisionResult {
  succeeded: UUID[];
  skipped: ShortlistBulkDecisionSkipped[];
}

// ---- interviews dashboard (redesign) ----

export interface InterviewsDashboardStatsResponse {
  total_interviews_scheduled_this_month: number;
  upcoming: number;
  completed: number;
  selected: number;
  rejected: number;
  total_interviews_scheduled_this_month_trend: StatTrend;
  completed_trend: StatTrend;
  selected_trend: StatTrend;
  rejected_trend: StatTrend;
  outcome_breakdown: LabeledCount[];
  interviewer_workload: LabeledCount[];
  scheduling_method_breakdown: LabeledCount[];
  recent_interviews: InterviewListRow[];
}

// ---- interview scheduling automation (Part 3: email + secure-link confirmation --
// replaces the earlier WhatsApp/Twilio plan entirely, which was dropped before any of it
// was built) ----

export interface InterviewSchedulingSettings {
  tracker_path: string | null;
  updated_at?: string | null;
}

export interface InterviewSchedulingSettingsUpdate {
  tracker_path: string;
}

// What ensure_tracker_file actually did to the workbook at this path -- created fresh, or
// an existing file left untouched/patched with whatever sheets/columns it was missing.
export interface TrackerValidationResult {
  created: boolean;
  sheets_added: string[];
  columns_added: Record<string, string[]>;
}

export interface InterviewSchedulingSettingsSaveResult extends InterviewSchedulingSettings {
  validation: TrackerValidationResult;
  interviewer_pool_jobs_considered: number;
  interviewer_pool_rows_added: number;
}

// ---- local-folder auto-import settings (Part G redesign) ----

// Both paths are null until a recruiter saves them via the Import wizard's Local Import
// configure step -- the scheduled scan has nothing to do until then. scan_interval_minutes
// always has a value (defaults to 30) and is configurable on that same step.
export interface LocalImportSettings {
  ready_to_upload_root: string | null;
  already_uploaded_root: string | null;
  scan_interval_minutes: number;
  updated_at?: string | null;
}

export interface LocalImportSettingsUpdate {
  ready_to_upload_root: string;
  already_uploaded_root: string;
  scan_interval_minutes: number;
}

// LocalImportSettings plus the immediate job-folder sync's own summary, so the wizard can
// show "N job folders created" right after saving without a second call.
export interface LocalImportSettingsSaveResult extends LocalImportSettings {
  jobs_considered: number;
  folders_created: number;
}
