// Color tokens shared by the app theme (createAppTheme.ts) and, already, every chart in
// this app (LabeledDonutChart, JobsLocationMap, StatCard) -- reusing the same validated
// light/dark pairs here means the new theme's brand color and surfaces are consistent
// with what every chart already renders, not a second, uncoordinated palette.
export const BRAND_BLUE = { light: "#2a78d6", dark: "#3987e5" };

export const SURFACE = { light: "#fcfcfb", dark: "#1a1a19" };
export const PAGE_PLANE = { light: "#f9f9f7", dark: "#0d0d0d" };
export const TEXT_PRIMARY = { light: "#0b0b0b", dark: "#ffffff" };
export const TEXT_SECONDARY = { light: "#52514e", dark: "#c3c2b7" };
export const HAIRLINE_BORDER = { light: "rgba(11,11,11,0.08)", dark: "rgba(255,255,255,0.10)" };

// Soft, layered card shadows -- default and a slightly stronger one for hover/elevation.
// Dark mode shadows lean on opacity+spread rather than color (a black shadow barely reads
// against an already-dark page), so cards stay legible via the hairline border above
// wherever the shadow alone doesn't carry enough contrast.
export const CARD_SHADOW = {
  light: "0 1px 2px rgba(11,11,11,0.04), 0 2px 8px rgba(11,11,11,0.06)",
  dark: "0 1px 2px rgba(0,0,0,0.5), 0 2px 8px rgba(0,0,0,0.35)",
};
export const CARD_SHADOW_HOVER = {
  light: "0 6px 20px rgba(11,11,11,0.10), 0 2px 6px rgba(11,11,11,0.06)",
  dark: "0 6px 24px rgba(0,0,0,0.6), 0 2px 8px rgba(0,0,0,0.4)",
};
