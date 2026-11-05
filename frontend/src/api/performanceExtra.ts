// Part 15.6 -- Performance, Compensation and Succession pages. Reads come from the
// /api/v1/ui/performance helpers (names joined in); every write goes to the Part 10
// /api/v1/performance endpoints unchanged.
import { http } from "./client";

type UUID = string;
const P = "/api/v1/performance";
const UI = "/api/v1/ui/performance";

export interface GoalNode {
  id: UUID;
  title: string;
  description: string | null;
  level: "company" | "department" | "team" | "individual" | string;
  parent_goal_id: UUID | null;
  owner_name: string | null;
  is_mine: boolean;
  progress_pct: number;
  rolled_up_progress_pct?: number;
  confidence: number | null;
  status: string;
  weightage: number;
  due_date: string | null;
  last_checkin_at: string | null;
  checkin_due: boolean;
  children: GoalNode[];
}

export interface ReviewToWrite {
  id: UUID;
  stage: string;
  status: string;
  about_me: boolean;
  employee_name: string;
  cycle_name: string;
  cycle_open: boolean;
  due_date: string | null;
}

export interface MyPerformance {
  employee: { id: UUID; name: string } | null;
  team_size: number;
  tree: GoalNode[];
  my_goals: Omit<GoalNode, "children">[];
  checkin_due_count: number;
  reviews_to_write: ReviewToWrite[];
}

export interface ScalePoint {
  value: number;
  label: string | null;
}

export interface ReviewSection {
  key: string;
  weight?: number;
  title?: string;
  name?: string;
  label?: string;
  items?: (string | { key?: string; label?: string; title?: string; text?: string })[];
}

export interface ReviewForm {
  review: {
    id: UUID;
    stage: string;
    status: string;
    section_scores: Record<string, number | null>;
    goal_ratings: Record<string, number | null>;
    answers: Record<string, unknown>;
    comments: string | null;
    overall_rating: number | null;
    ai_draft: { summary?: string; bias_flags?: string[] } | null;
    submitted_at: string | null;
  };
  about_me: boolean;
  employee_name: string;
  reviewer_name: string;
  submit_as: "me" | "admin";
  cycle: { name: string; status: string; period_start: string | null; period_end: string | null; sections: ReviewSection[] } | null;
  scale: ScalePoint[] | null;
  goals: { id: UUID; title: string; weightage: number; progress_pct: number }[];
}

export interface ReviewPayload {
  section_scores: Record<string, number | null>;
  goal_ratings: Record<string, number | null>;
  answers: Record<string, unknown>;
  comments: string | null;
  final: boolean;
}

export interface NineBox {
  performance: number; // 1 low .. 3 high
  potential: number; // 1 low .. 3 high
}

export interface TeamMember {
  employee_id: UUID;
  name: string;
  designation: string | null;
  department: string | null;
  goals: number;
  avg_progress: number | null;
  last_checkin_at: string | null;
  checkin_due: boolean;
  review_status: string | null;
  manager_review_id: UUID | null;
  rating: number | null;
  suggested_performance: number | null;
  nine_box?: NineBox | null;
  flight_risk?: string | null;
}

export interface TeamView {
  scope: "mine" | "all";
  can_see_all: boolean;
  has_team: boolean;
  show_talent: boolean;
  can_edit_talent: boolean;
  cycle: { name: string; status: string } | null;
  scale: ScalePoint[] | null;
  people: TeamMember[];
}

export interface PersonPick {
  id: UUID;
  name: string;
  designation: string | null;
}

export interface CompCycle {
  id: UUID;
  name: string;
  effective_date: string | null;
  currency: string;
  status: string;
}

export interface CompRow {
  id: UUID;
  employee_id: UUID;
  name: string;
  designation: string | null;
  department: string | null;
  grade: string | null;
  current_base: number | string | null; // "••••" when field security masks it
  rating: number | null;
  compa_ratio: number | string | null;
  guideline: [number | null, number | null];
  merit_pct: number | null;
  bonus_amount: number | string | null;
  promotion_to_grade: string | null;
  justification: string | null;
  status: string;
  outside_guideline: boolean;
  band: { min: number; mid: number; max: number } | null;
}

export interface CompBudget {
  merit_pool: number;
  merit_used: number;
  merit_remaining: number;
  bonus_pool: number;
  bonus_used: number;
  bonus_remaining: number;
  over_budget: boolean;
}

export interface CompGrid {
  cycle: CompCycle;
  rows: CompRow[];
  budget: CompBudget;
  departments: { id: UUID; name: string }[];
  can_see_bands: boolean;
  not_in_worksheet: UUID[];
}

export interface SuccessorRow {
  employee_id: UUID;
  name: string;
  readiness: "ready_now" | "ready_1_2_years" | "ready_3_plus_years" | string;
  rank: number;
  development_actions: unknown[];
  assessed_at: string | null;
}

export interface CriticalRole {
  position_id: UUID;
  title: string;
  department: string | null;
  grade: string | null;
  holders: string[];
  coverage: "covered" | "at_risk" | "uncovered";
  counts: Record<string, number>;
  successors: SuccessorRow[];
}

export interface TalentProfile {
  employee_id: UUID;
  aspirations: string | null;
  mobility: Record<string, unknown> | null;
  career_path: unknown[] | null;
  flight_risk: string | null;
}

export const performanceExtraApi = {
  // reads (UI helpers)
  me: () => http.get<MyPerformance>(`${UI}/me`),
  reviewForm: (reviewId: UUID) => http.get<ReviewForm>(`${UI}/reviews/${reviewId}/form`),
  team: (scope: "mine" | "all") => http.get<TeamView>(`${UI}/team?scope=${scope}`),
  people: (q: string) => http.get<PersonPick[]>(`${UI}/people?q=${encodeURIComponent(q)}`),
  compCycles: () => http.get<CompCycle[]>(`${UI}/compensation/cycles`),
  compGrid: (cycleId: UUID, departmentId?: UUID) =>
    http.get<CompGrid>(`${UI}/compensation/cycles/${cycleId}/grid${departmentId ? `?department_id=${departmentId}` : ""}`),
  succession: () => http.get<{ positions: CriticalRole[]; can_edit: boolean }>(`${UI}/succession`),

  // writes (Part 10 endpoints)
  createGoal: (payload: { title: string; level: string; owner_employee_id?: UUID | null; parent_goal_id?: UUID | null; weightage?: number; description?: string; due_date?: string | null }) =>
    http.post<{ id: UUID }>(`${P}/goals`, payload),
  checkIn: (goalId: UUID, payload: { progress_pct: number; confidence?: number | null; comment?: string | null }) =>
    http.post<{ id: UUID }>(`${P}/goals/${goalId}/checkins`, payload),
  saveMyReview: (reviewId: UUID, payload: ReviewPayload) => http.post<unknown>(`${P}/me/reviews/${reviewId}`, payload),
  saveReviewAsAdmin: (reviewId: UUID, payload: ReviewPayload) => http.post<unknown>(`${P}/reviews/${reviewId}/submit`, payload),
  aiDraft: (reviewId: UUID) => http.post<{ ai_draft: { summary?: string; bias_flags?: string[] } | null }>(`${P}/me/reviews/${reviewId}/ai-draft`),
  talent: (employeeId: UUID) => http.get<TalentProfile>(`${P}/talent/${employeeId}`),
  patchTalent: (employeeId: UUID, payload: { mobility_json?: Record<string, unknown> }) => http.patch<{ employee_id: UUID }>(`${P}/talent/${employeeId}`, payload),
  buildWorksheet: (cycleId: UUID, employeeIds: UUID[]) => http.post<unknown[]>(`${P}/compensation/cycles/${cycleId}/worksheet`, { employee_ids: employeeIds }),
  updateProposal: (proposalId: UUID, payload: { merit_pct?: number; bonus_amount?: number; justification?: string }) =>
    http.patch<CompRow>(`${P}/compensation/proposals/${proposalId}`, payload),
  submitProposal: (proposalId: UUID) => http.post<CompRow>(`${P}/compensation/proposals/${proposalId}/submit`),
  exportCycle: (cycleId: UUID) => http.fetchBlob(`${P}/compensation/cycles/${cycleId}/export`),
  addSuccessor: (positionId: UUID, payload: { employee_id: UUID; readiness: string; rank?: number }) =>
    http.post<unknown>(`${P}/succession/positions/${positionId}/successors`, payload),
};
