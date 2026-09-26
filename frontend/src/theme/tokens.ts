// Part 15 A -- the platform's default "Fresh" theme (docs/ui/reference_mockup.html).
// These are only DEFAULTS: every token can be overridden per company from brand_themes
// (GET /api/me/bootstrap -> branding.primary_color / branding.palette). Nothing here is
// any one client's colour.

export type ThemeMode = "light" | "dark";

export interface FreshTokens {
  brand: string;
  brandInk: string; // text on a brand-coloured surface
  brandSoft: string;
  coral: string;
  coralSoft: string;
  sun: string;
  sunSoft: string;
  sunInk: string; // readable text on sunSoft (sun itself is too light for text in light mode)
  sky: string;
  skySoft: string;
  ok: string;
  okSoft: string;
  ground: string; // page background
  surface: string; // cards
  surface2: string; // insets inside cards (list rows, evidence lines)
  ink: string;
  muted: string;
  line: string;
  shadow: string;
  shadowHover: string;
}

export const FRESH: Record<ThemeMode, FreshTokens> = {
  light: {
    brand: "#0E7C66", brandInk: "#FFFFFF", brandSoft: "#E2F3EE",
    coral: "#F26B4B", coralSoft: "#FDECE7",
    sun: "#F2B233", sunSoft: "#FDF4DF", sunInk: "#9A6A08",
    sky: "#2F6FDE", skySoft: "#E6EEFC",
    ok: "#1F8A4C", okSoft: "#E3F4EA",
    ground: "#F4F6F5", surface: "#FFFFFF", surface2: "#F9FBFA",
    ink: "#15211D", muted: "#5B6A65", line: "#E2E8E5",
    shadow: "0 1px 2px rgba(21,33,29,.05), 0 6px 20px rgba(21,33,29,.06)",
    shadowHover: "0 2px 4px rgba(21,33,29,.06), 0 12px 28px rgba(21,33,29,.10)",
  },
  dark: {
    brand: "#3FBF9F", brandInk: "#08110E", brandSoft: "#173A31",
    coral: "#FF8A6B", coralSoft: "#3A221C",
    sun: "#F5C35A", sunSoft: "#3A3020", sunInk: "#F5C35A",
    sky: "#6C9BF0", skySoft: "#1C2A45",
    ok: "#5BCB8A", okSoft: "#173424",
    ground: "#0E1412", surface: "#16201D", surface2: "#1B2622",
    ink: "#E6EEEB", muted: "#9AAAA4", line: "#26332F",
    shadow: "0 1px 2px rgba(0,0,0,.4), 0 6px 20px rgba(0,0,0,.3)",
    shadowHover: "0 2px 4px rgba(0,0,0,.45), 0 12px 28px rgba(0,0,0,.4)",
  },
};

// Shape + rhythm (Part 15 A): cards 18, buttons 11, chips pill, 8px spacing grid.
export const RADIUS = { card: 18, button: 11, input: 11, inset: 12, chip: 999 };
export const SPACING_UNIT = 8;

export const FONT_STACK = '"Plus Jakarta Sans", system-ui, -apple-system, "Segoe UI", sans-serif';

// ---- Legacy exports (kept so existing charts/cards keep compiling; now Fresh values) ----
export const BRAND_BLUE = { light: FRESH.light.brand, dark: FRESH.dark.brand };
export const SURFACE = { light: FRESH.light.surface, dark: FRESH.dark.surface };
export const PAGE_PLANE = { light: FRESH.light.ground, dark: FRESH.dark.ground };
export const TEXT_PRIMARY = { light: FRESH.light.ink, dark: FRESH.dark.ink };
export const TEXT_SECONDARY = { light: FRESH.light.muted, dark: FRESH.dark.muted };
export const HAIRLINE_BORDER = { light: FRESH.light.line, dark: FRESH.dark.line };
export const CARD_SHADOW = { light: FRESH.light.shadow, dark: FRESH.dark.shadow };
export const CARD_SHADOW_HOVER = { light: FRESH.light.shadowHover, dark: FRESH.dark.shadowHover };
