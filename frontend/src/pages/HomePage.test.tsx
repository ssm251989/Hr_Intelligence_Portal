import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// H1 (Part 27): Home called GET /me/home ~12 times a second -- `modules` was a new array on every
// render, so the load callback (and its effect) changed every render.
const mine = vi.fn();

vi.mock("../api/homeApi", () => ({
  homeApi: { mine: (...a: unknown[]) => mine(...a), saveLayout: vi.fn(), resetLayout: vi.fn(), saveDefault: vi.fn() },
}));
vi.mock("../bootstrap/MeBootstrapContext", () => ({
  // a NEW object (and new arrays) on every call, as a context re-render produces
  useMeBootstrap: () => ({ can: () => true, data: { modules: ["candidates"], company_modules: { active: ["jobs"] } } }),
}));
vi.mock("../components/home/HomeWidgets", () => {
  const W = () => null;
  return { AlertsWidget: W, AssetsWidget: W, FeedbackWidget: W, GoalsWidget: W, HiringFlowWidget: W, LettersWidget: W, OfficesWidget: W,
    StatsWidget: W, TeamWidget: W, TicketsWidget: W, TodoWidget: W };
});
vi.mock("../components/AdminHomeChecklist", () => ({ default: () => null }));
vi.mock("../ui-kit", () => ({ Emoji: () => null, HomeGreeting: () => null, PageTour: () => null }));

import HomePage from "./HomePage";

describe("HomePage", () => {
  it("loads the home once per mount, not in a loop", async () => {
    mine.mockResolvedValue({ kind: "employee", own_kind: "employee", layout: null, layout_source: "built_in", can_set_defaults: false });
    render(<MemoryRouter><HomePage /></MemoryRouter>);
    await waitFor(() => expect(mine).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 300));
    expect(mine).toHaveBeenCalledTimes(1);
  });
});
