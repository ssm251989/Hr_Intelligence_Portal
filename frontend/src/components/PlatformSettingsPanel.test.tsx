// Part 31.3: the Settings panel speaks the app's language (no English words in Hindi / Tamil), and a JSON setting
// can be cleared (an empty box saves the built-in default, never "not valid JSON").
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const values = vi.fn();
const update = vi.fn();
const history = vi.fn();
const revert = vi.fn();

vi.mock("../api/client", () => ({
  extractErrorMessage: (_err: unknown, fallback: string) => fallback,
  platformSettingsApi: {
    definitions: () => Promise.resolve([
      { key: "recruitment.salary.reminder_hours", type: "json", default: [24, 48], module: "recruitment", group: "Salary", label_i18n_key: "",
        help_i18n_key: "", scopes_allowed: ["tenant"], sensitive: false, requires_restart: false, help: "Salary form reminders (hours)", affects: null },
      { key: "iam.auth.mfa_required", type: "bool", default: false, module: "iam", group: "Sign-in", label_i18n_key: "", help_i18n_key: "",
        scopes_allowed: ["tenant"], sensitive: false, requires_restart: false, help: "Two-step sign-in", affects: null },
    ]),
    values: (...a: unknown[]) => values(...a),
    update: (...a: unknown[]) => update(...a),
    history: (...a: unknown[]) => history(...a),
    revert: (...a: unknown[]) => revert(...a),
  },
}));
vi.mock("../bootstrap/BootstrapContext", () => ({ useBootstrap: () => ({ reload: vi.fn() }) }));
vi.mock("../bootstrap/MeBootstrapContext", () => ({ useMeBootstrap: () => ({ reload: vi.fn() }) }));

import { I18nProvider } from "../i18n";
import PlatformSettingsPanel from "./PlatformSettingsPanel";

const ENGLISH = [/\bEdit\b/, /\bHistory\b/, /\bSave\b/, /\bCancel\b/, /\(empty\)/, /\(current\)/, /\bunknown\b/, /No changes recorded/,
  /Revert to this/, /\btrue\b/, /\bfalse\b/, /-- history/];

function renderIn(locale: string) {
  localStorage.setItem("hrms.locale", locale);
  return render(<I18nProvider><PlatformSettingsPanel /></I18nProvider>);
}

beforeEach(() => {
  values.mockResolvedValue([{ key: "recruitment.salary.reminder_hours", value: [12], scope_type: "tenant", scope_id: null, is_default: false },
    { key: "iam.auth.mfa_required", value: true, scope_type: "tenant", scope_id: null, is_default: false }]);
  history.mockResolvedValue([
    { value: [12], version: 2, updated_by: null, updated_at: "2026-11-21T10:00:00Z", scope_type: "tenant", scope_id: null },
    { value: [24, 48], version: 1, updated_by: "hr@example.com", updated_at: "2026-11-20T10:00:00Z", scope_type: "tenant", scope_id: null },
  ]);
  update.mockResolvedValue({});
});
afterEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("PlatformSettingsPanel", () => {
  it.each(["hi", "ta"])("has no English words left in %s (rows, edit box, history)", async (locale) => {
    const { container } = renderIn(locale);
    await screen.findByText("Two-step sign-in");
    const editButtons = await screen.findAllByRole("button", { name: locale === "hi" ? "बदलें" : "திருத்து" });
    fireEvent.click(editButtons[1]); // the yes/no setting: its choices are words, not true / false
    fireEvent.click((await screen.findAllByRole("button", { name: locale === "hi" ? "इतिहास" : "வரலாறு" }))[0]);
    await waitFor(() => expect(history).toHaveBeenCalled());
    await screen.findByText(locale === "hi" ? "इस पर वापस लाएँ" : "இதற்குத் திரும்பு");
    const text = (container.textContent ?? "") + (document.body.textContent ?? "");
    for (const word of ENGLISH) expect(text).not.toMatch(word);
  });

  it("clearing a JSON setting saves its built-in default instead of a JSON error", async () => {
    renderIn("en");
    await screen.findByText("Salary form reminders (hours)");
    fireEvent.click((await screen.findAllByRole("button", { name: "Edit" }))[0]);
    const box = await screen.findByDisplayValue("[12]");
    fireEvent.change(box, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("recruitment.salary.reminder_hours", [24, 48]));
    expect(screen.queryByText(/not valid JSON/)).toBeNull();
  });

  it("a bad number never reaches the server", async () => {
    renderIn("en");
    await screen.findByText("Salary form reminders (hours)");
    fireEvent.click((await screen.findAllByRole("button", { name: "Edit" }))[0]);
    fireEvent.change(await screen.findByDisplayValue("[12]"), { target: { value: "[12," } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("This value isn't valid JSON.");
    expect(update).not.toHaveBeenCalled();
  });

  it("the history stays open after Revert and shows the new entry (Part 31.4 proof)", async () => {
    revert.mockResolvedValue({});
    renderIn("en");
    await screen.findByText("Salary form reminders (hours)");
    fireEvent.click((await screen.findAllByRole("button", { name: "History" }))[0]);
    const revertBtn = await screen.findByRole("button", { name: "Revert to this" });
    history.mockResolvedValue([
      { value: [24, 48], version: 3, updated_by: "hr@example.com (revert to v1)", updated_at: "2026-11-21T11:00:00Z", scope_type: "tenant", scope_id: null },
      { value: [12], version: 2, updated_by: null, updated_at: "2026-11-21T10:00:00Z", scope_type: "tenant", scope_id: null },
      { value: [24, 48], version: 1, updated_by: "hr@example.com", updated_at: "2026-11-20T10:00:00Z", scope_type: "tenant", scope_id: null },
    ]);
    const rows = await values.mock.results[0].value;
    values.mockImplementation(() => new Promise((resolve) => setTimeout(() => resolve(rows), 40))); // a reload takes a moment, as over the network
    fireEvent.click(revertBtn);
    await waitFor(() => expect(revert).toHaveBeenCalledWith("recruitment.salary.reminder_hours", 1));
    await waitFor(() => expect(values).toHaveBeenCalledTimes(2)); // the panel reloaded its values after the revert
    await new Promise((r) => setTimeout(r, 80));
    expect(screen.queryByRole("dialog")).not.toBeNull(); // ...and the history is still open
    expect(await screen.findByText(/\(revert to v1\)/)).toBeTruthy();
  });
});
