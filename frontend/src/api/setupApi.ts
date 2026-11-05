// Part 17.10 -- setup checklist values, first office, employees file, ready-made templates
// (backend/app/experience/api_router.py + setup_wizard.py + setup_templates.py).
import { http, type SetupProgress } from "./client";

export interface SetupValues {
  company: { display_name: string | null; legal_name: string | null; timezone: string | null; locale: string | null; currency: string | null };
  entities: { id: string; name: string }[];
  locations: { id: string; name: string; state: string | null; lat: string | null; lng: string | null }[];
  branding: { primary_color: string | null; secondary_color: string | null; logo_url: string | null };
  mailbox: { connected: boolean; detail: string };
  employees: { count: number };
  modules: string[];
  available_modules?: { code: string; on: boolean; offered: boolean }[]; // Part 18.5
  template: { template?: string; name?: string; applied_at?: string; source?: string } | null;
  admins: { email: string; name: string | null }[];
}

export interface SetupTemplate {
  key: string;
  name: string;
  line: string;
  adds: { what: string; items: string[] }[];
  note: string;
}

export interface EmployeesFileResult { batch_id: string; rows: number; errors: number; committed: number; skipped_invalid?: number; progress?: SetupProgress }

export const setupApi = {
  values: () => http.get<SetupValues>("/api/v1/setup/values"),
  addEntityLocation: (payload: { entity_name: string; location_name: string; city?: string; state?: string }) =>
    http.post<SetupProgress>("/api/v1/setup/entities-locations", payload),
  employeesFile: (file: File, commit: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("commit", String(commit));
    return http.postForm<EmployeesFileResult>("/api/v1/setup/employees-file", form);
  },
  employeesSample: () => http.fetchBlob("/api/v1/setup/employees-sample"),
  templates: () => http.get<SetupTemplate[]>("/api/v1/setup/templates"),
  applyTemplate: (key: string) => http.post<{ template: string; name: string; added: Record<string, number>; progress: SetupProgress }>(`/api/v1/setup/templates/${key}/apply`),
  saveBrandColours: (payload: { primary_color?: string; secondary_color?: string }) => http.put<unknown>("/api/v1/comms/brand-theme", payload),
};

// Part 18.5: every module the company may switch on (Settings > Advanced > Modules)
export const modulesApi = {
  list: () => http.get<{ code: string; on: boolean; offered: boolean }[]>("/api/v1/setup/modules"),
  save: (modules: string[]) => http.post<SetupProgress>("/api/v1/setup/modules", { modules, scope: "all" }),
};
