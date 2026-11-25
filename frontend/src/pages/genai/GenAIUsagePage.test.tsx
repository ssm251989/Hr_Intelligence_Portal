// Part 33.4: AI Intelligence > Usage - "Cost per hire" / "Cost per exit" card and "Export cost report (Excel)".
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createAppTheme } from "../../theme/createAppTheme";
import GenAIUsagePage from "./GenAIUsagePage";

const getMock = vi.fn();
const fetchBlobMock = vi.fn();

vi.mock("../../api/client", () => ({
  http: {
    get: (...args: unknown[]) => getMock(...args),
    fetchBlob: (...args: unknown[]) => fetchBlobMock(...args),
  },
  apiUrl: (p: string) => p,
  ApiError: class extends Error {},
}));

const ROW = { key: "k", label: "k", requests: 0, errors: 0, tokens_in: 0, tokens_out: 0, tokens: 0, cost: 0 };
const USAGE = { currency: "INR", total: ROW, by_module: [], by_feature: [], by_user: [], by_model: [], by_day: [], top_candidates: [],
  avg_cost_per_candidate: 0, priced: true, limits: [] };
const UNITS = {
  currency: "INR", total_cost: 10, unattributed_cost: 0,
  per_resume: { resumes: 3, ai_cost: 1, avg: 0.33 }, per_job: { jobs: 0, avg: null, rows: [] }, per_hire: { hires: 1, avg: 10 },
  hire: { median: 0.83, p90: 1.5, currency: "INR", samples: 2, estimate: true },
  exit: { median: 0.33, p90: 0.62, currency: "INR", samples: 25, estimate: false },
};

function renderPage() {
  return render(
    <ThemeProvider theme={createAppTheme("light")}>
      <MemoryRouter><GenAIUsagePage /></MemoryRouter>
    </ThemeProvider>,
  );
}

describe("GenAIUsagePage - Part 33.4", () => {
  beforeEach(() => {
    getMock.mockReset();
    fetchBlobMock.mockReset();
    getMock.mockImplementation((path: string) => Promise.resolve(path.includes("unit-costs") ? UNITS : USAGE));
  });

  it("shows cost per hire and per exit with p90, samples and the estimate mark", async () => {
    renderPage();
    const card = await screen.findByTestId("journey-card");
    expect(within(card).getByText("INR 0.83")).toBeInTheDocument();
    expect(within(card).getByText("INR 0.33")).toBeInTheDocument();
    expect(within(card).getByText(/2 in this period · p90 INR 1.5/)).toBeInTheDocument();
    expect(within(card).getByText(/25 in this period · p90 INR 0.62/)).toBeInTheDocument();
    // only the hire number rests on fewer than 20 samples
    expect(within(card).getAllByText("Estimate: fewer than 20 samples")).toHaveLength(1);
  });

  it("hides the card when the server has no hire / exit numbers (older API)", async () => {
    getMock.mockImplementation((path: string) => Promise.resolve(path.includes("unit-costs") ? { ...UNITS, hire: undefined, exit: undefined } : USAGE));
    renderPage();
    await screen.findByText("Unit costs (AI only)");
    expect(screen.queryByTestId("journey-card")).not.toBeInTheDocument();
  });

  it("exports the cost report for the chosen dates", async () => {
    fetchBlobMock.mockResolvedValue(new Blob(["x"]));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Export cost report (Excel)" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("From"), { target: { value: "2026-11-01" } });
    fireEvent.change(within(dialog).getByLabelText("To"), { target: { value: "2026-11-24" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Download" }));
    await waitFor(() => expect(fetchBlobMock).toHaveBeenCalledWith("/api/v1/ui/genai/cost-report/export?since=2026-11-01&until=2026-11-24"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("defaults to the period shown and blocks an end date before the start", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Export cost report (Excel)" }));
    const dialog = await screen.findByRole("dialog");
    const from = (within(dialog).getByLabelText("From") as HTMLInputElement).value;
    const to = (within(dialog).getByLabelText("To") as HTMLInputElement).value;
    expect((Date.parse(to) - Date.parse(from)) / 86_400_000).toBe(30); // the "month" tab
    fireEvent.change(within(dialog).getByLabelText("From"), { target: { value: "2026-12-01" } });
    fireEvent.change(within(dialog).getByLabelText("To"), { target: { value: "2026-11-01" } });
    expect(within(dialog).getByText("The end date is before the start date.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Download" })).toBeDisabled();
    expect(fetchBlobMock).not.toHaveBeenCalled();
  });

  it("says so when the report can't be made", async () => {
    fetchBlobMock.mockResolvedValue(null);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Export cost report (Excel)" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Download" }));
    expect(await within(dialog).findByText("Couldn't make the report. Try again.")).toBeInTheDocument();
  });
});
