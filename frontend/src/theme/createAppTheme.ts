import { alpha, createTheme, darken, getContrastRatio, lighten, type Theme } from "@mui/material/styles";

import type { BrandingRead } from "../api/client";
import { FONT_STACK, FRESH, RADIUS, SPACING_UNIT, type FreshTokens, type ThemeMode } from "./tokens";

export type { ThemeMode } from "./tokens";

declare module "@mui/material/styles" {
  interface Palette {
    fresh: FreshTokens;
    chart: string[];
  }
  interface PaletteOptions {
    fresh?: FreshTokens;
    chart?: string[];
  }
}

const HEX = /^#[0-9a-fA-F]{6}$/;

/** Default "Fresh" tokens + the company's own overrides from brand_themes (Part 15 A). */
export function resolveTokens(mode: ThemeMode, branding?: Pick<BrandingRead, "primary_color" | "palette"> | null): FreshTokens {
  const base = FRESH[mode];
  const override = { ...(branding?.palette?.[mode] ?? {}) } as Partial<FreshTokens>;
  const primary = branding?.primary_color;
  // A company that only picked a primary colour (the common case) gets it in light mode and
  // a lifted version in dark mode, so it stays readable on the dark surface.
  if (!override.brand && primary && HEX.test(primary) && primary.toUpperCase() !== FRESH.light.brand) {
    override.brand = mode === "light" ? primary : lighten(primary, 0.3);
  }
  const t: FreshTokens = { ...base, ...override };
  if (override.brand) {
    if (!override.brandSoft) t.brandSoft = mode === "light" ? lighten(t.brand, 0.88) : darken(t.brand, 0.7);
    t.brandInk = getContrastRatio(t.brand, "#FFFFFF") >= 4.5 ? "#FFFFFF" : "#08110E";
  }
  return t;
}

/** Chart series derived from the theme, each nudged until it has >= 3:1 contrast on cards. */
export function chartColors(t: FreshTokens, mode: ThemeMode): string[] {
  return [t.brand, t.sky, t.sun, t.coral, t.ok, t.muted].map((c) => {
    let colour = c;
    for (let i = 0; i < 8 && getContrastRatio(colour, t.surface) < 3; i += 1) {
      colour = mode === "light" ? darken(colour, 0.1) : lighten(colour, 0.1);
    }
    return colour;
  });
}

type BrandingInput = Pick<BrandingRead, "primary_color"> & Partial<Pick<BrandingRead, "palette" | "font_family">>;

/** `branding` may also be a bare primary colour (older call sites / tests). */
export function createAppTheme(mode: ThemeMode, brandingOrPrimary?: BrandingInput | string | null): Theme {
  const branding: BrandingInput | null =
    typeof brandingOrPrimary === "string" ? { primary_color: brandingOrPrimary } : brandingOrPrimary ?? null;
  const t = resolveTokens(mode, branding);
  const focusRing = { outline: `2px solid ${t.brand}`, outlineOffset: 2 };
  const tabular = { fontVariantNumeric: "tabular-nums" as const };

  return createTheme({
    spacing: SPACING_UNIT,
    palette: {
      mode,
      primary: { main: t.brand, contrastText: t.brandInk },
      secondary: { main: t.coral },
      error: { main: t.coral },
      warning: { main: t.sun, contrastText: "#15211D" },
      info: { main: t.sky },
      success: { main: t.ok },
      background: { default: t.ground, paper: t.surface },
      text: { primary: t.ink, secondary: t.muted },
      divider: t.line,
      action: { selected: t.brandSoft, hover: alpha(t.brand, mode === "light" ? 0.06 : 0.12) },
      fresh: t,
      chart: chartColors(t, mode),
    },
    shape: { borderRadius: RADIUS.button },
    typography: {
      fontFamily: branding?.font_family && !/apple-system, Segoe UI, Roboto/.test(branding.font_family) ? `${branding.font_family}, ${FONT_STACK}` : FONT_STACK,
      fontSize: 14,
      h1: { fontSize: 26, fontWeight: 800, lineHeight: 1.2, textWrap: "balance" },
      h2: { fontSize: 22, fontWeight: 800, lineHeight: 1.25 },
      h3: { fontSize: 20, fontWeight: 800, lineHeight: 1.25 },
      h4: { fontSize: 26, fontWeight: 800, lineHeight: 1.2, ...tabular },
      h5: { fontSize: 18, fontWeight: 700, lineHeight: 1.3 },
      h6: { fontSize: 16, fontWeight: 700, lineHeight: 1.35 },
      subtitle1: { fontWeight: 700 },
      subtitle2: { fontWeight: 700, color: t.muted },
      body2: { lineHeight: 1.5 },
      caption: { color: t.muted },
      overline: { fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", color: t.muted },
      button: { textTransform: "none", fontWeight: 700 },
    },
    transitions: { duration: { shortest: 150, shorter: 180, short: 220 } },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: { backgroundColor: t.ground, color: t.ink },
          ".num, .MuiTableCell-root": tabular,
          "::selection": { backgroundColor: t.brandSoft },
        },
      },
      MuiPaper: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: { backgroundImage: "none" },
          rounded: { borderRadius: RADIUS.card },
          outlined: { border: "none", boxShadow: t.shadow },
          elevation1: { boxShadow: t.shadow },
        },
      },
      MuiCard: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          // Every existing card was written as variant="outlined"; redefining that variant
          // gives the whole app the soft two-layer shadow without touching call sites.
          root: { borderRadius: RADIUS.card, border: "none", boxShadow: t.shadow, backgroundColor: t.surface, transition: "box-shadow 220ms ease" },
        },
      },
      MuiCardContent: { styleOverrides: { root: { padding: 18, "&:last-child": { paddingBottom: 18 } } } },
      MuiCardHeader: { styleOverrides: { title: { fontSize: 16, fontWeight: 700 }, subheader: { fontSize: 12, color: t.muted } } },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: { borderRadius: RADIUS.button, fontWeight: 700, padding: "8px 16px", "&.Mui-focusVisible": focusRing },
          sizeSmall: { padding: "5px 12px", borderRadius: 9 },
          sizeLarge: { padding: "11px 20px" },
          contained: { "&:hover": { boxShadow: t.shadow } },
          outlined: { borderColor: t.line, backgroundColor: t.surface, color: t.ink, "&:hover": { borderColor: t.brand, backgroundColor: t.surface2 } },
          text: { "&:hover": { backgroundColor: t.brandSoft } },
        },
      },
      MuiIconButton: {
        styleOverrides: { root: { borderRadius: RADIUS.button, "&.Mui-focusVisible": focusRing } },
      },
      MuiChip: {
        styleOverrides: {
          // Soft tint + strong text per colour (mockup .chip); outlined keeps a coloured border.
          root: ({ ownerState }) => {
            const tones: Record<string, [string, string, string]> = {
              default: [t.surface2, t.ink, t.line], primary: [t.brandSoft, t.brand, t.brand], secondary: [t.coralSoft, t.coral, t.coral],
              error: [t.coralSoft, t.coral, t.coral], warning: [t.sunSoft, t.sunInk, t.sun], info: [t.skySoft, t.sky, t.sky], success: [t.okSoft, t.ok, t.ok],
            };
            const [bg, fg, border] = tones[ownerState.color ?? "default"] ?? tones.default;
            return {
              borderRadius: RADIUS.chip, fontWeight: 700, fontSize: 12, height: 26,
              ...(ownerState.variant === "outlined"
                ? { backgroundColor: "transparent", color: fg, borderColor: ownerState.color === "default" ? t.line : border }
                : { backgroundColor: bg, color: fg }),
              "& .MuiChip-icon": { color: "inherit" },
            };
          },
          sizeSmall: { height: 22, fontSize: 12 },
          label: { paddingLeft: 9, paddingRight: 9 },
          clickable: { "&:hover": { filter: "brightness(0.97)" } },
        },
      },
      MuiTableContainer: { styleOverrides: { root: { borderRadius: RADIUS.inset } } },
      MuiTable: { styleOverrides: { root: { borderCollapse: "separate", borderSpacing: 0 } } },
      MuiTableHead: {
        styleOverrides: {
          root: {
            "& .MuiTableCell-head": {
              backgroundColor: t.surface2, color: t.muted, fontSize: 12, fontWeight: 700,
              letterSpacing: "0.04em", textTransform: "uppercase", borderBottom: `1px solid ${t.line}`,
            },
          },
        },
      },
      MuiTableCell: { styleOverrides: { root: { borderBottom: `1px solid ${t.line}`, padding: "12px 14px" }, sizeSmall: { padding: "8px 12px" } } },
      MuiTableRow: { styleOverrides: { root: { "&.MuiTableRow-hover:hover": { backgroundColor: t.surface2 }, "&:last-child td": { borderBottom: 0 } } } },
      MuiTablePagination: { styleOverrides: { root: { borderTop: `1px solid ${t.line}` } } },
      MuiTabs: {
        styleOverrides: {
          root: { minHeight: 42, backgroundColor: t.surface, border: `1px solid ${t.line}`, borderRadius: 12, padding: 4, width: "fit-content", maxWidth: "100%" },
          indicator: { display: "none" },
          flexContainer: { gap: 4 },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            minHeight: 34, padding: "7px 14px", borderRadius: 9, fontWeight: 600, color: t.muted, textTransform: "none",
            "&.Mui-selected": { backgroundColor: t.brand, color: t.brandInk },
            "&.Mui-focusVisible": focusRing,
          },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: { borderRadius: RADIUS.card + 4, boxShadow: t.shadowHover, backgroundColor: t.surface },
        },
      },
      MuiDialogTitle: { styleOverrides: { root: { fontSize: 18, fontWeight: 800, padding: "20px 24px 8px" } } },
      MuiDialogContent: { styleOverrides: { root: { padding: "8px 24px" } } },
      MuiDialogActions: { styleOverrides: { root: { padding: "12px 24px 20px", gap: 8 } } },
      MuiBackdrop: { styleOverrides: { root: { "&:not(.MuiBackdrop-invisible)": { backgroundColor: alpha("#0E1412", 0.45), backdropFilter: "blur(2px)" } } } },
      MuiDrawer: {
        styleOverrides: {
          paper: { backgroundImage: "none", backgroundColor: t.surface, borderRight: "none", borderLeft: "none" },
          paperAnchorRight: { borderTopLeftRadius: RADIUS.card, borderBottomLeftRadius: RADIUS.card },
          paperAnchorLeft: { borderTopRightRadius: RADIUS.card, borderBottomRightRadius: RADIUS.card },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: RADIUS.input, backgroundColor: t.surface,
            "& .MuiOutlinedInput-notchedOutline": { borderColor: t.line },
            "&:hover .MuiOutlinedInput-notchedOutline": { borderColor: t.muted },
            "&.Mui-focused .MuiOutlinedInput-notchedOutline": { borderColor: t.brand, borderWidth: 2 },
          },
        },
      },
      MuiTextField: { defaultProps: { size: "small" } },
      MuiFormControl: { defaultProps: { size: "small" } },
      MuiInputLabel: { styleOverrides: { root: { fontWeight: 500 } } },
      MuiFormHelperText: { styleOverrides: { root: { marginLeft: 2 } } },
      MuiSelect: { styleOverrides: { select: { borderRadius: RADIUS.input } } },
      MuiMenu: { styleOverrides: { paper: { borderRadius: 14, boxShadow: t.shadowHover, border: `1px solid ${t.line}` } } },
      MuiPopover: { styleOverrides: { paper: { borderRadius: 16, boxShadow: t.shadowHover, border: `1px solid ${t.line}` } } },
      MuiMenuItem: { styleOverrides: { root: { borderRadius: 8, margin: "2px 6px", "&.Mui-selected": { backgroundColor: t.brandSoft } } } },
      MuiTooltip: {
        defaultProps: { arrow: true },
        styleOverrides: {
          tooltip: { backgroundColor: t.ink, color: t.surface, fontSize: 12, fontWeight: 500, borderRadius: 8, padding: "6px 10px" },
          arrow: { color: t.ink },
        },
      },
      MuiAppBar: {
        defaultProps: { elevation: 0, color: "transparent" },
        styleOverrides: { root: { backgroundImage: "none", boxShadow: "none" } },
      },
      MuiSnackbarContent: {
        styleOverrides: { root: { borderRadius: 14, backgroundColor: t.ink, color: t.surface, fontWeight: 600, boxShadow: t.shadowHover } },
      },
      MuiAlert: {
        styleOverrides: {
          root: { borderRadius: 14, alignItems: "center" },
          standardSuccess: { backgroundColor: t.okSoft, color: t.ink },
          standardInfo: { backgroundColor: t.skySoft, color: t.ink },
          standardWarning: { backgroundColor: t.sunSoft, color: t.ink },
          standardError: { backgroundColor: t.coralSoft, color: t.ink },
          filled: { borderRadius: 14 },
        },
      },
      MuiStepper: { styleOverrides: { root: { padding: 0 } } },
      MuiStepIcon: {
        styleOverrides: {
          root: { color: t.line, "&.Mui-active": { color: t.brand }, "&.Mui-completed": { color: t.brand } },
          text: { fontWeight: 700 },
        },
      },
      MuiStepLabel: { styleOverrides: { label: { fontWeight: 600, "&.Mui-active": { fontWeight: 700 } } } },
      MuiStepConnector: { styleOverrides: { line: { borderColor: t.line, borderTopWidth: 2 } } },
      MuiLinearProgress: {
        styleOverrides: {
          root: { height: 10, borderRadius: 5, backgroundColor: t.line },
          bar: { borderRadius: 5, backgroundImage: `linear-gradient(90deg, ${t.brand}, ${t.sun})` },
        },
      },
      MuiAvatar: { styleOverrides: { rounded: { borderRadius: 12 } } },
      MuiBadge: { styleOverrides: { badge: { fontWeight: 700 } } },
      MuiListItemButton: {
        styleOverrides: { root: { borderRadius: 10, "&.Mui-selected": { backgroundColor: t.brandSoft, color: t.brand } } },
      },
      MuiDivider: { styleOverrides: { root: { borderColor: t.line } } },
      MuiAccordion: {
        defaultProps: { disableGutters: true, elevation: 0 },
        styleOverrides: { root: { borderRadius: RADIUS.inset, boxShadow: t.shadow, "&:before": { display: "none" } } },
      },
      MuiSwitch: {
        styleOverrides: { switchBase: { "&.Mui-checked + .MuiSwitch-track": { opacity: 1, backgroundColor: t.brand } } },
      },
      MuiSkeleton: { styleOverrides: { root: { borderRadius: 8, backgroundColor: t.line } } },
    },
  });
}

/** Mirrors the tokens onto :root as CSS variables (var(--brand), ...) for plain-CSS widgets
 * such as SVG charts and maps, matching the reference mockup's variable names. */
export function cssVariables(t: FreshTokens): Record<string, string> {
  return {
    "--brand": t.brand, "--brand-ink": t.brandInk, "--brand-soft": t.brandSoft,
    "--coral": t.coral, "--coral-soft": t.coralSoft, "--sun": t.sun, "--sun-soft": t.sunSoft, "--sun-ink": t.sunInk,
    "--sky": t.sky, "--sky-soft": t.skySoft, "--ok": t.ok, "--ok-soft": t.okSoft,
    "--ground": t.ground, "--surface": t.surface, "--surface-2": t.surface2,
    "--ink": t.ink, "--muted": t.muted, "--line": t.line, "--shadow": t.shadow,
  };
}
