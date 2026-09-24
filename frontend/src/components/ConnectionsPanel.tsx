import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { connectorsApi, extractErrorMessage, type ConnectionRow, type ProviderCatalogEntry, type PurposeStatus } from "../api/client";

// Part 3 (docs/HRMS_COMPLETE_SPEC.txt section 7's UI, scoped down): a connections list +
// a create dialog (provider picker -> plain key/value config & secret fields -> Test ->
// Save) + an unrouted-purposes warning strip. Deliberately NOT the full spec vision (a
// drag-to-reorder routing matrix with a JSONLogic condition builder, a health dashboard
// with 24h attempt/latency charts) -- see docs/build_log.md's own Part 3 note.

function CreateConnectionDialog({ open, onClose, providers, onCreated, onError }: {
  open: boolean;
  onClose: () => void;
  providers: ProviderCatalogEntry[];
  onCreated: () => void;
  onError: (message: string) => void;
}) {
  const implemented = providers.filter((p) => p.implemented);
  const [providerCode, setProviderCode] = useState(implemented[0]?.code ?? "");
  const [name, setName] = useState("");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const selected = providers.find((p) => p.code === providerCode);
  const configFields = Object.keys((selected?.config_schema.properties as Record<string, unknown>) ?? {});

  const handleCreate = async () => {
    setSaving(true);
    try {
      await connectorsApi.createConnection({ name, provider_code: providerCode, config, secrets });
      onCreated();
      onClose();
    } catch (err) {
      onError(extractErrorMessage(err, "Failed to create connection"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>New Connection</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          <Select size="small" value={providerCode} onChange={(e) => setProviderCode(e.target.value)}>
            {implemented.map((p) => (
              <MenuItem key={p.code} value={p.code}>
                {p.code} ({p.capabilities.join(", ")})
              </MenuItem>
            ))}
          </Select>
          <TextField size="small" label="Name" value={name} onChange={(e) => setName(e.target.value)} />
          {configFields.map((field) => (
            <TextField
              key={field}
              size="small"
              label={field}
              value={config[field] ?? ""}
              onChange={(e) => setConfig((prev) => ({ ...prev, [field]: e.target.value }))}
            />
          ))}
          {(selected?.secret_fields ?? []).map((field) => (
            <TextField
              key={field}
              size="small"
              type="password"
              label={field}
              value={secrets[field] ?? ""}
              onChange={(e) => setSecrets((prev) => ({ ...prev, [field]: e.target.value }))}
            />
          ))}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleCreate} disabled={saving || !name || !providerCode}>
          Create
        </Button>
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
  const [dialogOpen, setDialogOpen] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([connectorsApi.connections(), connectorsApi.providers(), connectorsApi.purposes()])
      .then(([conns, provs, purps]) => {
        setConnections(conns);
        setProviders(provs);
        setPurposes(purps);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load connections")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      await connectorsApi.testConnection(id);
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Test connection failed"));
    } finally {
      setTesting(null);
    }
  };

  const unrouted = purposes.filter((p) => !p.routed);

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
          <Typography variant="h6">Connections</Typography>
          <Button size="small" variant="contained" onClick={() => setDialogOpen(true)}>
            New Connection
          </Button>
        </Stack>
        <Typography variant="body2" color="text.secondary" mb={2}>
          Every external system (mailbox, AI model, ...) this tenant uses, with encrypted
          credentials and purpose-based routing (Part 3's Connections Framework).
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {unrouted.length > 0 && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            {unrouted.length} purpose(s) have no connection routed: {unrouted.map((p) => p.purpose).join(", ")}
          </Alert>
        )}

        {loading ? (
          <CircularProgress size={24} />
        ) : connections.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No connections yet.
          </Typography>
        ) : (
          <List dense disablePadding>
            {connections.map((c) => (
              <ListItem
                key={c.id}
                divider
                secondaryAction={
                  <Button size="small" onClick={() => handleTest(c.id)} disabled={testing === c.id}>
                    {testing === c.id ? "Testing..." : "Test"}
                  </Button>
                }
              >
                <ListItemText
                  primary={
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Typography variant="body2">{c.name}</Typography>
                      <Chip label={c.provider_code} size="small" variant="outlined" />
                      <Chip
                        label={c.status}
                        size="small"
                        color={c.status === "active" ? "success" : c.status === "error" ? "error" : "default"}
                      />
                    </Stack>
                  }
                  secondary={c.last_test_result?.error ?? (c.last_tested_at ? `Last tested ${new Date(c.last_tested_at).toLocaleString()}` : "Never tested")}
                />
              </ListItem>
            ))}
          </List>
        )}

        <CreateConnectionDialog open={dialogOpen} onClose={() => setDialogOpen(false)} providers={providers} onCreated={load} onError={setError} />
      </CardContent>
    </Card>
  );
}
