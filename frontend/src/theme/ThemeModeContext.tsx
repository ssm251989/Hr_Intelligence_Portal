import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import CssBaseline from "@mui/material/CssBaseline";
import GlobalStyles from "@mui/material/GlobalStyles";
import { ThemeProvider } from "@mui/material/styles";

import { useBootstrap } from "../bootstrap/BootstrapContext";
import { createAppTheme, cssVariables, type ThemeMode } from "./createAppTheme";

const STORAGE_KEY = "hr-automation-theme-mode";

function readStoredMode(): ThemeMode {
  if (typeof window === "undefined") return "light";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // storage blocked (private window) -- fall through to the OS preference
  }
  // No explicit choice saved yet -- respect the OS/browser preference on first visit.
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const ThemeModeContext = createContext<{ mode: ThemeMode; toggleMode: () => void }>({
  mode: "light",
  toggleMode: () => {},
});

export function useThemeMode() {
  return useContext(ThemeModeContext);
}

export function AppThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(readStoredMode);
  const { branding } = useBootstrap();

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // not persisted; the toggle still works for this visit
    }
    // Same switch the reference mockup uses, so plain-CSS widgets can follow the mode too.
    document.documentElement.dataset.theme = mode;
    document.documentElement.style.colorScheme = mode;
  }, [mode]);

  const toggleMode = () => setMode((prev) => (prev === "light" ? "dark" : "light"));
  const theme = useMemo(() => createAppTheme(mode, branding), [mode, branding]);

  return (
    <ThemeModeContext.Provider value={{ mode, toggleMode }}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <GlobalStyles styles={{ ":root": cssVariables(theme.palette.fresh) }} />
        {children}
      </ThemeProvider>
    </ThemeModeContext.Provider>
  );
}
