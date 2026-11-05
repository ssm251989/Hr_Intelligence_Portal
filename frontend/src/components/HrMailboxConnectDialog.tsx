import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, hrInboxApi } from "../api/client";
import type { HrIntegrationRead, HrMailboxValidateRequest } from "../api/types";

// Collects the SMTP+IMAP field set (backend app/schemas/hr_integration.py
// HrIntegrationUpdate/HrMailboxValidateRequest) and validates it for real -- a test email
// send AND an IMAP login, via POST /hr-inbox/settings/validate -- BEFORE ever calling
// PUT /hr-inbox/settings to save it. Nothing is persisted until both checks pass, so a
// failed attempt (wrong password, unreachable host, whatever) can never overwrite --
// and thus never risks losing -- a previously-working saved config, including an
// existing password when editing.
export default function HrMailboxConnectDialog({
  open,
  mode,
  initial,
  onClose,
  onConnected,
}: {
  open: boolean;
  mode: "connect" | "edit";
  initial: HrIntegrationRead | null;
  onClose: () => void;
  onConnected: (updated: HrIntegrationRead) => void;
}) {
  const hasExistingPassword = Boolean(initial?.smtp_configured);

  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("");
  const [useTls, setUseTls] = useState(true);
  const [smtpUsername, setSmtpUsername] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [fromAddress, setFromAddress] = useState("");
  const [hrModuleEmail, setHrModuleEmail] = useState("");
  const [imapHost, setImapHost] = useState("");
  const [imapPort, setImapPort] = useState("");
  const [useSsl, setUseSsl] = useState(true);

  const [submitting, setSubmitting] = useState(false);
  const [submitStage, setSubmitStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Re-seeds from `initial` only at the moment the dialog opens -- not on every `initial`
  // change while it's already open and the admin is mid-edit, which a background settings
  // refresh elsewhere could otherwise trigger and stomp on what they're typing.
  useEffect(() => {
    if (!open) return;
    setSmtpHost(initial?.smtp_host ?? "");
    setSmtpPort(initial?.smtp_port != null ? String(initial.smtp_port) : "");
    setUseTls(initial?.use_tls ?? true);
    setSmtpUsername(initial?.smtp_username ?? "");
    setSmtpPassword("");
    setFromAddress(initial?.from_address ?? "");
    setHrModuleEmail(initial?.hr_module_email ?? "");
    setImapHost(initial?.imap_host ?? "");
    setImapPort(initial?.imap_port != null ? String(initial.imap_port) : "");
    setUseSsl(initial?.use_ssl ?? true);
    setError(null);
    setSubmitStage(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const missingRequiredField =
    !smtpHost.trim() || !smtpPort.trim() || !smtpUsername.trim() ||
    !imapHost.trim() || !imapPort.trim() || (!hasExistingPassword && !smtpPassword.trim());

  const handleSubmit = async () => {
    if (missingRequiredField) {
      setError(`Fill in every required field above${hasExistingPassword ? "" : ", including a password"} before connecting.`);
      return;
    }
    setSubmitting(true);
    setError(null);

    const fields: HrMailboxValidateRequest = {
      smtp_host: smtpHost.trim(),
      smtp_port: Number(smtpPort),
      use_tls: useTls,
      smtp_username: smtpUsername.trim(),
      from_address: fromAddress.trim() || null,
      hr_module_email: hrModuleEmail.trim() || null,
      imap_host: imapHost.trim(),
      imap_port: Number(imapPort),
      use_ssl: useSsl,
    };
    // Blank means "use the currently-stored password" -- both for validating (see the
    // backend's fallback in POST .../validate) and, further down, for saving (PUT leaves
    // smtp_password untouched when it's omitted from the body).
    if (smtpPassword.trim()) {
      fields.smtp_password = smtpPassword.trim();
    }

    try {
      setSubmitStage("Sending a test email...");
      const result = await hrInboxApi.validateSettings(fields);

      if (!result.smtp_ok || !result.imap_ok) {
        const failures = [
          !result.smtp_ok && `Test email: ${result.smtp_error || "failed"}`,
          !result.imap_ok && `IMAP connection: ${result.imap_error || "failed"}`,
        ].filter(Boolean);
        setError(failures.join(" — "));
        return;
      }

      setSubmitStage("Saving...");
      const saved = await hrInboxApi.updateSettings(fields);
      onConnected(saved);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to validate the HR mailbox settings"));
    } finally {
      setSubmitting(false);
      setSubmitStage(null);
    }
  };

  return (
    <Dialog open={open} onClose={submitting ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{mode === "edit" ? "Edit HR Mailbox" : "Connect HR Mailbox"}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" mb={2}>
          Plain SMTP/IMAP credentials for the single shared, org-level mailbox every automated HR email sends from
          and the incoming-mail poll reads from -- works with any provider (Gmail, Outlook, Yahoo, etc.).
          {mode === "edit" ? " Saving" : " Connecting"} sends a real test email to the From address (or username,
          if no From address is set) and checks the IMAP login before anything is saved -- a failed check leaves
          the previously-saved config (including an existing password) untouched.
        </Typography>

        <Stack spacing={2}>
          <Typography variant="subtitle2">Outgoing mail (SMTP)</Typography>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <TextField
              label="SMTP host" size="small" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)}
              sx={{ minWidth: 220, flexGrow: 1 }} required
            />
            <TextField
              label="SMTP port" size="small" type="number" value={smtpPort}
              onChange={(e) => setSmtpPort(e.target.value)} sx={{ minWidth: 120 }} required
            />
            <FormControlLabel
              control={<Checkbox checked={useTls} onChange={(e) => setUseTls(e.target.checked)} />}
              label="Use TLS"
            />
          </Stack>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <TextField
              label="Username" size="small" value={smtpUsername} onChange={(e) => setSmtpUsername(e.target.value)}
              sx={{ minWidth: 220, flexGrow: 1 }} required
            />
            <TextField
              label="Password" size="small" type="password" value={smtpPassword}
              placeholder={hasExistingPassword ? "Leave blank to keep the current password" : ""}
              onChange={(e) => setSmtpPassword(e.target.value)} sx={{ minWidth: 220, flexGrow: 1 }}
              required={!hasExistingPassword}
            />
          </Stack>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <TextField
              label="From address" size="small" value={fromAddress} onChange={(e) => setFromAddress(e.target.value)}
              sx={{ minWidth: 220, flexGrow: 1 }}
            />
            <TextField
              label="HR module email (Reply-To / BCC)" size="small" value={hrModuleEmail}
              onChange={(e) => setHrModuleEmail(e.target.value)} sx={{ minWidth: 260, flexGrow: 1 }}
              helperText="Optional -- added as Reply-To and BCC on every outgoing HR email when set."
            />
          </Stack>

          <Divider />

          <Typography variant="subtitle2">Incoming mail (IMAP) -- checked every 30 minutes</Typography>
          <Typography variant="body2" color="text.secondary">
            Reuses the same username/password above -- it's the same mailbox account.
          </Typography>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            <TextField
              label="IMAP host" size="small" value={imapHost} onChange={(e) => setImapHost(e.target.value)}
              sx={{ minWidth: 220, flexGrow: 1 }} required
            />
            <TextField
              label="IMAP port" size="small" type="number" value={imapPort}
              onChange={(e) => setImapPort(e.target.value)} sx={{ minWidth: 120 }} required
            />
            <FormControlLabel
              control={<Checkbox checked={useSsl} onChange={(e) => setUseSsl(e.target.checked)} />}
              label="Use SSL"
            />
          </Stack>

          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>
          Cancel
        </Button>
        <Button variant="contained" onClick={handleSubmit} disabled={submitting}>
          {submitting ? submitStage || "Working..." : mode === "edit" ? "Save & Verify" : "Connect"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
