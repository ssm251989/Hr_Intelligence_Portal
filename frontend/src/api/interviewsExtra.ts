import { http } from "./client";
import type { InterviewListRow, UUID } from "./types";

// Part 15 step 15.4: the restyled Interviews + HR Inbox screens' extra reads/actions
// (backend/app/experience/ui_interviews_router.py).

export interface MyInterviewRow {
  interview: InterviewListRow;
  candidate_location?: string | null;
  candidate_phone?: string | null;
  total_experience_years?: number | null;
  top_skills: string[];
  missing_skills: string[];
  /** Part 17.4: the Match score, when the server sends it; else match_score is shown. */
  composite_score?: number | null;
  match_score?: number | null;
  feedback_submitted: boolean;
  // Part 20.4
  candidate_id?: string | null;
  application_id?: string | null;
  has_resume?: boolean;
  interviewer_response?: { kind: "declined" | "reschedule"; reason: string | null; proposed: string | null; at: string; by: string } | null;
}

export interface PanelEntry {
  interview_id: UUID;
  interviewer_name?: string | null;
  scheduled_at?: string | null;
  technical_rating?: number | null;
  communication_rating?: number | null;
  overall_rating?: number | null;
  comments?: string | null;
  decision?: string | null;
  submitted: boolean;
}

export interface PanelFeedback {
  hidden: boolean;
  my_feedback_submitted: boolean;
  is_panel_member: boolean;
  others: PanelEntry[];
}

export interface ThreadMessage {
  id: UUID;
  from_address: string;
  to_address?: string | null;
  subject?: string | null;
  body?: string | null;
  received_at?: string | null;
  created_at?: string | null;
  matched_candidate_id?: UUID | null;
  matched_application_id?: UUID | null;
}

export interface ReplySnippet {
  key: string;
  locale: string;
  subject?: string | null;
  text: string;
}

export interface AssignResult {
  assigned: number;
  candidate_id: UUID;
  application_id: UUID;
}

export const interviewsExtraApi = {
  mine: (includeDone = true) => http.get<MyInterviewRow[]>(`/api/v1/ui/interviews/mine?include_done=${includeDone}`),
  panel: (interviewId: UUID) => http.get<PanelFeedback>(`/api/v1/ui/interviews/${interviewId}/panel`),
  // Part 20.4: the interviewer can't make a booked interview
  decline: (interviewId: UUID, reason: string) => http.post<{ ok: boolean }>(`/api/v1/ui/interviews/${interviewId}/decline`, { reason }),
  proposeTime: (interviewId: UUID, proposed: string, reason?: string) =>
    http.post<{ ok: boolean }>(`/api/v1/ui/interviews/${interviewId}/propose-time`, { proposed, reason }),
};

export const inboxExtraApi = {
  thread: (emailId: UUID) => http.get<{ messages: ThreadMessage[] }>(`/api/v1/ui/hr-inbox/${emailId}/thread`),
  assign: (emailId: UUID, applicationId: UUID, includeSameSender = true) =>
    http.post<AssignResult>(`/api/v1/ui/hr-inbox/${emailId}/assign`, { application_id: applicationId, include_same_sender: includeSameSender }),
  snippets: () => http.get<ReplySnippet[]>("/api/v1/ui/hr-inbox/snippets"),
};
