// Part 15.6 -- Helpdesk / Assets / Exits pages. Wraps the Part 11 service-desk API
// (/api/v1/service-desk/*) and the read-only page helpers in
// backend/app/experience/ui_servicedesk_router.py (/api/v1/ui/servicedesk/*).
import { http } from "./client";

const SD = "/api/v1/service-desk";
const UI = "/api/v1/ui/servicedesk";
const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
};

// ---- shared ----

export interface Category {
  code: string;
  label: string;
  emoji?: string | null;
  hint?: string | null;
}

export interface PersonLite {
  id: string;
  name: string | null;
  code: string;
  status: string;
}

// ---- helpdesk ----

export interface TicketSla {
  has_sla: boolean;
  response_due_at?: string | null;
  resolution_due_at?: string | null;
  response_breached?: boolean;
  resolution_breached?: boolean;
  resolution_elapsed_pct?: number;
  paused?: boolean;
}

export interface Ticket {
  id: string;
  number: string;
  category_code: string;
  subcategory_code: string | null;
  priority: string;
  subject: string;
  description: string | null;
  channel: string;
  status: string;
  confidential: boolean;
  queue_code: string | null;
  assignee_user_id: string | null;
  requester_employee_id: string | null;
  created_at: string | null;
  escalation_level: number;
  csat_score: number | null;
  sla: TicketSla | null;
}

export interface TicketComment {
  author: string;
  body: string;
  internal: boolean;
  is_agent: boolean;
  at: string | null;
}

export interface TicketMeta {
  first_responded_at: string | null;
  resolved_at: string | null;
  paused_at: string | null;
  response_due_at: string | null;
  resolution_due_at: string | null;
  escalation_level: number;
  csat_score: number | null;
  requester_name: string | null;
  assignee_name: string | null;
  team_name: string | null;
  created_at: string | null;
}

export interface KbHit {
  id: string;
  slug: string;
  title: string;
  excerpt: string;
}

export interface AgentsInfo {
  agents: { id: string; name: string | null; me: boolean }[];
  teams: { code: string; name: string }[];
}

// ---- assets ----

export interface Asset {
  id: string;
  asset_tag: string;
  category_code: string;
  name: string;
  serial_number: string | null;
  status: string;
  warranty_until: string | null;
  vendor: string | null;
  book_value: number | null;
  allocated_to: string | null;
}

export interface MyAsset extends Asset {
  allocation_id: string;
  acknowledged: boolean;
}

export interface AssetMeta {
  allocation_id: string;
  employee_id: string;
  employee_name: string | null;
  allocated_at: string | null;
  acknowledged_at: string | null;
}

export interface CatalogueItem extends Category {
  in_stock: number;
}

export interface AssetRequestRow {
  id: string;
  category_code: string;
  reason: string | null;
  status: string;
  source: string;
  created_at: string | null;
  employee_id: string;
  employee_name?: string | null;
  fulfilled_asset?: { name: string; asset_tag: string } | null;
}

export interface NewAsset {
  asset_tag: string;
  category_code: string;
  name: string;
  serial_number?: string | null;
  vendor?: string | null;
  purchase_date?: string | null;
  warranty_until?: string | null;
}

// ---- exits ----

export interface ClearanceItem {
  id: string;
  department: string;
  kind: string;
  title: string;
  status: string;
  blocks_relieving: boolean;
  owner_name: string | null;
  cleared_by: string | null;
  cleared_at: string | null;
  notes?: string | null;
  amount_due: number | null;
  asset_allocation_id: string | null;
}

export interface LetterRef {
  id: string;
  generated_at: string | null;
}

export interface SeparationRow {
  id: string;
  employee_id: string;
  employee_name: string | null;
  employee_code: string | null;
  type: string;
  status: string;
  submitted_on: string | null;
  requested_lwd: string | null;
  approved_lwd: string | null;
  notice_period_days: number;
  reason_code: string | null;
  reason_text: string | null;
  items_total: number;
  items_pending: number;
  blocking_pending: number;
  exit_interview_done: boolean;
  exit_interview?: { answers?: Record<string, unknown>; submitted_at?: string } | null;
  exit_interview_ai_summary?: Record<string, unknown> | null;
  letters: { relieving: LetterRef | null; experience: LetterRef | null };
  rehire_eligible: boolean | null;
  items?: ClearanceItem[];
}

export interface MySeparation {
  linked: boolean;
  employee_status?: string;
  separation: SeparationRow | null;
  notice_period_days: number | null;
}

export interface LetterHtml {
  id: string;
  generated_at: string | null;
  html: string;
}

export const serviceDeskExtra = {
  // shared
  categories: (kind: "ticket" | "asset" | "exit_reason", locale = "en") => http.get<Category[]>(`${UI}/categories${qs({ kind, locale })}`),
  people: (params: { q?: string; ids?: string[] }) => http.get<PersonLite[]>(`${UI}/people${qs({ q: params.q, ids: params.ids?.join(",") })}`),

  // helpdesk -- employee
  kbSearch: (q: string) => http.get<KbHit[]>(`${SD}/kb/search${qs({ q })}`),
  kbDeflected: (articleId: string, helpful: boolean) => http.post<{ ok: boolean }>(`${SD}/kb/${articleId}/deflected`, { helpful }),
  raiseTicket: (payload: { category_code: string; subject: string; description?: string; priority?: string }) =>
    http.post<Ticket>(`${SD}/me/tickets`, payload),
  myTickets: () => http.get<Ticket[]>(`${SD}/me/tickets`),
  ticket: (id: string) => http.get<Ticket & { comments: TicketComment[] }>(`${SD}/tickets/${id}`),
  comment: (id: string, body: string, internal = false) => http.post<{ id: string }>(`${SD}/tickets/${id}/comments`, { body, internal }),
  rate: (id: string, score: number, comment?: string) => http.post<{ csat_score: number }>(`${SD}/me/tickets/${id}/csat`, { score, comment }),
  ticketsMeta: (ids: string[]) => http.get<Record<string, TicketMeta>>(`${UI}/tickets-meta${qs({ ids: ids.join(",") })}`),

  // helpdesk -- agents
  queue: (params: { status?: string; team?: string; mine?: boolean; page?: number }) =>
    http.get<{ total: number; page: number; page_size: number; items: Ticket[] }>(
      `${SD}/tickets${qs({ status: params.status, queue_code: params.team, assignee: params.mine ? "me" : undefined, page: params.page ?? 1, page_size: 25 })}`,
    ),
  setStatus: (id: string, status: string) => http.post<Ticket>(`${SD}/tickets/${id}/status`, { status }),
  assign: (id: string, assignee_user_id: string | null, queue_code?: string | null) =>
    http.post<Ticket>(`${SD}/tickets/${id}/assign`, { assignee_user_id, queue_code: queue_code || undefined }),
  agents: () => http.get<AgentsInfo>(`${UI}/agents`),

  // assets
  assets: (params: { status?: string; category?: string; page?: number }) =>
    http.get<{ total: number; items: Asset[] }>(`${SD}/assets${qs({ status: params.status, category_code: params.category, page: params.page ?? 1, page_size: 25 })}`),
  assetsMeta: (ids: string[]) => http.get<Record<string, AssetMeta>>(`${UI}/assets-meta${qs({ ids: ids.join(",") })}`),
  createAsset: (payload: NewAsset) => http.post<Asset>(`${SD}/assets`, payload),
  allocate: (assetId: string, employeeId: string) => http.post<{ allocation_id: string }>(`${SD}/assets/${assetId}/allocate`, { employee_id: employeeId }),
  returnAsset: (allocationId: string, condition: "good" | "damaged" | "lost", notes?: string) =>
    http.post<{ returned_at: string }>(`${SD}/allocations/${allocationId}/return`, { condition, notes }),
  maintenance: (assetId: string, payload: { performed_on: string; description: string; cost?: number | null; vendor?: string | null }) =>
    http.post<{ id: string }>(`${SD}/assets/${assetId}/maintenance`, payload),
  myAssets: () => http.get<MyAsset[]>(`${SD}/me/assets`),
  acknowledge: (allocationId: string, text: string) => http.post<{ acknowledged_at: string }>(`${SD}/me/allocations/${allocationId}/acknowledge`, { text }),
  catalogue: (locale = "en") => http.get<CatalogueItem[]>(`${UI}/catalogue${qs({ locale })}`),
  requestAsset: (category_code: string, reason?: string) => http.post<{ id: string; status: string }>(`${SD}/me/asset-requests`, { category_code, reason }),
  myRequests: () => http.get<AssetRequestRow[]>(`${UI}/me/asset-requests`),
  requests: (status?: string) => http.get<AssetRequestRow[]>(`${UI}/asset-requests${qs({ status })}`),
  decide: (requestId: string, approve: boolean) => http.post<{ id: string; status: string }>(`${SD}/asset-requests/${requestId}/decision`, { approve }),
  fulfil: (requestId: string, assetId?: string | null) => http.post<{ allocation_id: string }>(`${SD}/asset-requests/${requestId}/fulfil`, { asset_id: assetId || undefined }),

  // exits
  mySeparation: () => http.get<MySeparation>(`${UI}/me/separation`),
  resign: (payload: { requested_lwd?: string | null; reason_code?: string | null; reason_text?: string | null }) => http.post<unknown>(`${SD}/me/resignation`, payload),
  separations: (includeClosed: boolean) => http.get<{ today: string; items: SeparationRow[] }>(`${UI}/separations-overview${qs({ include_closed: includeClosed })}`),
  approveLwd: (id: string, lwd: string, waived_days = 0, buyout_days = 0) => http.post<unknown>(`${SD}/separations/${id}/approve-lwd`, { lwd, waived_days, buyout_days }),
  retention: (id: string, notes: string, retained: boolean) => http.post<unknown>(`${SD}/separations/${id}/retention`, { notes, retained }),
  withdraw: (id: string) => http.post<unknown>(`${SD}/separations/${id}/withdraw`),
  clearItem: (itemId: string, payload: { waive?: boolean; notes?: string | null; amount_due?: number | null }) => http.post<ClearanceItem>(`${SD}/clearance-items/${itemId}/clear`, payload),
  exitInterview: (id: string, answers: Record<string, unknown>, summarize = false) =>
    http.post<{ exit_interview: unknown; ai_summary: unknown }>(`${SD}/separations/${id}/exit-interview${summarize ? "?summarize=true" : ""}`, { answers }),
  issueLetters: (id: string) => http.post<{ relieving_letter_id: string; experience_letter_id: string | null }>(`${SD}/separations/${id}/relieving-letter`, {}),
  complete: (id: string, payload: { rehire_eligible: boolean; alumni_opt_in?: boolean; regretted?: boolean | null }) => http.post<unknown>(`${SD}/separations/${id}/complete`, payload),
  letters: (id: string) => http.get<{ relieving: LetterHtml | null; experience: LetterHtml | null }>(`${UI}/separations/${id}/letters`),
  exportUrl: `${SD}/separations-export`,
};
