// Part 15.4 -- read helpers for the restyled Salary / BGV / Offers pages
// (backend/app/experience/ui_offers_router.py). Nothing here changes how a stage moves on.
import { http } from "./client";

export interface OffersUiContext {
  currency: string | null;
  offer_expiry_days: number;
}

export interface OfferTimelineEvent {
  kind: "sent" | "viewed" | "signed" | "joined" | "esign_failed";
  action: string;
  at: string | null;
  by?: string | null;
}

export interface ApprovalStepInfo {
  id: string;
  name: string;
  step: string;
  status: string;
  action?: string | null;
  acted_by?: string | null;
  comment?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  due_at?: string | null;
}

export interface OfferTimelineResponse {
  offer: {
    id: string;
    created_at: string | null;
    sent_at: string | null;
    signed: boolean;
    expiry_date: string | null;
    expiry_is_default: boolean;
    joining_date: string | null;
    esign: "docusign" | "manual" | null;
  } | null;
  events: OfferTimelineEvent[];
  approvals: ApprovalStepInfo[];
  expiry_days: number;
}

export interface BgvTimelineEvent {
  kind: string;
  at: string | null;
  by?: string | null;
  decision?: string | null;
  doc_id?: string;
  doc_type?: string | null;
  result?: string | null;
  case_id?: string;
}

export interface BgvVendorCase {
  id: string;
  status: string;
  decision: string;
  discrepancy?: string | null;
  checks: { type: string; status: string; notes?: string | null }[];
}

export interface BgvTimelineResponse {
  events: BgvTimelineEvent[];
  vendor_cases: BgvVendorCase[];
}

export interface OfferTemplate {
  id: string | null;
  version: number;
  status: string;
  name: string;
  html_tpl: string;
  sample_context: Record<string, string>;
}

const BASE = "/api/v1/ui/offers";

export const offersExtraApi = {
  context: () => http.get<OffersUiContext>(`${BASE}/context`),
  offerTimeline: (applicationId: string) => http.get<OfferTimelineResponse>(`${BASE}/applications/${applicationId}/offer-timeline`),
  bgvTimeline: (applicationId: string) => http.get<BgvTimelineResponse>(`${BASE}/applications/${applicationId}/bgv-timeline`),
  template: () => http.get<OfferTemplate>(`${BASE}/template`),
  previewTemplate: (html_tpl: string, sample_context: Record<string, string> = {}) =>
    http.post<{ html: string | null; error: string | null }>(`${BASE}/template/preview`, { html_tpl, sample_context }),
  saveTemplate: (html_tpl: string, publish = true) =>
    http.post<{ id: string; version: number; status: string }>(`${BASE}/template`, { html_tpl, publish }),
};
