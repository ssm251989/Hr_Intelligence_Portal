// Part 21.4: BGV Download all + BGV vendors (backend/app/experience/ui_bgv_vendor_router.py)
import { apiUrl, http } from "./client";

export interface BgvVendor { id: string; name: string; email: string | null; checks: { check: string; price: number | null }[]; turnaround_days: number | null }
export interface BgvAssignment {
  id: string; application_id: string; agency_id: string; agency: string | null; agency_email: string | null; checks: string[]; due_date: string | null;
  status: "assigned" | "in_progress" | "report_received" | "decided" | "cancelled"; overdue: boolean; link_expires_at: string; opened_at: string | null;
  report_name: string | null; report_note: string | null; report_uploaded_at: string | null; decision: string | null; cost: number | null;
  created_by: string | null; created_at: string | null; cancelled_at: string | null; cancel_reason: string | null; link?: string; email?: string | null;
  reminders: { on: string; kind: string; email: string | null }[];
}
export interface VendorView {
  company: string; vendor: string | null; candidate: string; job_title: string; checks: string[]; due_date: string | null; status: string;
  link_expires_at: string; documents: { id: string; label: string; type: string; available: boolean }[];
  report: { name: string; uploaded_at: string | null } | null; can_upload: boolean;
}

const B = "/api/v1/ui/bgv";
const PUB = "/api/v1/public/bgv-vendor";
export const bgvVendorApi = {
  vendors: () => http.get<{ items: BgvVendor[] }>(`${B}/vendors`),
  assignments: (appId: string) => http.get<{ items: BgvAssignment[]; status: string }>(`${B}/${appId}/assignments`),
  assign: (appId: string, body: { agency_id: string; checks: string[]; due_date?: string | null }) => http.post<BgvAssignment>(`${B}/${appId}/assign`, body),
  cancel: (id: string, reason?: string) => http.post<BgvAssignment>(`${B}/assignments/${id}/cancel`, { reason }),
  reportBlob: (id: string) => http.fetchBlob(`${B}/assignments/${id}/report`),
  downloadAllBlob: (appId: string) => http.fetchBlob(`${B}/${appId}/download-all`),
  // bulk: up to 20 -> the ZIP itself; more -> {export_id} prepared in the background
  downloadAllBulk: async (ids: string[]): Promise<{ blob?: Blob; export_id?: string }> => {
    const r = await http.postBlob(`${B}/download-all`, { application_ids: ids });
    return r.blob ? { blob: r.blob } : { export_id: String(r.json?.export_id ?? "") };
  },
  exportBlob: (exportId: string) => http.fetchBlob(`${B}/exports/${exportId}`),
  vendorView: (token: string) => http.get<VendorView>(`${PUB}/${token}`),
  vendorFileUrl: (token: string, docId: string) => apiUrl(`${PUB}/${token}/files/${docId}`) ?? "",
  vendorReport: (token: string, file: File, note: string) => {
    const form = new FormData();
    form.append("file", file);
    if (note) form.append("note", note);
    return http.postForm<{ ok: boolean }>(`${PUB}/${token}/report`, form);
  },
};

export function saveBlob(blob: Blob, name: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
}
