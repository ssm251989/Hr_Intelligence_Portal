import { render, screen, waitFor } from "@testing-library/react";
import { useTheme } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BootstrapProvider } from "../bootstrap/BootstrapContext";
import { createAppTheme } from "./createAppTheme";
import { AppThemeProvider } from "./ThemeModeContext";

const publicBrandingMock = vi.fn();

vi.mock("../api/client", () => ({
  brandingApi: {
    public: (...args: unknown[]) => publicBrandingMock(...args),
  },
}));

function ThemeProbe() {
  const theme = useTheme();
  return <div data-testid="primary-color">{theme.palette.primary.main}</div>;
}

describe("createAppTheme", () => {
  it("uses the generic BRAND_BLUE token when no override is passed", () => {
    const theme = createAppTheme("light");
    expect(theme.palette.primary.main).toBeTruthy();
  });

  it("uses the override color when one is passed", () => {
    const theme = createAppTheme("light", "#ff00ff");
    expect(theme.palette.primary.main).toBe("#ff00ff");
  });

  it("falls back to the generic token when the override is null", () => {
    const withOverride = createAppTheme("light", "#ff00ff");
    const withoutOverride = createAppTheme("light", null);
    expect(withoutOverride.palette.primary.main).not.toBe("#ff00ff");
    expect(withoutOverride.palette.primary.main).not.toBe(withOverride.palette.primary.main);
  });
});

describe("theme from bootstrap (integration)", () => {
  beforeEach(() => {
    publicBrandingMock.mockReset();
  });

  it("renders the real MUI theme with the tenant's own brand primary_color once bootstrap loads", async () => {
    publicBrandingMock.mockResolvedValue({
      product_name: "Test Co", logo_file_id: null, primary_color: "#123456", secondary_color: null,
      gradient_from: "#000000", gradient_to: "#123456", font_family: "sans-serif",
      support_contact: null, legal_links: [], custom_css: null,
    });

    render(
      <BootstrapProvider>
        <AppThemeProvider>
          <ThemeProbe />
        </AppThemeProvider>
      </BootstrapProvider>
    );

    await waitFor(() => expect(screen.getByTestId("primary-color").textContent).toBe("#123456"));
  });

  it("falls back to the generic brand token if the branding fetch fails", async () => {
    publicBrandingMock.mockRejectedValue(new Error("network error"));

    render(
      <BootstrapProvider>
        <AppThemeProvider>
          <ThemeProbe />
        </AppThemeProvider>
      </BootstrapProvider>
    );

    await waitFor(() => expect(publicBrandingMock).toHaveBeenCalled());
    expect(screen.getByTestId("primary-color").textContent).not.toBe("");
    expect(screen.getByTestId("primary-color").textContent).not.toBe("#123456");
  });
});
