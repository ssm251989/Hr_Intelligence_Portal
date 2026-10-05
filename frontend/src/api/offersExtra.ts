// Part 15.4 -- read helpers for the restyled Salary / BGV / Offers pages
// (backend/app/experience/ui_offers_router.py). Nothing here changes how a stage moves on.
import { http } from "./client";

export interface OffersUiContext {
  currency: string | null;
  offer_expiry_days: number;
}

export interface OfferTimelineEvent {
  kind: "sent" | "viewed" | "signed" | "joined" | "esign_failed" | "resent" | "revised";
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

// fix 2026-10-05: resend for signature + revised offers (backend app/offers/revisions.py)
export type OfferVersionStatus = "draft" | "sent" | "viewed" | "signed" | "declined" | "replaced" | "pending_approval" | "rejected" | "withdrawn";
export interface OfferChange { field: string; label: string; old: string; new: string }
export interface OfferVersionRow {
  id: string;
  version_no: number;
  status: OfferVersionStatus;
  sent_at: string | null;
  sent_by: string | null;
  reason_code: string | null;
  reason: string | null;
  reason_note: string | null;
  changes: OfferChange[];
  ctc_total: number | null;
  joining_date: string | null;
  designation: string | null;
  viewed_at: string | null;
  signed_at: string | null;
  replaced_at: string | null;
  resend_count: number;
  approval: { needed?: { code: string; over_pct?: number; band_max?: number; short_by?: number; department?: string }[]; approved_by?: string; rejected_by?: string; note?: string } | null;
  created_at: string | null;
}
export interface OfferValues {
  ctc_total: number | null;
  components: { code: string | null; name: string | null; amount: number | null }[];
  joining_date: string | null;
  designation: string;
  work_location: string;
  terms: string;
  expiry_date: string | null;
}
export interface OfferVersionsSummary {
  offer_id: string;
  version_no: number;
  status: OfferVersionStatus;
  signed: boolean;
  sent_count: number;
  last_sent_at: string | null;
  resend_available_at: string | null;
  can_resend: boolean;
  sign_url: string | null;
  values: OfferValues;
  band: { min: number | null; max: number | null } | null;
  reasons: { code: string; label: string }[];
  pending: OfferVersionRow | null;
  can_approve: boolean;
  history: OfferVersionRow[];
}
export interface OfferReviseInput {
  ctc_total: number | null;
  components?: { code: string | null; name: string | null; amount: number }[];
  joining_date: string | null;
  designation: string;
  work_location: string;
  terms: string;
  reason_code: string;
  reason_note?: string;
}
export interface OfferReviseResult {
  state: "sent" | "pending_approval" | "rejected";
  version_no: number;
  changes?: OfferChange[];
  emailed?: boolean;
  summary: OfferVersionsSummary;
}

const BASE = "/api/v1/ui/offers";

export const offersExtraApi = {
  context: () => http.get<OffersUiContext>(`${BASE}/context`),
  offerTimeline: (applicationId: string) => http.get<OfferTimelineResponse>(`${BASE}/applications/${applicationId}/offer-timeline`),
  bgvTimeline: (applicationId: string) => http.get<BgvTimelineResponse>(`${BASE}/applications/${applicationId}/bgv-timeline`),
  template: () => http.get<OfferTemplate>(`${BASE}/template`),
  previewTemplate: (html_tpl: string, sample_context: Record<string, string> = {}) =>
    http.post<{ html: string | null; error: string | null }>(`${BASE}/template/preview`, { html_tpl, sample_context }),
  versions: (applicationId: string) => http.get<OfferVersionsSummary>(`${BASE}/applications/${applicationId}/offer-versions`),
  resend: (applicationId: string) =>
    http.post<{ email_status: string; sent_count: number; last_sent_at: string; summary: OfferVersionsSummary }>(`${BASE}/applications/${applicationId}/offer/resend`, {}),
  revise: (applicationId: string, body: OfferReviseInput) => http.post<OfferReviseResult>(`${BASE}/applications/${applicationId}/offer/revise`, body),
  decideRevision: (applicationId: string, versionId: string, approve: boolean, note?: string) =>
    http.post<OfferReviseResult>(`${BASE}/applications/${applicationId}/offer/revisions/${versionId}/decide`, { approve, note }),
  versionPdf: (applicationId: string, versionNo: number) => http.fetchBlob(`${BASE}/applications/${applicationId}/offer/versions/${versionNo}/pdf`),
  saveTemplate: (html_tpl: string, publish = true) =>
    http.post<{ id: string; version: number; status: string }>(`${BASE}/template`, { html_tpl, publish }),
};
