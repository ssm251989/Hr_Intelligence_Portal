// Part 17.12 -- interviewer availability + pools kept in the app (backend/app/experience/ui_interviewers_router.py).
import { http } from "./client";

export type DayKey = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export const DAY_KEYS: DayKey[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export interface TimeRange { start: string; end: string }
export type WeeklyPattern = Partial<Record<DayKey, TimeRange[] | false>>;
export interface BlockedDate { date: string; available?: boolean; note?: string }

export interface Availability {
  email: string;
  name: string;
  weekly_pattern: WeeklyPattern;
  exceptions: BlockedDate[];
  max_interviews_per_day: number | null;
  max_interviews_per_week: number | null;
  has_availability: boolean;
  booked_next_7_days: number;
  pools: string[];
  free_tomorrow: string[];
  source: string | null;
  suggested?: boolean;
  upcoming?: { id: string; scheduled_at: string; application_id: string }[];
}

export interface AvailabilityIn {
  weekly_pattern: WeeklyPattern;
  exceptions: BlockedDate[];
  max_interviews_per_day?: number | null;
  max_interviews_per_week?: number | null;
  interviewer_name?: string;
}

export interface Pool { id: string; name: string; job_role_id: string | null; job_title: string | null; skills: string[]; member_emails: string[]; active: boolean; source: string }
export interface PoolIn { name: string; job_role_id?: string | null; skills: string[]; member_emails: string[]; active: boolean }

export interface TrackerImport {
  dry_run: boolean;
  pools: number;
  interviewers: number;
  names_without_email: string[];
  pools_detail: { name: string; job_title: string; job_found: boolean; members: string[] }[];
  created_pools?: number;
  created_interviewers?: number;
}

const B = "/api/v1/ui/interviewers";

export const interviewersApi = {
  me: () => http.get<Availability>(`${B}/me`),
  saveMe: (payload: AvailabilityIn) => http.put<Availability>(`${B}/me`, payload),
  all: () => http.get<{ items: Availability[]; slot_times_tomorrow: string[] }>(B),
  saveFor: (email: string, payload: AvailabilityIn) => http.put<Availability>(`${B}/${encodeURIComponent(email)}`, payload),
  pools: () => http.get<Pool[]>(`${B}/pools`),
  createPool: (payload: PoolIn) => http.post<Pool>(`${B}/pools`, payload),
  updatePool: (id: string, payload: PoolIn) => http.patch<Pool>(`${B}/pools/${id}`, payload),
  deletePool: (id: string) => http.del<void>(`${B}/pools/${id}`),
  importExcel: (file: File, dryRun: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", String(dryRun));
    return http.postForm<TrackerImport>(`${B}/import-excel`, form);
  },
  importSample: () => http.fetchBlob(`${B}/import-sample`),
};
