import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HrIntegrationRead } from "../api/types";
import HrMailboxSettingsCard from "./HrMailboxSettingsCard";

const getSettingsMock = vi.fn();
const updateSettingsMock = vi.fn();
const validateSettingsMock = vi.fn();
const sendTestEmailMock = vi.fn();
const testImapConnectionMock = vi.fn();

vi.mock("../api/client", () => ({
  hrInboxApi: {
    getSettings: (...args: unknown[]) => getSettingsMock(...args),
    updateSettings: (...args: unknown[]) => updateSettingsMock(...args),
    validateSettings: (...args: unknown[]) => validateSettingsMock(...args),
    sendTestEmail: (...args: unknown[]) => sendTestEmailMock(...args),
    testImapConnection: (...args: unknown[]) => testImapConnectionMock(...args),
  },
  extractErrorMessage: (_err: unknown, fallback: string) => fallback,
}));

const UNCONFIGURED: HrIntegrationRead = {
  smtp_host: null, smtp_port: null, use_tls: null, smtp_username: null,
  from_address: null, hr_module_email: null, smtp_configured: false,
  imap_host: null, imap_port: null, use_ssl: null, imap_configured: false,
};

const CONFIGURED: HrIntegrationRead = {
  smtp_host: "smtp.example.com", smtp_port: 587, use_tls: true, smtp_username: "hr@example.com",
  from_address: "hr@example.com", hr_module_email: null, smtp_configured: true,
  imap_host: "imap.example.com", imap_port: 993, use_ssl: true, imap_configured: true,
};

const PASSING_VALIDATION = { smtp_ok: true, smtp_error: null, imap_ok: true, imap_error: null };

function fillRequiredConnectFields() {
  fireEvent.change(screen.getByLabelText(/SMTP host/), { target: { value: "smtp.example.com" } });
  fireEvent.change(screen.getByLabelText(/SMTP port/), { target: { value: "587" } });
  fireEvent.change(screen.getByLabelText(/^Username/), { target: { value: "hr@example.com" } });
  fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: "secret-password" } });
  fireEvent.change(screen.getByLabelText(/IMAP host/), { target: { value: "imap.example.com" } });
  fireEvent.change(screen.getByLabelText(/IMAP port/), { target: { value: "993" } });
}

describe("HrMailboxSettingsCard", () => {
  beforeEach(() => {
    getSettingsMock.mockReset();
    updateSettingsMock.mockReset();
    validateSettingsMock.mockReset();
    sendTestEmailMock.mockReset();
    testImapConnectionMock.mockReset();
  });

  it("shows a Not-connected badge and a Connect button when no mailbox is configured", async () => {
    getSettingsMock.mockResolvedValue(UNCONFIGURED);

    render(<HrMailboxSettingsCard />);

    await waitFor(() => expect(screen.getByText("Not connected")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disconnect" })).not.toBeInTheDocument();
  });

  it("flips to Connected only once validation passes, saving only after both checks succeed", async () => {
    getSettingsMock.mockResolvedValue(UNCONFIGURED);
    validateSettingsMock.mockResolvedValue(PASSING_VALIDATION);
    updateSettingsMock.mockResolvedValueOnce(CONFIGURED);

    render(<HrMailboxSettingsCard />);
    await waitFor(() => expect(screen.getByText("Not connected")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const dialog = await screen.findByRole("dialog");
    fillRequiredConnectFields();
    fireEvent.click(within(dialog).getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());
    expect(screen.getByText("hr@example.com")).toBeInTheDocument();
    // MUI's Dialog un-mounts only after its exit transition finishes, so give it a beat.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(validateSettingsMock).toHaveBeenCalledTimes(1);
    // Exactly one PUT -- the real save, made only after validation already passed.
    expect(updateSettingsMock).toHaveBeenCalledTimes(1);
  });

  it("shows the specific validation error inline, stays Not connected, and never calls save on a failed check", async () => {
    getSettingsMock.mockResolvedValue(UNCONFIGURED);
    validateSettingsMock.mockResolvedValue({
      smtp_ok: false, smtp_error: "Authentication failed", imap_ok: true, imap_error: null,
    });

    render(<HrMailboxSettingsCard />);
    await waitFor(() => expect(screen.getByText("Not connected")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    const dialog = await screen.findByRole("dialog");
    fillRequiredConnectFields();
    fireEvent.click(within(dialog).getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(within(dialog).getByText(/Authentication failed/)).toBeInTheDocument());
    // The dialog stays open with the admin's typed values still there to fix and retry.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Not connected")).toBeInTheDocument();
    // The whole point of validate-then-save: a failed check never even attempts a save,
    // so there is nothing that could have overwritten (and thus lost) a saved config.
    expect(updateSettingsMock).not.toHaveBeenCalled();
  });

  it("editing an already-connected mailbox with a blank password re-validates using the existing one, with zero save risk on failure", async () => {
    getSettingsMock.mockResolvedValue(CONFIGURED);
    validateSettingsMock.mockResolvedValue({
      smtp_ok: false, smtp_error: "IMAP host unreachable", imap_ok: false, imap_error: "IMAP host unreachable",
    });

    render(<HrMailboxSettingsCard />);
    await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");

    // Only change the From address -- password field is left blank on purpose.
    const fromAddressField = within(dialog).getByLabelText(/From address/);
    fireEvent.change(fromAddressField, { target: { value: "hr-new@example.com" } });
    expect(within(dialog).getByLabelText(/^Password/)).toHaveValue("");

    fireEvent.click(within(dialog).getByRole("button", { name: "Save & Verify" }));

    await waitFor(() => expect(within(dialog).getByText(/IMAP host unreachable/)).toBeInTheDocument());
    // Validated with the changed field but WITHOUT a password in the request body -- the
    // backend falls back to the currently-stored one (see the backend's own test for
    // that fallback); the point here is the frontend never sends a blank/placeholder
    // password value.
    expect(validateSettingsMock).toHaveBeenCalledWith(
      expect.objectContaining({ from_address: "hr-new@example.com" }),
    );
    expect(validateSettingsMock.mock.calls[0][0]).not.toHaveProperty("smtp_password");
    // No save was ever attempted, so the previously-working config (including its real
    // password) was never at risk of being overwritten by this failed attempt.
    expect(updateSettingsMock).not.toHaveBeenCalled();
    // Still shown as connected with the ORIGINAL address -- nothing changed underneath.
    expect(screen.getByText("hr@example.com")).toBeInTheDocument();
  });

  it("Disconnect clears the credentials and reverts the card to Not connected", async () => {
    getSettingsMock.mockResolvedValue(CONFIGURED);
    updateSettingsMock.mockResolvedValueOnce(UNCONFIGURED);

    render(<HrMailboxSettingsCard />);
    await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    const confirmDialog = await screen.findByRole("dialog");
    fireEvent.click(within(confirmDialog).getByRole("button", { name: "Disconnect" }));

    await waitFor(() => expect(screen.getByText("Not connected")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument());
    expect(updateSettingsMock).toHaveBeenCalledWith(
      expect.objectContaining({ smtp_host: null, smtp_username: null, imap_host: null }),
    );
  });
});
