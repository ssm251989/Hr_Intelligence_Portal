import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LocalImportSettings, LocalImportSettingsSaveResult } from "../api/types";
import ImportCandidatesWizard from "./ImportCandidatesWizard";

const listApplicationsMock = vi.fn();
const getSettingsMock = vi.fn();
const updateSettingsMock = vi.fn();

vi.mock("../api/client", () => ({
  candidatesApi: {
    listApplications: (...args: unknown[]) => listApplicationsMock(...args),
  },
  localImportApi: {
    getSettings: (...args: unknown[]) => getSettingsMock(...args),
    updateSettings: (...args: unknown[]) => updateSettingsMock(...args),
  },
  extractErrorMessage: (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback),
}));

const UNCONFIGURED: LocalImportSettings = {
  ready_to_upload_root: null,
  already_uploaded_root: null,
  scan_interval_minutes: 30,
};

const SAVE_RESULT: LocalImportSettingsSaveResult = {
  ready_to_upload_root: "/srv/hr/ready-to-upload",
  already_uploaded_root: "/srv/hr/already-uploaded",
  scan_interval_minutes: 45,
  updated_at: "2026-08-19T00:00:00Z",
  jobs_considered: 3,
  folders_created: 6,
};

function selectLocalImportAndAdvance() {
  fireEvent.click(screen.getByText("Local Import"));
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
}

describe("ImportCandidatesWizard -- Local Import (Part G folder configuration)", () => {
  beforeEach(() => {
    listApplicationsMock.mockReset();
    getSettingsMock.mockReset().mockResolvedValue(UNCONFIGURED);
    updateSettingsMock.mockReset();
  });

  it("shows the two folder-path fields and the scan-interval field once Local Import is selected", async () => {
    render(<ImportCandidatesWizard open onClose={vi.fn()} onImported={vi.fn()} initialSource={null} />);

    selectLocalImportAndAdvance();

    await waitFor(() => expect(getSettingsMock).toHaveBeenCalled());
    expect(await screen.findByRole("textbox", { name: "Ready to Upload root path" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Already Uploaded root path" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Scan interval (minutes)" })).toBeInTheDocument();
  });

  it("prefills all three fields from the currently saved settings", async () => {
    getSettingsMock.mockResolvedValue({
      ready_to_upload_root: "/existing/ready",
      already_uploaded_root: "/existing/already",
      scan_interval_minutes: 60,
    });

    render(<ImportCandidatesWizard open onClose={vi.fn()} onImported={vi.fn()} initialSource={null} />);
    selectLocalImportAndAdvance();

    expect(await screen.findByDisplayValue("/existing/ready")).toBeInTheDocument();
    expect(screen.getByDisplayValue("/existing/already")).toBeInTheDocument();
    expect(screen.getByDisplayValue("60")).toBeInTheDocument();
  });

  it("requires both paths before saving", async () => {
    render(<ImportCandidatesWizard open onClose={vi.fn()} onImported={vi.fn()} initialSource={null} />);
    selectLocalImportAndAdvance();
    await screen.findByRole("textbox", { name: "Ready to Upload root path" });

    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Both folder paths are required")).toBeInTheDocument();
    expect(updateSettingsMock).not.toHaveBeenCalled();
  });

  it("saves all three fields and shows the job-folder sync summary", async () => {
    updateSettingsMock.mockResolvedValue(SAVE_RESULT);

    render(<ImportCandidatesWizard open onClose={vi.fn()} onImported={vi.fn()} initialSource={null} />);
    selectLocalImportAndAdvance();
    await screen.findByRole("textbox", { name: "Ready to Upload root path" });

    fireEvent.change(screen.getByRole("textbox", { name: "Ready to Upload root path" }), {
      target: { value: "/srv/hr/ready-to-upload" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Already Uploaded root path" }), {
      target: { value: "/srv/hr/already-uploaded" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Scan interval (minutes)" }), {
      target: { value: "45" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(updateSettingsMock).toHaveBeenCalledWith({
        ready_to_upload_root: "/srv/hr/ready-to-upload",
        already_uploaded_root: "/srv/hr/already-uploaded",
        scan_interval_minutes: 45,
      }),
    );
    expect(await screen.findByText("Folder settings saved.")).toBeInTheDocument();
    expect(screen.getByText(/6 job folders created/)).toBeInTheDocument();
    expect(screen.getByText(/3 currently published\/ready-for-publishing jobs/)).toBeInTheDocument();
    expect(screen.getByText(/every 45 minutes/)).toBeInTheDocument();
  });

  it("rejects a scan interval outside the 5-1440 minute bounds", async () => {
    render(<ImportCandidatesWizard open onClose={vi.fn()} onImported={vi.fn()} initialSource={null} />);
    selectLocalImportAndAdvance();
    await screen.findByRole("textbox", { name: "Ready to Upload root path" });

    fireEvent.change(screen.getByRole("textbox", { name: "Ready to Upload root path" }), {
      target: { value: "/srv/hr/ready-to-upload" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Already Uploaded root path" }), {
      target: { value: "/srv/hr/already-uploaded" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Scan interval (minutes)" }), {
      target: { value: "1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Scan interval must be between 5 and 1440 minutes")).toBeInTheDocument();
    expect(updateSettingsMock).not.toHaveBeenCalled();
  });

  it("shows an error and stays on the configure step when saving fails", async () => {
    updateSettingsMock.mockRejectedValue(new Error("Permission denied writing to that path"));

    render(<ImportCandidatesWizard open onClose={vi.fn()} onImported={vi.fn()} initialSource={null} />);
    selectLocalImportAndAdvance();
    await screen.findByRole("textbox", { name: "Ready to Upload root path" });

    fireEvent.change(screen.getByRole("textbox", { name: "Ready to Upload root path" }), { target: { value: "/bad/ready" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Already Uploaded root path" }), { target: { value: "/bad/already" } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Permission denied writing to that path")).toBeInTheDocument();
    // Still on the Configure step -- the path fields are still visible.
    expect(screen.getByRole("textbox", { name: "Ready to Upload root path" })).toBeInTheDocument();
  });
});
