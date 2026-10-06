// feat 2026-10-06: actionable exit checklist (backend/app/experience/ui_exit_checklist_router.py)
import { http } from "./client";

export type ItemStatus = "todo" | "requested" | "waiting_confirmation" | "done" | "not_applicable" | "blocked";
export type ItemKind = "asset_recovery" | "id_card" | "no_assets" | "access_revocation" | "finance_settlement" | "handover_signoff" | "exit_docs"
  | "clearance" | "knowledge_transfer";
export type ItemAction = "request_return" | "employee_returned" | "received" | "lost" | "revoke_now" | "revoke_last_day" | "confirm_manual" | "settle"
  | "sign_off" | "generate_letters" | "interview_na" | "mark_done" | "block" | "unblock" | "not_applicable" | "reopen";
export interface HistoryEntry { at: string; actor: string; action: string; note?: string }
export interface ChecklistItem {
  id: string; title: string; kind: ItemKind; status: ItemStatus; owner_role: string | null; department: string; owner_name: string | null;
  owner_email: string | null; due_date: string | null; required: boolean; reason: string | null; auto_rule: string | null; overdue: boolean;
  details: Record<string, any>; history: HistoryEntry[]; amount_due: number | null; done_by: string | null; done_at: string | null;
  actions: ItemAction[]; separation_id?: string; employee_name?: string;
}
export interface Checklist {
  separation_id: string | null; status: string | null; last_working_day?: string | null; items: ChecklistItem[]; done?: number; total?: number;
  percent?: number; pending?: number; past_last_day?: boolean; pending_after_last_day?: boolean; can_manage?: boolean; completion_note?: string | null;
  letters?: { relieving: string | null; experience: string | null }; letters_emailed_at?: string | null;
  employee?: { id: string; name: string; code: string; status: string } | null;
}
export interface ChecklistConfigItem {
  key: string; title: string; owner_role: string; owner_email?: string | null; due_days_before: number; required: boolean; auto: string; kind?: string; cards?: string[];
}
export interface ChecklistSettings { items: ChecklistConfigItem[]; owner_roles: string[]; auto_rules: string[] }

const B = "/api/v1/ui/exit-checklist";
export const exitChecklistApi = {
  mine: () => http.get<Checklist>(`${B}/me`),
  myTasks: () => http.get<{ items: ChecklistItem[] }>(`${B}/my-tasks`),
  get: (separationId: string) => http.get<Checklist>(`${B}/separations/${separationId}`),
  act: (itemId: string, action: ItemAction, data: Record<string, unknown> = {}) => http.post<Checklist>(`${B}/items/${itemId}/act`, { action, data }),
  upload: (itemId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http.postForm<{ file: string; name: string }>(`${B}/items/${itemId}/upload`, form);
  },
  fileBlob: (ref: string) => http.fetchBlob(`${B}/files/${ref}`),
  letterBlob: (letterId: string) => http.fetchBlob(`${B}/letters/${letterId}.pdf`),
  extend: (separationId: string, lastWorkingDay: string) => http.post<Checklist>(`${B}/separations/${separationId}/extend`, { last_working_day: lastWorkingDay }),
  complete: (separationId: string, reason?: string) => http.post<Checklist>(`${B}/separations/${separationId}/complete`, { reason: reason || null }),
  settings: () => http.get<ChecklistSettings>(`${B}/settings`),
  saveSettings: (items: ChecklistConfigItem[]) => http.put<ChecklistSettings>(`${B}/settings`, { items }),
};
