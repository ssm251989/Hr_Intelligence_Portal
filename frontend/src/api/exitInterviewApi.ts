// fix 2026-10-06: exit interview answered by the employee, read by HR (backend/app/experience/ui_exit_interview_router.py)
import { http } from "./client";

export type QuestionType = "text" | "stars" | "yes_maybe_no" | "choice";
export interface ExitQuestion { id: string; type: QuestionType; required: boolean; label: Partial<Record<"en" | "hi" | "ta", string>>; options?: string[] }
export type Answers = Record<string, string | number | null>;
export interface ExitInterviewView {
  separation_id: string; status: "not_started" | "in_progress" | "submitted"; questions: ExitQuestion[]; answers: Answers;
  submitted_at: string | null; deadline: string | null; can_edit: boolean; note: string;
}
export interface ExitInterviewHr extends ExitInterviewView {
  ai_summary: { summary?: string; error?: string; generated_at?: string } | null; hr_notes: string; filled_by: "employee" | "hr_call" | null;
  filled_by_hr: { actor: string; at: string } | null; reminders: { at: string; by: string; automatic: boolean; email: string }[];
  can_record_call: boolean; ai_enabled: boolean;
}
export interface ExitInterviewSettings { questions: ExitQuestion[]; ai_summary: boolean; reminder_days: number }
export interface ExitReportBucket {
  count: number; manager_rating_avg: number | null; manager_rating_n: number; top_reasons: [string, number][];
  recommend?: Record<"yes" | "maybe" | "no", number>; return?: Record<"yes" | "maybe" | "no", number>;
}
export interface ExitReport { overall: ExitReportBucket; by_department: Record<string, ExitReportBucket>; by_manager: Record<string, ExitReportBucket>;
  by_tenure: Record<string, ExitReportBucket>; note: string }

const B = "/api/v1/ui/exit-interview";
export const exitInterviewApi = {
  mine: () => http.get<ExitInterviewView>(`${B}/me`),
  saveDraft: (answers: Answers) => http.put<ExitInterviewView>(`${B}/me`, { answers }),
  submit: (answers: Answers) => http.post<ExitInterviewView>(`${B}/me/submit`, { answers }),
  hr: (separationId: string) => http.get<ExitInterviewHr>(`${B}/separations/${separationId}`),
  remind: (separationId: string) => http.post<{ sent_to: string[]; status: string }>(`${B}/separations/${separationId}/remind`, {}),
  notes: (separationId: string, notes: string) => http.put<ExitInterviewHr>(`${B}/separations/${separationId}/notes`, { notes }),
  recordCall: (separationId: string, answers: Answers) => http.post<ExitInterviewHr>(`${B}/separations/${separationId}/record-call`, { answers }),
  summary: (separationId: string) => http.post<ExitInterviewHr>(`${B}/separations/${separationId}/summary`, {}),
  report: () => http.get<ExitReport>(`${B}/report`),
  settings: () => http.get<ExitInterviewSettings>(`${B}/settings`),
  saveSettings: (s: ExitInterviewSettings) => http.put<ExitInterviewSettings>(`${B}/settings`, s),
};
