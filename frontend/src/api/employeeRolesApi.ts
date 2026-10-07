// Part 22.4: Employees > Assign roles (backend app/experience/ui_employee_roles_router.py).
import { http } from "./client";

export interface RoleOption { id: string; name: string; key: string | null; system: boolean; description: string | null }
export interface EmployeeRoleState {
  employee_id: string; name: string; status: string; has_account: boolean; login: string | null; role_ids: string[]; other_roles: string[];
}
export interface RoleResult {
  employee_id: string; name: string; result: "changed" | "unchanged" | "no_account" | "last_admin" | "error";
  added?: string[]; removed?: string[]; invited?: boolean; emailed?: boolean | string; error?: string;
}
export interface ApplyRolesIn {
  employee_ids: string[]; set_role_ids?: string[]; add_role_ids?: string[]; remove_role_ids?: string[]; create_accounts?: boolean;
  interviewer?: { skills: string[]; pool_ids: string[]; max_per_day?: number | null } | null;
}

const B = "/api/v1/ui/employee-roles";
export const employeeRolesApi = {
  catalog: () => http.get<{ roles: RoleOption[] }>(`${B}/catalog`),
  state: (ids: string[]) => http.get<{ items: EmployeeRoleState[] }>(`${B}?ids=${ids.join(",")}`),
  apply: (body: ApplyRolesIn) => http.post<{ results: RoleResult[] }>(B, body),
};
