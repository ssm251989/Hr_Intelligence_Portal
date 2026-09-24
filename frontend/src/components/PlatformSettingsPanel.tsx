import { useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
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

import { extractErrorMessage, platformSettingsApi, type SettingDefinition, type SettingHistoryEntry, type SettingValueRow } from "../api/client";

// Part 2 (docs/HRMS_COMPLETE_SPEC.txt section 4's UI) + section L/A1-A3 (client decision,
// added to the spec after this Part started -- WINS over Part 14's own UI wording):
// "Settings: category tree + search" (A1, here: module/group sections + the search box
// below -- a flat grouped list rather than a collapsible nested tree, since there's no
// deep hierarchy yet with only 3 modules/~10 groups registered), "change history with
// revert" (A2, the History dialog's own Revert button), "setup health checklist on admin
// home" (A3 -- out of scope here, belongs on the admin home page a later part builds).
// Deliberately NOT the full spec-section-4 vision (auto-rendered json_schema forms via
// @rjsf/mui, a scope switcher across every SCOPE_ORDER level, "inherited from X" badges) --
// every currently-registered setting is a plain str/int/decimal/bool/enum/json value with
// no nested schema, and only the tenant scope has real data yet (no positions/departments/
// locations exist before Part 7's Core HR) -- see docs/build_log.md's own note on this.

function valueToEditString(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function parseEditValue(raw: string, type: string): unknown {
  if (type === "int") return parseInt(raw, 10);
  if (type === "decimal") return parseFloat(raw);
  if (type === "bool") return raw === "true";
  if (type === "str" || type === "enum" || type === "color" || type === "email" || type === "url") return raw;
  return JSON.parse(raw); // json, duration, time, and everything else: raw JSON text
}

function SettingRow({
  def,
  row,
  onSaved,
  onError,
}: {
  def: SettingDefinition;
  row: SettingValueRow | undefined;
  onSaved: () => void;
  onError: (message: string) => void;
}) {
  const currentValue = row ? row.value : def.default;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => valueToEditString(currentValue));
  const [saving, setSaving] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<SettingHistoryEntry[] | null>(null);

  const isDefault = row === undefined;
  const [reverting, setReverting] = useState<number | null>(null);

  const handleSave = async () => {
    setSaving(true);
    try {
      const parsed = parseEditValue(draft, def.type);
      await platformSettingsApi.update(def.key, parsed);
      setEditing(false);
      onSaved();
    } catch (err) {
      onError(extractErrorMessage(err, `Failed to update ${def.key}`));
    } finally {
      setSaving(false);
    }
  };

  const openHistory = async () => {
    setHistoryOpen(true);
    try {
      setHistory(await platformSettingsApi.history(def.key));
    } catch (err) {
      onError(extractErrorMessage(err, `Failed to load history for ${def.key}`));
    }
  };

  const handleRevert = async (entry: SettingHistoryEntry) => {
    setReverting(entry.version);
    try {
      await platformSettingsApi.update(def.key, entry.value);
      setHistory(await platformSettingsApi.history(def.key));
      onSaved();
    } catch (err) {
      onError(extractErrorMessage(err, `Failed to revert ${def.key}`));
    } finally {
      setReverting(null);
    }
  };

  return (
    <ListItem
      divider
      secondaryAction={
        !editing && (
          <Stack direction="row" spacing={1}>
            <Button size="small" onClick={() => setEditing(true)}>
              Edit
            </Button>
            <Button size="small" onClick={openHistory}>
              History
            </Button>
          </Stack>
        )
      }
    >
      <ListItemText
        primary={
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" fontFamily="monospace">
              {def.key}
            </Typography>
            {isDefault && <Chip label="platform default" size="small" variant="outlined" />}
          </Stack>
        }
        secondary={
          editing ? (
            <Stack direction="row" spacing={1} alignItems="center" mt={1}>
              {def.type === "bool" ? (
                <Select size="small" value={draft} onChange={(e) => setDraft(e.target.value)}>
                  <MenuItem value="true">true</MenuItem>
                  <MenuItem value="false">false</MenuItem>
                </Select>
              ) : (
                <TextField size="small" value={draft} onChange={(e) => setDraft(e.target.value)} sx={{ minWidth: 260 }} />
              )}
              <Button size="small" variant="contained" onClick={handleSave} disabled={saving}>
                Save
              </Button>
              <Button size="small" onClick={() => setEditing(false)} disabled={saving}>
                Cancel
              </Button>
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary" component="span">
              {valueToEditString(currentValue) || "(empty)"}
            </Typography>
          )
        }
      />
      <Dialog open={historyOpen} onClose={() => setHistoryOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{def.key} -- history</DialogTitle>
        <DialogContent>
          {history === null ? (
            <CircularProgress size={20} />
          ) : history.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No changes recorded yet.
            </Typography>
          ) : (
            <List dense>
              {history.map((entry, i) => (
                <ListItem
                  key={i}
                  divider
                  secondaryAction={
                    i > 0 && (
                      <Button size="small" onClick={() => handleRevert(entry)} disabled={reverting !== null}>
                        {reverting === entry.version ? "Reverting..." : "Revert to this"}
                      </Button>
                    )
                  }
                >
                  <ListItemText
                    primary={valueToEditString(entry.value)}
                    secondary={`v${entry.version} -- ${entry.updated_by ?? "unknown"} -- ${entry.updated_at ? new Date(entry.updated_at).toLocaleString() : ""}${i === 0 ? " (current)" : ""}`}
                  />
                </ListItem>
              ))}
            </List>
          )}
        </DialogContent>
      </Dialog>
    </ListItem>
  );
}

export default function PlatformSettingsPanel() {
  const [definitions, setDefinitions] = useState<SettingDefinition[] | null>(null);
  const [values, setValues] = useState<SettingValueRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  const load = () => {
    setLoading(true);
    Promise.all([platformSettingsApi.definitions(), platformSettingsApi.values()])
      .then(([defs, vals]) => {
        setDefinitions(defs);
        setValues(vals);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load platform settings")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const valuesByKey = useMemo(() => new Map(values.map((v) => [v.key, v])), [values]);

  const groups = useMemo(() => {
    if (!definitions) return [];
    const needle = search.trim().toLowerCase();
    const filtered = needle
      ? definitions.filter(
          (def) =>
            def.key.toLowerCase().includes(needle) ||
            def.module.toLowerCase().includes(needle) ||
            def.group.toLowerCase().includes(needle),
        )
      : definitions;
    const byGroup = new Map<string, SettingDefinition[]>();
    for (const def of filtered) {
      const label = `${def.module} / ${def.group || "General"}`;
      if (!byGroup.has(label)) byGroup.set(label, []);
      byGroup.get(label)!.push(def);
    }
    return Array.from(byGroup.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [definitions, search]);

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Platform Settings
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          Tenant-wide configuration values (Part 2's Settings Registry). "platform default"
          means nothing has been set for this tenant yet -- editing writes a tenant-scoped
          override.
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        <TextField
          size="small"
          placeholder="Search settings by key, module, or group"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ mb: 2, minWidth: 320 }}
        />

        {loading ? (
          <CircularProgress size={24} />
        ) : groups.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No settings match "{search}".
          </Typography>
        ) : (
          <Stack spacing={3}>
            {groups.map(([label, defs]) => (
              <Box key={label}>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  {label}
                </Typography>
                <List dense disablePadding>
                  {defs.map((def) => (
                    <SettingRow key={def.key} def={def} row={valuesByKey.get(def.key)} onSaved={load} onError={setError} />
                  ))}
                </List>
              </Box>
            ))}
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
