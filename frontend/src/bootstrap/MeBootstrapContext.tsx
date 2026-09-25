import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { brandingApi, type BootstrapRead } from "../api/client";

// Part 12/14 (docs/HRMS_COMPLETE_SPEC.txt): the signed-in user's GET /api/me/bootstrap --
// permissions, nav and AI feature flags. Anything AI in the UI checks `aiFeature()` so a
// tenant that turns AI (or one AI feature) off never sees the affordance at all.

interface MeBootstrapValue {
  data: BootstrapRead | null;
  loading: boolean;
  can: (permission: string) => boolean;
  aiFeature: (feature: string) => boolean;
  reload: () => void;
}

const MeBootstrapContext = createContext<MeBootstrapValue>({
  data: null,
  loading: true,
  can: () => false,
  aiFeature: () => false,
  reload: () => undefined,
});

export function useMeBootstrap() {
  return useContext(MeBootstrapContext);
}

export function MeBootstrapProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<BootstrapRead | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    brandingApi
      .meBootstrap()
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  // Part 14 section 9 / L-V8: reading direction and the per-user reduce-motion preference
  // apply to the whole document (CSS in index.css honours .reduce-motion and the OS setting).
  useEffect(() => {
    const root = document.documentElement;
    root.dir = data?.ux?.direction ?? "ltr";
    root.classList.toggle("reduce-motion", Boolean(data?.ux?.reduce_motion));
    if (data?.locale) root.lang = data.locale;
  }, [data]);

  const permissions = new Set(data?.permissions ?? []);
  const value: MeBootstrapValue = {
    data,
    loading,
    can: (permission) => permissions.has(permission),
    aiFeature: (feature) => Boolean(data?.ai?.enabled && data.ai.features[feature]),
    reload: load,
  };
  return <MeBootstrapContext.Provider value={value}>{children}</MeBootstrapContext.Provider>;
}
