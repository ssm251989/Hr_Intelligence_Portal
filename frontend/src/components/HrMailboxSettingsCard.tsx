import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, hrInboxApi } from "../api/client";
import type { HrIntegrationRead } from "../api/types";
import ConfirmDialog from "./ConfirmDialog";
import HrMailboxConnectDialog from "./HrMailboxConnectDialog";

// The single shared, org-level HR mailbox every automated HR email sends from and the
// incoming-mail poll reads from -- interview scheduling emails, candidate messages, and
// new-application notifications, across every recruiter, admin-only. Plain SMTP/IMAP
// credentials rather than a Google OAuth connection (universal across providers).
//
// Same Connect/Connected/Disconnect visual pattern as the personal Google/DocuSign/
// LinkedIn IntegrationCard elsewhere on this page -- a status Chip plus a single action
// button when not connected -- except "Connected" here is only ever reached by actually
// validating the credentials (a real test send + IMAP login, see
// HrMailboxConnectDialog), not merely by having saved something that looks filled in.
export default function HrMailboxSettingsCard() {
  const [settings, setSettings] = useState<HrIntegrationRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);

  const [testEmailTo, setTestEmailTo] = useState("");
  const [sendingTestEmail, setSendingTestEmail] = useState(false);
  const [testEmailResult, setTestEmailResult] = useState<{ ok: boolean; detail: string } | null>(null);

  const [testingImap, setTestingImap] = useState(false);
  const [imapTestResult, setImapTestResult] = useState<{ ok: boolean; detail: string } | null>(null);

  useEffect(() => {
    hrInboxApi
      .getSettings()
      .then(setSettings)
      .catch((err) => setLoadError(extractErrorMessage(err, "Failed to load the HR mailbox settings")))
      .finally(() => setLoading(false));
  }, []);

  // Both sides configured is the only way this ever becomes true post-connect (the dialog
  // validates and saves both together, or reverts both) -- so it doubles correctly as
  // "was actually validated", not just "something is filled in".
  const connected = Boolean(settings?.smtp_configured && settings?.imap_configured);

  const handleDisconnect = async () => {
    setDisconnecting(true);
    setDisconnectError(null);
    try {
      const updated = await hrInboxApi.updateSettings({
        smtp_host: null, smtp_port: null, use_tls: null, smtp_username: null,
        from_address: null, hr_module_email: null, imap_host: null, imap_port: null, use_ssl: null,
      });
      setSettings(updated);
      setDisconnectOpen(false);
      setTestEmailResult(null);
      setImapTestResult(null);
    } catch (err) {
      setDisconnectError(extractErrorMessage(err, "Failed to disconnect the HR mailbox"));
    } finally {
      setDisconnecting(false);
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
          The single shared, org-level mailbox every automated HR email sends from and the incoming-mail poll
          reads from -- interview scheduling emails, candidate messages, new-application notifications, and every
          reply back -- across every recruiter, admin-only. Plain SMTP/IMAP credentials work with any email
          provider (Gmail, Outlook, Yahoo, etc.), no Google OAuth connection required. This is separate from the
          Google Calendar card above, which still creates each recruiter's own interview Calendar events.
        </Typography>

        {loadError && <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>}

        {loading ? (
          <CircularProgress size={24} />
        ) : (
          <Stack spacing={2}>
            <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
              <Chip label={connected ? "Connected" : "Not connected"} color={connected ? "success" : "default"} size="small" />
              {connected && settings?.from_address && (
                <Typography variant="body2" color="text.secondary">
                  {settings.from_address}
                </Typography>
              )}
              {!connected ? (
                <Button size="small" variant="contained" onClick={() => setDialogOpen(true)}>
                  Connect
                </Button>
              ) : (
                <>
                  <Button size="small" variant="outlined" onClick={() => setDialogOpen(true)}>
                    Edit
                  </Button>
                  <Button size="small" color="error" onClick={() => setDisconnectOpen(true)}>
                    Disconnect
                  </Button>
                </>
              )}
            </Stack>

            {disconnectError && (
              <Alert severity="error" onClose={() => setDisconnectError(null)}>
                {disconnectError}
              </Alert>
            )}

            {connected && (
              <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
                <TextField
                  label="Send test email to" size="small" value={testEmailTo}
                  onChange={(e) => setTestEmailTo(e.target.value)} sx={{ minWidth: 240 }}
                />
                <Button variant="outlined" onClick={handleSendTestEmail} disabled={sendingTestEmail || !testEmailTo.trim()}>
                  {sendingTestEmail ? "Sending..." : "Send test email"}
                </Button>
                <Button variant="outlined" onClick={handleTestImapConnection} disabled={testingImap}>
                  {testingImap ? "Testing..." : "Test IMAP connection"}
                </Button>
              </Stack>
            )}
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

      <HrMailboxConnectDialog
        open={dialogOpen}
        mode={connected ? "edit" : "connect"}
        initial={settings}
        onClose={() => setDialogOpen(false)}
        onConnected={(updated) => {
          setSettings(updated);
          setDialogOpen(false);
        }}
      />

      <ConfirmDialog
        open={disconnectOpen}
        title="Disconnect HR mailbox?"
        message="This clears the stored SMTP/IMAP credentials. Automated HR emails and the incoming-mail poll will stop working until it's reconnected."
        confirmLabel="Disconnect"
        confirming={disconnecting}
        onConfirm={handleDisconnect}
        onCancel={() => setDisconnectOpen(false)}
      />
    </Card>
  );
}
