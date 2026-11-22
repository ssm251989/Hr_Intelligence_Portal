// Part 32: where the company stands with CTD Techs (approved / grace / locked), the request for CTD, CTD's signed code,
// and loading a new signed CTD file.
import { http } from "./client";
import type { ActivationRequestInfo } from "./modulesApi";

export interface LicenceStatus {
  state: "approved" | "grace" | "locked";
  modules: string[];
  valid_until: string | null;
  expiring_in_days: number | null;
  expired: boolean;
  grace_days_left: number | null;
  set_up: boolean;
  approver: string | null;
  support: { email?: string; phone?: string; hours?: string };
  is_admin: boolean;
  request: ActivationRequestInfo | null;
  install_id: string | null;
}

export const licenceApi = {
  status: () => http.get<LicenceStatus>("/api/v1/licence/status"),
  requestAccess: (modules: string[] = []) => http.post<ActivationRequestInfo>("/api/v1/licence/request-access", { modules }),
  enterCode: (code: string) => http.post<{ activated: string[]; names: string; kind: string; valid_until: string | null }>("/api/v1/licence/code", { code }),
  loadConfig: (config: File, signature: File) => {
    const form = new FormData();
    form.append("config", config);
    form.append("signature", signature);
    return http.postForm<{ approver: string; issued_at: string | null }>("/api/v1/licence/config", form);
  },
};
