// Part 20.3: employee self-service (backend/app/experience/ui_self_service_router.py)
import { http } from "./client";
import type { EmployeeProfile } from "./employeesApi";

export type EditableField = "preferred_name" | "pronouns" | "personal_email" | "phone" | "marital_status" | "blood_group" | "address" | "emergency_contact";
export interface EmergencyContact { name: string | null; relation: string | null; phone: string | null }
export type Editable = Partial<Record<Exclude<EditableField, "emergency_contact">, string | null>> & { emergency_contact?: EmergencyContact | null };
export interface ChangeRequest {
  id: string; employee_id: string; changes: Record<string, { old: unknown; new: unknown }>; note: string | null; status: "pending" | "approved" | "rejected" | "cancelled";
  requested_by: string | null; created_at: string | null; reviewed_by: string | null; reviewed_at: string | null; review_note: string | null;
  employee_name?: string; employee_code?: string | null;
}
export interface ExitStatus { key: "submitted" | "manager_approved" | "hr_approved" | "completed" | "withdrawn"; last_working_day: string | null;
  manager_approved_at: string | null; can_withdraw: boolean; early_release_requested: boolean; has_letter: boolean }
export interface MyProfile {
  linked: boolean; profile?: Omit<EmployeeProfile, "history">; editable?: Editable; fields?: EditableField[]; change_requests?: ChangeRequest[];
  exit?: ExitStatus | null; can_resign?: boolean; is_interviewer?: boolean;
}
export interface TeamExit { id: string; employee_name: string; employee_code: string | null; submitted_on: string | null; requested_lwd: string | null;
  reason_text: string | null; early_release_requested: boolean }
export type StartExitKind = "resigned" | "terminated" | "absconded" | "retirement" | "contract_end";

const B = "/api/v1/ui/self-service";
export const selfServiceApi = {
  me: () => http.get<MyProfile>(`${B}/me`),
  requestChange: (changes: Editable, note?: string) => http.post<ChangeRequest>(`${B}/me/change-requests`, { changes, note }),
  cancelChange: (id: string) => http.post<ChangeRequest>(`${B}/me/change-requests/${id}/cancel`, {}),
  letterBlob: (id: string) => http.fetchBlob(`${B}/me/letters/${id}.pdf`),
  uploadResignationLetter: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http.postForm<{ ok: boolean; name: string }>(`${B}/me/resignation/letter`, form);
  },
  withdraw: () => http.post<{ ok: boolean; status: string }>(`${B}/me/resignation/withdraw`, {}),
  teamExits: () => http.get<{ items: TeamExit[] }>(`${B}/team-exits`),
  managerApprove: (id: string, note?: string) => http.post<{ ok: boolean; items: TeamExit[] }>(`${B}/team-exits/${id}/approve`, { note }),
  changeRequests: (employeeId?: string) => http.get<{ items: ChangeRequest[] }>(`${B}/change-requests${employeeId ? `?employee_id=${employeeId}` : ""}`),
  review: (id: string, approve: boolean, note?: string) => http.post<ChangeRequest>(`${B}/change-requests/${id}/review`, { approve, note }),
  resignationLetterBlob: (separationId: string) => http.fetchBlob(`${B}/separations/${separationId}/resignation-letter`),
  startExit: (employeeId: string, body: { kind: StartExitKind; last_working_day: string; notes: string; confirm_now: boolean; send_notice: boolean }) =>
    http.post<{ separation_id: string; status: string }>(`${B}/employees/${employeeId}/start-exit`, body),
};

export async function openBlob(p: Promise<Blob | null>) {
  const blob = await p;
  if (blob) window.open(URL.createObjectURL(blob), "_blank", "noopener");
}
