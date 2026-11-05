import type { ReactNode } from "react";

import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";

// Part 19.1: is a "Choose what you use" module active for this company? Unknown (bootstrap not
// loaded yet, or an older server) counts as active so nothing flickers away.
export function useModuleActive(key: string): boolean {
  const { data } = useMeBootstrap();
  const active = data?.company_modules?.active;
  return !active || active.includes(key);
}

/** Renders `on` when the module is active, else `off` (e.g. Candidates without Jobs -> talent pool). */
export default function ByModule({ module, on, off }: { module: string; on: ReactNode; off: ReactNode }) {
  return <>{useModuleActive(module) ? on : off}</>;
}
