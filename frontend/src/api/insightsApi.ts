import { http } from "./client";

// Part 15.6: Analytics maps + report builder helpers
// (backend/app/experience/ui_insights_router.py and /api/v1/intelligence).

export interface HeatCell { city: string; lat: number | null; lng: number | null; count: number }
export interface CandidateHeat { cells: HeatCell[]; hidden_small: number; unknown: number; min_cell: number; total: number }
export interface JobLocation { location: string | null; city: string | null; lat: number | null; lng: number | null; count: number }
export interface ReportScheduleRow {
  id: string; report_id: string; report_name: string; frequency: "daily" | "weekly" | "monthly" | string; hour: number;
  day_of_week: number | null; day_of_month: number | null; recipients: string[]; format: string; enabled: boolean;
  next_run_at: string | null; last_run_at: string | null;
}
export interface ScheduleCreate {
  frequency: "daily" | "weekly" | "monthly"; hour: number; recipients: string[]; template_key: string;
  format: "csv" | "xlsx"; day_of_week?: number; day_of_month?: number;
}

// The email the scheduled report goes out with (created under Settings -> Email templates).
export const REPORT_TEMPLATE_KEY = "analytics.report.scheduled";

export const insightsApi = {
  candidateHeat: () => http.get<CandidateHeat>("/api/v1/ui/insights/candidate-heat"),
  jobsByLocation: () => http.get<{ locations: JobLocation[]; total: number }>("/api/v1/ui/insights/jobs-by-location"),
  schedules: () => http.get<ReportScheduleRow[]>("/api/v1/ui/insights/report-schedules"),
  createSchedule: (reportId: string, payload: ScheduleCreate) =>
    http.post<{ id: string; next_run_at: string }>(`/api/v1/intelligence/reports/${reportId}/schedules`, payload),
  exportReport: (reportId: string, format: "csv" | "xlsx") => http.fetchBlob(`/api/v1/intelligence/reports/${reportId}/export?format=${format}`),
};
