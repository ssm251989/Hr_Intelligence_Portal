import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { connectorsApi, extractErrorMessage, http, type ConnectionRow, type ProviderCatalogEntry, type PurposeStatus } from "../api/client";
import { t as tr } from "../i18n";
import ConfirmDialog from "./ConfirmDialog";

export function purposeLabel(code: string): string {
  const text = tr(`purpose.${code}`);
  return text === `purpose.${code}` ? code.split(".").slice(1).join(" ").replace(/_/g, " ") || code : text;
}

// Part 18.22: example values shown as placeholders (never real ones) so people know what goes where.
const EXAMPLES: Record<string, string> = {
  host: "smtp.gmail.com / imap.gmail.com", port: "587 (SMTP) / 993 (IMAP)", username: "hr@yourcompany.com", password: "app password",
  from_address: "hr@yourcompany.com", api_key: "sk-ant-… / your provider key", client_id: "from your provider's app page",
  client_secret: "from your provider's app page", integration_key: "DocuSign integration key", secret_key: "DocuSign secret key",
  account_id: "DocuSign account ID", bucket: "my-company-files", region: "ap-south-1", base_url: "https://…", root_path: "C:\\hrms\\files",
};
const example = (field: string) => EXAMPLES[field] ?? tr("conn.example");

type Mode = { kind: "new" } | { kind: "edit"; row: ConnectionRow } | null;

// Settings > Integrations > Connections -- every connection with its status chip, last test,
// Test, Edit (masked secrets: empty = keep the saved one), Disconnect (with confirm), + New.
function ConnectionDialog({ mode, providers, onClose, onSaved }: { mode: Mode; providers: ProviderCatalogEntry[]; onClose: () => void; onSaved: (id?: string) => void }) {
  const editing = mode?.kind === "edit" ? mode.row : null;
  const implemented = providers.filter((p) => p.implemented);
  const [providerCode, setProviderCode] = useState("");
  const [name, setName] = useState("");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!mode) return;
    setError(null);
    setSecrets({});
    if (editing) {
      setProviderCode(editing.provider_code);
      setName(editing.name);
      setConfig(Object.fromEntries(Object.entries(editing.config_json ?? {}).map(([k, v]) => [k, v == null ? "" : String(v)])));
    } else {
      setProviderCode(implemented[0]?.code ?? "");
      setName("");
      setConfig({});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const selected = providers.find((p) => p.code === providerCode);
  const configFields = Object.keys((selected?.config_schema.properties as Record<string, unknown>) ?? {});
  const save = async () => {
    setSaving(true); setError(null);
    try {
      const cleanConfig = Object.fromEntries(Object.entries(config).filter(([, v]) => v !== "").map(([k, v]) => [k, /^\d+$/.test(v) ? Number(v) : v]));
      if (editing) {
        await http.patch(`/api/v1/connections/${editing.id}`, { name, config: cleanConfig, secrets: Object.keys(secrets).length ? secrets : undefined, status: editing.status === "disabled" ? "draft" : undefined });
        onSaved(editing.id);
      } else {
        const row = await connectorsApi.createConnection({ name, provider_code: providerCode, config: cleanConfig, secrets });
        onSaved(row.id);
      }
      onClose();
    } catch (err) { setError(extractErrorMessage(err, tr("conn.err"))); } finally { setSaving(false); }
  };

  return (
    <Dialog open={mode !== null} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{editing ? tr("conn.edit_title", { name: editing.name }) : tr("conn.new_title")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          <TextField select size="small" label={tr("conn.provider")} value={providerCode} onChange={(e) => setProviderCode(e.target.value)} disabled={Boolean(editing)}>
            {(editing ? providers.filter((p) => p.code === editing.provider_code) : implemented).map((p) => (
              <MenuItem key={p.code} value={p.code}>{p.code} ({p.capabilities.join(", ")})</MenuItem>
            ))}
          </TextField>
          <TextField size="small" label={tr("conn.name")} value={name} onChange={(e) => setName(e.target.value)} placeholder={tr("conn.name_eg")} />
          {configFields.map((field) => (
            <TextField key={field} size="small" label={field.replace(/_/g, " ")} value={config[field] ?? ""} placeholder={example(field)}
              onChange={(e) => setConfig((prev) => ({ ...prev, [field]: e.target.value }))} />
          ))}
          {(selected?.secret_fields ?? []).map((field) => (
            <TextField key={field} size="small" type="password" autoComplete="new-password" label={field.replace(/_/g, " ")} value={secrets[field] ?? ""}
              placeholder={editing ? tr("conn.saved_secret") : example(field)} helperText={editing ? tr("conn.keep_secret") : " "}
              onChange={(e) => setSecrets((prev) => ({ ...prev, [field]: e.target.value }))} />
          ))}
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{tr("lock.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={saving || !name || !providerCode}>{editing ? tr("lock.save") : tr("conn.create")}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function ConnectionsPanel() {
  const [connections, setConnections] = useState<ConnectionRow[]>([]);
  const [providers, setProviders] = useState<ProviderCatalogEntry[]>([]);
  const [purposes, setPurposes] = useState<PurposeStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>(null);
  const [disconnecting, setDisconnecting] = useState<ConnectionRow | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([connectorsApi.connections(), connectorsApi.providers(), connectorsApi.purposes()])
      .then(([conns, provs, purps]) => { setConnections(conns); setProviders(provs); setPurposes(purps); })
      .catch((err) => setError(extractErrorMessage(err, tr("conn.err"))))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const handleTest = async (id: string) => {
    setTesting(id); setError(null); setNotice(null);
    try {
      const r = await connectorsApi.testConnection(id);
      if (r.success) setNotice(tr("conn.test_ok")); else setError(r.error || tr("conn.test_failed"));
      load();
    } catch (err) { setError(extractErrorMessage(err, tr("conn.test_failed"))); } finally { setTesting(null); }
  };

  const unrouted = purposes.filter((p) => !p.routed && !p.purpose.startsWith("email."));
  const tone = (s: string): "success" | "error" | "warning" | "default" => (s === "active" ? "success" : s === "error" ? "error" : s === "draft" ? "warning" : "default");

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
          <Typography variant="h6">{tr("settings.connections.title")}</Typography>
          <Button size="small" variant="contained" onClick={() => setMode({ kind: "new" })}>{tr("settings.connections.new")}</Button>
        </Stack>
        <Typography variant="body2" color="text.secondary" mb={2}>{tr("settings.connections.intro")}</Typography>
        {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
        {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}
        {unrouted.length > 0 && (
          <Alert severity="info" sx={{ mb: 2 }}>
            {tr("settings.connections.missing", { count: unrouted.length, list: unrouted.map((p) => purposeLabel(p.purpose)).join(", ") })}
          </Alert>
        )}
        {loading ? <CircularProgress size={24} /> : connections.length === 0 ? (
          <Typography variant="body2" color="text.secondary">{tr("conn.none")}</Typography>
        ) : (
          <Stack spacing={1}>
            {connections.map((c) => (
              <Box key={c.id} sx={{ p: 1.5, borderRadius: 2, border: 1, borderColor: "divider", opacity: c.status === "disabled" ? 0.7 : 1 }}>
                <Stack direction={{ xs: "column", md: "row" }} spacing={1} alignItems={{ md: "center" }}>
                  <Box sx={{ flex: 1 }}>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                      <Typography sx={{ fontWeight: 700 }}>{c.name}</Typography>
                      <Chip label={c.provider_code} size="small" variant="outlined" />
                      <Chip label={tr(`conn.status.${c.status}`)} size="small" color={tone(c.status)} />
                    </Stack>
                    <Typography variant="caption" sx={{ display: "block", mt: 0.5 }}>
                      {c.last_tested_at
                        ? `${c.last_test_result?.success ? tr("conn.last_ok") : tr("conn.last_failed")} · ${new Date(c.last_tested_at).toLocaleString()}${c.last_test_result?.error ? ` · ${c.last_test_result.error}` : ""}`
                        : tr("conn.never")}
                    </Typography>
                  </Box>
                  <Stack direction="row" spacing={0.5}>
                    {c.status !== "disabled" && <Button size="small" onClick={() => handleTest(c.id)} disabled={testing === c.id}>{testing === c.id ? tr("conn.testing") : tr("conn.test")}</Button>}
                    <Button size="small" onClick={() => setMode({ kind: "edit", row: c })}>{c.status === "disabled" ? tr("conn.connect_again") : tr("conn.edit")}</Button>
                    {c.status !== "disabled" && <Button size="small" color="error" onClick={() => setDisconnecting(c)}>{tr("conn.disconnect")}</Button>}
                  </Stack>
                </Stack>
              </Box>
            ))}
          </Stack>
        )}
        <ConnectionDialog mode={mode} providers={providers} onClose={() => setMode(null)} onSaved={(id) => { load(); if (id) void handleTest(id); }} />
        <ConfirmDialog
          open={disconnecting !== null}
          title={tr("conn.disconnect_title", { name: disconnecting?.name ?? "" })}
          message={tr("conn.disconnect_body")}
          confirmLabel={tr("conn.disconnect")}
          destructive
          onConfirm={async () => {
            if (!disconnecting) return;
            try { await connectorsApi.deleteConnection(disconnecting.id); setNotice(tr("conn.disconnected")); } catch (err) { setError(extractErrorMessage(err, tr("conn.err"))); }
            setDisconnecting(null); load();
          }}
          onCancel={() => setDisconnecting(null)}
        />
      </CardContent>
    </Card>
  );
}
