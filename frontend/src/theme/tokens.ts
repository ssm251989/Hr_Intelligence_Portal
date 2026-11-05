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
  violet: string; // Part 18.6: a fifth accent so modules/tiles/charts can each have their own colour
  violetSoft: string;
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
    coral: "#D9462B", coralSoft: "#FDECE7",
    sun: "#F2B233", sunSoft: "#FDF4DF", sunInk: "#8A5E06",
    sky: "#2F6FDE", skySoft: "#E6EEFC",
    ok: "#1F8A4C", okSoft: "#E3F4EA",
    violet: "#7048D8", violetSoft: "#EFE9FD",
    ground: "#F2F6F9", surface: "#FFFFFF", surface2: "#F7FAFC",
    ink: "#15211D", muted: "#5B6A65", line: "#E2E8E5",
    shadow: "0 1px 2px rgba(21,33,29,.05), 0 6px 20px rgba(21,33,29,.06)",
    shadowHover: "0 2px 4px rgba(21,33,29,.06), 0 12px 28px rgba(21,33,29,.10)",
  },
  // Part 18.6: deep navy/teal ground with bright accents (the old dark mode looked dull);
  // every text/background pair is >= 4.5:1 (scripts/contrast-check.mjs).
  dark: {
    brand: "#2DD4BF", brandInk: "#03201C", brandSoft: "#0E3B3F",
    coral: "#FF8474", coralSoft: "#3E1E27",
    sun: "#FFCB57", sunSoft: "#3A2F17", sunInk: "#FFD27A",
    sky: "#6AADFF", skySoft: "#15294B",
    ok: "#4ADE80", okSoft: "#10352A",
    violet: "#B39DFF", violetSoft: "#2A2150",
    ground: "#0A1324", surface: "#111E36", surface2: "#172743",
    ink: "#EDF3FC", muted: "#A9B8D0", line: "#24365A",
    shadow: "0 1px 2px rgba(0,0,0,.45), 0 8px 24px rgba(2,8,23,.55)",
    shadowHover: "0 2px 6px rgba(0,0,0,.5), 0 14px 34px rgba(2,8,23,.65), 0 0 0 1px rgba(45,212,191,.18)",
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
