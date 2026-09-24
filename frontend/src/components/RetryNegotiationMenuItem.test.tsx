import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CandidateApplicationRow } from "../api/types";
import RetryNegotiationMenuItem, { isRetryNegotiationEligible } from "./RetryNegotiationMenuItem";

const retryNegotiationMock = vi.fn();

vi.mock("../api/client", () => ({
  interviewSchedulingApi: {
    retryNegotiation: (...args: unknown[]) => retryNegotiationMock(...args),
  },
  extractErrorMessage: (_err: unknown, fallback: string) => fallback,
  hasErrorCode: (err: unknown, code: string) =>
    Boolean(err && typeof err === "object" && "code" in err && (err as { code: unknown }).code === code),
}));

// This component is the ONE shared implementation Shortlisting List's row action and
// Screening List's row action both render (see ShortlistingListPage.tsx/ScreeningListPage.tsx
// ShortlistingActionsMenu/ScreeningActionsMenu) -- testing it here is testing both pages'
// "Retry Scheduling" behavior at once, so it can never drift between them.
function makeRow(overrides: Partial<CandidateApplicationRow> = {}): CandidateApplicationRow {
  return {
    application_id: "app-1",
    candidate_id: "cand-1",
    candidate_name: "Jane Doe",
    job_role_id: "job-1",
    job_title: "Backend Engineer",
    status: "hr_selected",
    source: "manual",
    applied_on: "2026-01-01",
    ...overrides,
  };
}

describe("isRetryNegotiationEligible", () => {
  it("is eligible only for a Shortlisted (hr_selected) row", () => {
    expect(isRetryNegotiationEligible(makeRow({ status: "hr_selected" }))).toBe(true);
    expect(isRetryNegotiationEligible(makeRow({ status: "screened" }))).toBe(false);
    expect(isRetryNegotiationEligible(makeRow({ status: "interview_scheduled" }))).toBe(false);
    expect(isRetryNegotiationEligible(makeRow({ status: "hr_rejected" }))).toBe(false);
  });
});

describe("RetryNegotiationMenuItem", () => {
  beforeEach(() => {
    retryNegotiationMock.mockReset();
  });

  it("calls the API with this row's own application id and reports success via onDone", async () => {
    retryNegotiationMock.mockResolvedValue({ outcome: "started", invalidated_stale_tokens: 0, reason: null });
    const onClose = vi.fn();
    const onDone = vi.fn();
    const onError = vi.fn();

    render(<RetryNegotiationMenuItem row={makeRow({ application_id: "app-42" })} onClose={onClose} onDone={onDone} onError={onError} />);
    fireEvent.click(screen.getByText("Retry Scheduling"));

    expect(onClose).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(retryNegotiationMock).toHaveBeenCalledWith("app-42");
    expect(onError).not.toHaveBeenCalled();
  });

  it("surfaces the server-side reason on a skip instead of generic fallback copy", async () => {
    retryNegotiationMock.mockResolvedValue({
      outcome: null, invalidated_stale_tokens: 0,
      reason: "Application is flagged for manual scheduling and needs a human to pick it up",
    });
    const onError = vi.fn();

    render(<RetryNegotiationMenuItem row={makeRow({ candidate_name: "Kishore Reddy" })} onClose={vi.fn()} onDone={vi.fn()} onError={onError} />);
    fireEvent.click(screen.getByText("Retry Scheduling"));

    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onError).toHaveBeenCalledWith(
      "Retry for Kishore Reddy did not start a new negotiation: Application is flagged for manual scheduling and needs a human to pick it up",
    );
  });

  it("falls back to generic copy when a skip has no reason", async () => {
    retryNegotiationMock.mockResolvedValue({ outcome: null, invalidated_stale_tokens: 0, reason: null });
    const onError = vi.fn();

    render(<RetryNegotiationMenuItem row={makeRow()} onClose={vi.fn()} onDone={vi.fn()} onError={onError} />);
    fireEvent.click(screen.getByText("Retry Scheduling"));

    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onError.mock.calls[0][0]).toContain("check Remarks/the Interview Log tracker");
  });

  it("surfaces a thrown API error via extractErrorMessage", async () => {
    retryNegotiationMock.mockRejectedValue(new Error("network down"));
    const onError = vi.fn();

    render(<RetryNegotiationMenuItem row={makeRow()} onClose={vi.fn()} onDone={vi.fn()} onError={onError} />);
    fireEvent.click(screen.getByText("Retry Scheduling"));

    await waitFor(() => expect(onError).toHaveBeenCalledWith("Failed to retry interview scheduling"));
  });

  it("shows the tracker-locked snackbar text for a TRACKER_LOCKED error, not extractErrorMessage's fallback", async () => {
    retryNegotiationMock.mockRejectedValue({ code: "TRACKER_LOCKED", message: "Tracker file is open in Excel -- close it and retry. (simulated)" });
    const onError = vi.fn();

    render(<RetryNegotiationMenuItem row={makeRow()} onClose={vi.fn()} onDone={vi.fn()} onError={onError} />);
    fireEvent.click(screen.getByText("Retry Scheduling"));

    await waitFor(() => expect(onError).toHaveBeenCalledWith("Tracker file is open in Excel -- close it and retry."));
  });
});
