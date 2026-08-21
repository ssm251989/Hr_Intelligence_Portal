import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import Divider from "@mui/material/Divider";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, hrInboxApi } from "../api/client";
import type { HrIntegrationRead, HrIntegrationUpdate } from "../api/types";

// The single shared, org-level HR mailbox every automated HR email sends from --
// interview scheduling emails, candidate messages, and new-application notifications --
// across every recruiter, admin-only. Plain SMTP/IMAP credentials rather than a Google
// OAuth connection (universal across providers), replacing the earlier "Connect CTDHR
// Account" OAuth card entirely. This is separate from the "Google Calendar" card above,
// which still creates each recruiter's own interview Calendar events.
export default function HrMailboxSettingsCard() {
  const [settings, setSettings] = useState<HrIntegrationRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

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

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const [testEmailTo, setTestEmailTo] = useState("");
  const [sendingTestEmail, setSendingTestEmail] = useState(false);
  const [testEmailResult, setTestEmailResult] = useState<{ ok: boolean; detail: string } | null>(null);

  const [testingImap, setTestingImap] = useState(false);
  const [imapTestResult, setImapTestResult] = useState<{ ok: boolean; detail: string } | null>(null);

  const applySettings = (loaded: HrIntegrationRead) => {
    setSettings(loaded);
    setSmtpHost(loaded.smtp_host ?? "");
    setSmtpPort(loaded.smtp_port != null ? String(loaded.smtp_port) : "");
    setUseTls(loaded.use_tls ?? true);
    setSmtpUsername(loaded.smtp_username ?? "");
    setFromAddress(loaded.from_address ?? "");
    setHrModuleEmail(loaded.hr_module_email ?? "");
    setImapHost(loaded.imap_host ?? "");
    setImapPort(loaded.imap_port != null ? String(loaded.imap_port) : "");
    setUseSsl(loaded.use_ssl ?? true);
  };

  useEffect(() => {
    hrInboxApi
      .getSettings()
      .then(applySettings)
      .catch((err) => setLoadError(extractErrorMessage(err, "Failed to load the HR mailbox settings")))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const payload: HrIntegrationUpdate = {
        smtp_host: smtpHost.trim() || null,
        smtp_port: smtpPort.trim() ? Number(smtpPort) : null,
        use_tls: useTls,
        smtp_username: smtpUsername.trim() || null,
        from_address: fromAddress.trim() || null,
        hr_module_email: hrModuleEmail.trim() || null,
        imap_host: imapHost.trim() || null,
        imap_port: imapPort.trim() ? Number(imapPort) : null,
        use_ssl: useSsl,
      };
      // Blank means "leave the currently-stored password alone" -- never send an empty
      // string, which the backend would otherwise have to special-case as "no change"
      // vs. "clear it" (see app.integrations.hr_email.encrypted_smtp_password).
      if (smtpPassword.trim()) {
        payload.smtp_password = smtpPassword.trim();
      }
      const updated = await hrInboxApi.updateSettings(payload);
      applySettings(updated);
      setSmtpPassword("");
      setSaveSuccess(true);
    } catch (err) {
      setSaveError(extractErrorMessage(err, "Failed to save the HR mailbox settings"));
    } finally {
      setSaving(false);
    }
  };

  const handleSendTestEmail = async () => {
    if (!testEmailTo.trim()) return;
    setSendingTestEmail(true);
    setTestEmailResult(null);
    try {
      const result = await hrInboxApi.sendTestEmail(testEmailTo.trim());
      setTestEmailResult({ ok: result.sent, detail: result.detail ?? (result.sent ? "Sent." : "Failed to send.") });
    } catch (err) {
      setTestEmailResult({ ok: false, detail: extractErrorMessage(err, "Failed to send the test email") });
    } finally {
      setSendingTestEmail(false);
    }
  };

  const handleTestImapConnection = async () => {
    setTestingImap(true);
    setImapTestResult(null);
    try {
      const result = await hrInboxApi.testImapConnection();
      setImapTestResult({
        ok: result.connected,
        detail: result.detail ?? (result.connected ? "Connected." : "Failed to connect."),
      });
    } catch (err) {
      setImapTestResult({ ok: false, detail: extractErrorMessage(err, "Failed to test the IMAP connection") });
    } finally {
      setTestingImap(false);
    }
  };

  return (
    <Card variant="outlined" sx={{ maxWidth: 560 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          HR Mailbox (Shared Email Account)
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          The single shared, org-level mailbox every automated HR email sends from -- interview scheduling emails,
          candidate messages, and new-application notifications -- across every recruiter, admin-only. Plain
          SMTP/IMAP credentials work with any email provider (Gmail, Outlook, Yahoo, etc.), no Google OAuth
          connection required. This is separate from the Google Calendar card above, which still creates each
          recruiter's own interview Calendar events.
        </Typography>

        {loadError && <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>}

        {loading ? (
          <CircularProgress size={24} />
        ) : (
          <Stack spacing={2}>
            <Typography variant="subtitle2">Outgoing mail (SMTP)</Typography>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
              <TextField
                label="SMTP host" size="small" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)}
                sx={{ minWidth: 220, flexGrow: 1 }}
              />
              <TextField
                label="SMTP port" size="small" type="number" value={smtpPort}
                onChange={(e) => setSmtpPort(e.target.value)} sx={{ minWidth: 120 }}
              />
              <FormControlLabel
                control={<Checkbox checked={useTls} onChange={(e) => setUseTls(e.target.checked)} />}
                label="Use TLS"
              />
            </Stack>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
              <TextField
                label="Username" size="small" value={smtpUsername} onChange={(e) => setSmtpUsername(e.target.value)}
                sx={{ minWidth: 220, flexGrow: 1 }}
              />
              <TextField
                label="Password" size="small" type="password" value={smtpPassword}
                placeholder={settings?.smtp_configured ? "Leave blank to keep the current password" : ""}
                onChange={(e) => setSmtpPassword(e.target.value)} sx={{ minWidth: 220, flexGrow: 1 }}
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
                sx={{ minWidth: 220, flexGrow: 1 }}
              />
              <TextField
                label="IMAP port" size="small" type="number" value={imapPort}
                onChange={(e) => setImapPort(e.target.value)} sx={{ minWidth: 120 }}
              />
              <FormControlLabel
                control={<Checkbox checked={useSsl} onChange={(e) => setUseSsl(e.target.checked)} />}
                label="Use SSL"
              />
            </Stack>

            {saveError && <Alert severity="error" onClose={() => setSaveError(null)}>{saveError}</Alert>}
            {saveSuccess && <Alert severity="success" onClose={() => setSaveSuccess(false)}>Settings saved.</Alert>}

            <Stack direction="row" spacing={2} alignItems="center">
              <Button variant="contained" onClick={handleSave} disabled={saving}>
                {saving ? "Saving..." : "Save"}
              </Button>
            </Stack>

            <Divider />

            <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
              <TextField
                label="Send test email to" size="small" value={testEmailTo}
                onChange={(e) => setTestEmailTo(e.target.value)} sx={{ minWidth: 240 }}
              />
              <Button
                variant="outlined" onClick={handleSendTestEmail} disabled={sendingTestEmail || !testEmailTo.trim()}
              >
                {sendingTestEmail ? "Sending..." : "Send test email"}
              </Button>
              <Button variant="outlined" onClick={handleTestImapConnection} disabled={testingImap}>
                {testingImap ? "Testing..." : "Test IMAP connection"}
              </Button>
            </Stack>
            {testEmailResult && (
              <Alert severity={testEmailResult.ok ? "success" : "error"} onClose={() => setTestEmailResult(null)}>
                {testEmailResult.detail}
              </Alert>
            )}
            {imapTestResult && (
              <Alert severity={imapTestResult.ok ? "success" : "error"} onClose={() => setImapTestResult(null)}>
                {imapTestResult.detail}
              </Alert>
            )}
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
