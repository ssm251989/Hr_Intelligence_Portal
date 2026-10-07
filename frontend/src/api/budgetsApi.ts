// Part 18.15 -- department hiring budgets + finance dashboard (backend/app/experience/ui_budgets_router.py).
import { http } from "./client";

export interface DeptBudget {
  id: string | null; department: string; fiscal_year: string; allocated: number | null; quarters: Record<string, number> | null;
  alert_pct: number; on_exceed: "needs_approval" | "block"; reserved: number; committed: number; hires: number;
  remaining: number | null; used_pct: number | null; alert: boolean; exceeded: boolean;
}
export interface FinanceData {
  fiscal_year: string;
  totals: { allocated: number; reserved: number; committed: number; remaining: number };
  departments: DeptBudget[];
  trend: { month: string; reserved: number; committed: number }[];
  top_roles: { job_title: string; department: string; amount: number; hires: number }[];
  alerts: { department: string; kind: "near" | "exceeded"; used_pct: number | null; remaining: number | null }[];
  history?: { department: string; job_title: string | null; amount: number; on: string; reason: string | null }[];  // Part 21.7
}

export const budgetsApi = {
  list: (fy?: string) => http.get<{ fiscal_year: string; fiscal_years: string[]; departments: DeptBudget[]; can_edit: boolean }>(
    `/api/v1/ui/budgets${fy ? `?fiscal_year=${encodeURIComponent(fy)}` : ""}`),
  save: (b: { department: string; fiscal_year: string; allocated: number; quarters?: Record<string, number> | null; alert_pct: number; on_exceed: string }) =>
    http.put<{ id: string; saved: boolean }>("/api/v1/ui/budgets", b),
  remove: (id: string) => http.del<void>(`/api/v1/ui/budgets/${id}`),
  dashboard: (fy?: string) => http.get<FinanceData>(`/api/v1/ui/budgets/dashboard${fy ? `?fiscal_year=${encodeURIComponent(fy)}` : ""}`),
  exportXlsx: (fy: string) => http.fetchBlob(`/api/v1/ui/budgets/export?fiscal_year=${encodeURIComponent(fy)}`),
};
