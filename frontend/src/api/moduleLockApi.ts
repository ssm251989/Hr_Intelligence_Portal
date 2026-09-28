// Part 18.4 -- module unlock passcode (backend/app/experience/module_lock_router.py).
import { http } from "./client";

export const ALL_MODULES = "__all__";

export interface ModuleLockItem {
  module: string;
  locked: boolean;
  unlocked_at: string | null;
  unlocked_by: string | null;
  has_own_passcode: boolean;
}

export interface ModuleLockStatus {
  enabled: boolean;
  active: boolean;
  mode: "one" | "per_module";
  passcode_set: boolean;
  try_again_at: string | null;
  can_unlock: boolean;
  modules: ModuleLockItem[];
}

const base = "/api/v1/modules/access";

export const moduleLockApi = {
  status: () => http.get<ModuleLockStatus>(base),
  unlock: (module: string, passcode: string) => http.post<ModuleLockStatus>(`${base}/unlock`, { module, passcode }),
  lock: (module: string) => http.post<ModuleLockStatus>(`${base}/lock`, { module }),
  changePasscode: (current: string, next: string, module?: string) =>
    http.post<{ changed: boolean }>(`${base}/passcode`, { current, new: next, module }),
};

/** Which lockable area a page path belongs to (bootstrap.module_locks.pages + nav lock keys). */
export function lockKeyForPath(
  path: string,
  pages: Record<string, string[]> | undefined,
  nav: { path: string; lock_key?: string | null }[] | undefined,
): string | null {
  const under = (p: string) => path === p || path.startsWith(`${p}/`);
  for (const [key, list] of Object.entries(pages ?? {})) if (list.some(under)) return key;
  for (const n of nav ?? []) if (n.lock_key && n.path !== "/" && under(n.path)) return n.lock_key;
  return null;
}
