// Part 17.7: "Candidate emails" (was HR Inbox) -- backend app/experience/ui_candidate_emails_router.py.
import { http } from "./client";
import type { HrInboundEmailRead, UUID } from "./types";

// Part 22.2: "Not matched" became "Closed" -- unlinked mail is in Needs action with suggested candidates
export type CandidateEmailTab = "needs_action" | "linked" | "closed";
export interface EmailSuggestion { candidate_id: UUID; application_id: UUID | null; name: string | null; email: string | null; job_title: string | null }
export type CandidateEmailTopic = "interview_time" | "documents" | "question" | "offer" | "withdrawal" | "automated" | "other";

export interface CandidateEmailItem {
  id: UUID;
  from_address: string;
  subject?: string | null;
  received_at?: string | null;
  candidate_id?: UUID | null;
  candidate_name?: string | null;
  application_id?: UUID | null;
  job_title?: string | null;
  topic?: CandidateEmailTopic | string | null;
  summary?: string | null;
  summary_source?: "ai" | "text" | string | null;
  status?: "needs_action" | "done" | string | null;
  done_at?: string | null;
  done_by?: string | null;
  from_name?: string | null;
  match_rule?: "email" | "alt_email" | "name" | "thread" | "manual" | string | null;
  suggestions?: EmailSuggestion[];
}

export interface CandidateEmailPage {
  tab: CandidateEmailTab;
  items: CandidateEmailItem[];
  counts: Record<CandidateEmailTab, number>;
  total: number;
  page: number;
  page_size: number;
  mailbox_connected: boolean;
}

const BASE = "/api/v1/ui/candidate-emails";

export const candidateEmailsApi = {
  list: (p: { tab: CandidateEmailTab; search?: string; page?: number; pageSize?: number }) => {
    const q = new URLSearchParams({ tab: p.tab, page: String(p.page ?? 1), page_size: String(p.pageSize ?? 25) });
    if (p.search) q.set("search", p.search);
    return http.get<CandidateEmailPage>(`${BASE}?${q.toString()}`);
  },
  setDone: (id: UUID, done: boolean) => http.post<{ id: UUID; status: string }>(`${BASE}/${id}/done`, { done }),
  rematch: () => http.post<{ checked: number; linked: number; ambiguous: number }>(`${BASE}/rematch`),
  link: (emailId: UUID, applicationId: UUID, rememberEmail: boolean) =>
    http.post<{ assigned: number }>(`/api/v1/ui/hr-inbox/${emailId}/assign`, { application_id: applicationId, include_same_sender: true, remember_email: rememberEmail }),
};

// The thread / candidate panes (components/inbox) still take the older HR-inbox row shape.
export function toInboundEmail(e: CandidateEmailItem): HrInboundEmailRead {
  return {
    id: e.id,
    from_address: e.from_address,
    subject: e.subject ?? null,
    body: null,
    received_at: e.received_at ?? null,
    matched_candidate_id: e.candidate_id ?? null,
    matched_candidate_name: e.candidate_name ?? null,
    matched_application_id: e.application_id ?? null,
    matched_job_title: e.job_title ?? null,
    created_at: e.received_at ?? "",
  };
}
