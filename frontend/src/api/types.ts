// Types inferred from backend/app/schemas/*.py pydantic schemas.

export type UUID = string;

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
}

export interface JobRoleRead extends JobRoleBase {
  id: UUID;
  hiring_manager_id?: UUID | null;
  jd_text?: string | null;
  status: string;
  created_by?: UUID | null;
  created_at: string;
}

// ---- candidates ----

export interface CandidateRead {
  id: UUID;
  full_name?: string | null;
  email?: string | null;
  phone?: string | null;
  resume_path?: string | null;
  parsed_fields?: Record<string, unknown> | null;
  created_at: string;
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
  missing_skills?: unknown[] | null;
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
  validator_output?: Record<string, unknown> | null;
  created_at: string;
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
