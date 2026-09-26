import { http } from "./client";

// Part 15.5: role-based home screens (backend/app/experience/home_router.py).

export type HomeKind = "hr" | "manager" | "employee";
export interface LayoutItem { i: string; x: number; y: number; w: number; h: number }

export interface MyHome {
  kind: HomeKind;
  own_kind: HomeKind;
  layout: LayoutItem[] | null;
  layout_source: "mine" | "company" | "built_in";
  can_set_defaults: boolean;
}

export interface HiringFlow {
  nodes: { key: string }[];
  links: { source: number; target: number; value: number }[];
  stages: Record<string, number>;
  total: number;
}

// Part 17.2 funnel (GET /api/v1/home/funnel).
export type FunnelPeriod = "7d" | "30d" | "90d" | "year";
export interface FunnelStage {
  key: "applied" | "screened" | "shortlisted" | "interviewed" | "offered" | "joined";
  label: string | null; // the company's own pipeline name, else the page's wording
  count: number;
  pct_of_previous: number | null;
  statuses: string[];
  drop: number; // did not reach the next stage
  stopped: number; // ...of which were not selected
  still_here: number; // ...of which are still waiting at this stage
}
export interface HiringFunnelData { period: FunnelPeriod; since: string; job_id: string | null; total: number; stages: FunnelStage[] }

export interface HomeAlert { key: string; tone: "coral" | "sun" | "sky" | "ok"; emoji: string; count: number; path: string }
export interface Office { id: string; name: string; lat: number | null; lng: number | null; count: number }
export interface TeamMember { id: string; name: string; status: string; designation: string | null }
export interface FeedbackDue { id: string; application_id: string | null; candidate: string | null; scheduled_at: string; meeting_link: string | null; past: boolean }
export interface GoalRow { id: string; title: string; level: string; progress_pct: number; status: string; owner_employee_id: string | null }
export interface MyTicket { id: string; number?: string; subject: string; status: string; created_at?: string | null }
export interface MyAsset { id: string; name?: string; asset_tag?: string; category?: string; allocation_id: string; acknowledged: boolean }

export const homeApi = {
  mine: (kind?: HomeKind) => http.get<MyHome>(`/api/v1/me/home${kind ? `?kind=${kind}` : ""}`),
  saveLayout: (kind: HomeKind, layout: LayoutItem[]) => http.put<{ ok: boolean }>("/api/v1/me/home/layout", { kind, layout }),
  resetLayout: (kind: HomeKind) => http.del<{ ok: boolean }>(`/api/v1/me/home/layout?kind=${kind}`),
  setCompanyDefault: (kind: HomeKind, layout: LayoutItem[]) => http.put<{ ok: boolean }>(`/api/v1/home/defaults/${kind}`, { kind, layout }),
  funnel: (period: FunnelPeriod, jobId?: string, locale?: string) =>
    http.get<HiringFunnelData>(`/api/v1/home/funnel?period=${period}${jobId ? `&job_id=${encodeURIComponent(jobId)}` : ""}${locale ? `&locale=${locale}` : ""}`),
  hiringFlow: () => http.get<HiringFlow>("/api/v1/home/hiring-flow"),
  alerts: () => http.get<{ alerts: HomeAlert[] }>("/api/v1/home/alerts"),
  offices: () => http.get<{ offices: Office[] }>("/api/v1/home/people-by-office"),
  myTeam: () => http.get<{ people: TeamMember[] }>("/api/v1/home/my-team"),
  myFeedback: () => http.get<{ items: FeedbackDue[] }>("/api/v1/home/my-feedback"),
  myGoals: () => http.get<{ mine: GoalRow[]; team: GoalRow[] }>("/api/v1/home/my-goals"),
  myTickets: () => http.get<MyTicket[]>("/api/v1/service-desk/me/tickets"),
  myAssets: () => http.get<MyAsset[]>("/api/v1/service-desk/me/assets"),
};
