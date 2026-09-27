import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { apiUrl, brandingApi, type BrandingRead } from "../api/client";

// Part 6 section 5 -- replaces the old bootstrap/defaults.ts staging file (Part 1's own
// "one file's exports, not every component that referenced a literal by hand" plan):
// every real call site now reads branding from HERE, fetched at runtime from GET
// /api/v1/public/branding (no-auth, so it works on the login page too, before anyone's
// authenticated) instead of a build-time constant. `logoMark` is derived client-side from
// `productName`'s own initials -- there's no separate "short mark" field in the backend's
// branding response (no real logo file storage exists yet either), so this is a
// reasonable rendering fallback, not a second source of truth to keep in sync.
const FALLBACK_PRODUCT_NAME = "HR Automation";

function deriveLogoMark(productName: string): string {
  const words = productName.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "";
  if (words.length === 1) return words[0].slice(0, 3).toUpperCase();
  return words.slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

interface BootstrapContextValue {
  branding: BrandingRead | null;
  productName: string;
  logoMark: string;
  logoUrl: string | null; // Part 17.11: the company logo, when one is uploaded
  reload: () => void; // re-read branding after a settings save (name / logo / colours)
  loading: boolean;
}

const BootstrapContext = createContext<BootstrapContextValue>({
  branding: null,
  productName: FALLBACK_PRODUCT_NAME,
  logoMark: deriveLogoMark(FALLBACK_PRODUCT_NAME),
  logoUrl: null,
  reload: () => undefined,
  loading: true,
});

export function useBootstrap() {
  return useContext(BootstrapContext);
}

export function BootstrapProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState<BrandingRead | null>(null);
  const [loading, setLoading] = useState(true);

  const [tick, setTick] = useState(0);
  useEffect(() => {
    brandingApi
      .public()
      .then(setBranding)
      .catch(() => setBranding(null)) // falls back to the generic defaults below -- never blocks the app from rendering
      .finally(() => setLoading(false));
  }, [tick]);

  const productName = branding?.product_name || FALLBACK_PRODUCT_NAME;

  return (
    <BootstrapContext.Provider value={{ branding, productName, logoMark: deriveLogoMark(productName), logoUrl: apiUrl(branding?.logo_url), reload: () => setTick((x) => x + 1), loading }}>
      {children}
    </BootstrapContext.Provider>
  );
}
