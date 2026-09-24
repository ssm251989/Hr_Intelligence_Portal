import { createTheme, type Theme } from "@mui/material/styles";

import {
  BRAND_BLUE,
  CARD_SHADOW,
  CARD_SHADOW_HOVER,
  HAIRLINE_BORDER,
  PAGE_PLANE,
  SURFACE,
  TEXT_PRIMARY,
  TEXT_SECONDARY,
} from "./tokens";

export type ThemeMode = "light" | "dark";

export function createAppTheme(mode: ThemeMode, primaryColorOverride?: string | null): Theme {
  // Part 6 section 5 -- "MUI theme created at runtime" from GET /api/me/bootstrap's own
  // branding.primary_color (a tenant's real brand_theme row), falling back to this
  // design system's own generic BRAND_BLUE token (see tokens.ts's own comment on why
  // that palette is excluded from the hardcode guard -- it's the platform's neutral
  // default, not client data) until bootstrap has actually loaded.
  const brand = primaryColorOverride || BRAND_BLUE[mode];
  const surface = SURFACE[mode];
  const pagePlane = PAGE_PLANE[mode];
  const border = HAIRLINE_BORDER[mode];
  const shadow = CARD_SHADOW[mode];
  const shadowHover = CARD_SHADOW_HOVER[mode];

  return createTheme({
    palette: {
      mode,
      primary: { main: brand },
      background: { default: pagePlane, paper: surface },
      text: { primary: TEXT_PRIMARY[mode], secondary: TEXT_SECONDARY[mode] },
    },
    shape: { borderRadius: 14 },
    typography: {
      fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
    },
    transitions: {
      duration: { shortest: 150, shorter: 180, short: 220 },
    },
    components: {
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 14,
            // This app's cards were all written as variant="outlined" (a flat border, by
            // MUI's own definition of that variant) -- redefining what "outlined" looks
            // like here swaps every one of them to soft-shadow elevation without editing
            // a single card usage across the app.
            border: "none",
            boxShadow: shadow,
            transition: "box-shadow 220ms ease, transform 220ms ease",
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: { backgroundImage: "none" },
          outlined: { border: "none", boxShadow: shadow },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            textTransform: "none",
            transition: "box-shadow 180ms ease, transform 180ms ease, background-color 180ms ease",
          },
          contained: {
            boxShadow: shadow,
            "&:hover": {
              boxShadow: shadowHover,
              transform: "translateY(-1px)",
            },
          },
          outlined: {
            "&:hover": {
              transform: "translateY(-1px)",
            },
          },
        },
      },
      MuiIconButton: {
        styleOverrides: {
          root: {
            transition: "background-color 180ms ease, transform 180ms ease",
          },
        },
      },
      MuiDrawer: {
        styleOverrides: {
          paper: {
            borderRight: `1px solid ${border}`,
            backgroundImage: "none",
          },
        },
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            backgroundImage: "none",
            boxShadow: shadow,
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { borderRadius: 8 },
        },
      },
    },
  });
}
