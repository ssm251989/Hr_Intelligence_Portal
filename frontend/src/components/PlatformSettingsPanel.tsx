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
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, platformSettingsApi, type SettingDefinition, type SettingHistoryEntry, type SettingValueRow } from "../api/client";
import { t as tr } from "../i18n";
import { useBootstrap } from "../bootstrap/BootstrapContext";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import { formatDateTime } from "../utils/datetime";
import { parseEditValue, valueToEditString } from "../utils/settingValue";

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


function SettingRow({
  showKey,
  def,
  row,
  onSaved,
  onError,
}: {
  def: SettingDefinition;
  row: SettingValueRow | undefined;
  onSaved: () => void;
  onError: (message: string) => void;
  showKey?: boolean;
}) {
  const currentValue = row ? row.value : def.default;
  const name = def.help || friendlyName(def.key);
  // bool values read Yes / No in the app's language (the stored value stays true / false)
  const shown = (value: unknown) => (def.type === "bool" && typeof value === "boolean" ? tr(value ? "settings.yes" : "settings.no") : valueToEditString(value));
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => valueToEditString(currentValue));
  const [saving, setSaving] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<SettingHistoryEntry[] | null>(null);

  const isDefault = row === undefined || row.is_default === true;
  const [reverting, setReverting] = useState<number | null>(null);

  // Always start editing from the value currently shown (after a save, a revert or a cancel
  // the draft from an earlier edit is stale).
  const startEditing = () => {
    setDraft(valueToEditString(currentValue));
    setEditing(true);
  };

  const handleSave = async () => {
    let parsed: unknown;
    try {
      parsed = parseEditValue(draft, def.type, def.default); // an empty JSON box = the built-in default
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
      return;
    }
    setSaving(true);
    try {
      await platformSettingsApi.update(def.key, parsed);
      setEditing(false);
      onSaved();
    } catch (err) {
      onError(extractErrorMessage(err, tr("settings.failed_update", { name })));
    } finally {
      setSaving(false);
    }
  };

  const openHistory = async () => {
    setHistoryOpen(true);
    try {
      setHistory(await platformSettingsApi.history(def.key));
    } catch (err) {
      onError(extractErrorMessage(err, tr("settings.failed_history", { name })));
    }
  };

  const handleRevert = async (entry: SettingHistoryEntry) => {
    setReverting(entry.version);
    try {
      // The backend's revert route records "(revert to vN)" in the history.
      await platformSettingsApi.revert(def.key, entry.version);
      setHistory(await platformSettingsApi.history(def.key));
      onSaved();
    } catch (err) {
      onError(extractErrorMessage(err, tr("settings.failed_revert", { name })));
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
            <Button size="small" onClick={startEditing}>
              {tr("settings.edit")}
            </Button>
            <Button size="small" onClick={openHistory}>
              {tr("settings.history")}
            </Button>
          </Stack>
        )
      }
    >
      <ListItemText
        primary={
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            {/* Part 16.2: the plain sentence is the name; the key only shows under "Advanced". */}
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              {def.help || friendlyName(def.key)}
            </Typography>
            {isDefault && <Chip label={tr("settings.default_chip")} size="small" variant="outlined" />}
            {showKey && <Typography variant="caption" fontFamily="monospace" color="text.secondary">{def.key}</Typography>}
          </Stack>
        }
        // Part 14 section 11: plain-language help + what the setting affects, always visible.
        primaryTypographyProps={{ component: "div" }}
        secondary={
          !editing && def.affects ? (
            <Typography variant="caption" color="text.secondary" component="span">
              {tr("settings.affects", { what: def.affects })}
            </Typography>
          ) : editing ? (
            <Stack direction="row" spacing={1} alignItems="center" mt={1}>
              {def.type === "bool" ? (
                <Select size="small" value={draft} onChange={(e) => setDraft(e.target.value)}>
                  <MenuItem value="true">{tr("settings.yes")}</MenuItem>
                  <MenuItem value="false">{tr("settings.no")}</MenuItem>
                </Select>
              ) : (
                <TextField size="small" value={draft} onChange={(e) => setDraft(e.target.value)} sx={{ minWidth: 260 }} />
              )}
              <Button size="small" variant="contained" onClick={handleSave} disabled={saving}>
                {tr("action.save")}
              </Button>
              <Button size="small" onClick={() => setEditing(false)} disabled={saving}>
                {tr("action.cancel")}
              </Button>
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary" component="span">
              {shown(currentValue) || tr("settings.empty")}
            </Typography>
          )
        }
      />
      <Dialog open={historyOpen} onClose={() => setHistoryOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{tr("settings.history_title", { name })}</DialogTitle>
        <DialogContent>
          {history === null ? (
            <CircularProgress size={20} />
          ) : history.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {tr("settings.no_history")}
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
                        {reverting === entry.version ? tr("settings.reverting") : tr("settings.revert_to_this")}
                      </Button>
                    )
                  }
                >
                  <ListItemText
                    primary={shown(entry.value) || tr("settings.empty")}
                    secondary={`v${entry.version} - ${entry.updated_by ?? tr("settings.unknown")} - ${entry.updated_at ? formatDateTime(entry.updated_at) : ""}${i === 0 ? ` ${tr("settings.current")}` : ""}`}
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

// "iam.auth.password_min_length" -> "Password min length" (only when no help text exists).
function friendlyName(key: string): string {
  const last = (key.split(".").pop() ?? key).replace(/_/g, " ");
  return last.charAt(0).toUpperCase() + last.slice(1);
}

/** Part 16.3: `prefixes` limits the list to one area's settings (e.g. ["iam.auth."]); no prefixes = everything. */
export default function PlatformSettingsPanel({ prefixes, title, intro }: { prefixes?: string[]; title?: string; intro?: string } = {}) {
  const [showKeys, setShowKeys] = useState(false);
  const [definitions, setDefinitions] = useState<SettingDefinition[] | null>(null);
  const [values, setValues] = useState<SettingValueRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  // Part 17.11: after a save -> a clear success message, and the app picks the change up at
  // once (company name / colours / modules in the menu, sign-in page, careers site).
  const [saved, setSaved] = useState<string | null>(null);
  const { reload: reloadBranding } = useBootstrap();
  const { reload: reloadMe } = useMeBootstrap();
  const afterSave = (label: string) => {
    load();
    setSaved(label);
    reloadBranding();
    reloadMe();
  };

  const load = () => {
    setLoading(true);
    Promise.all([platformSettingsApi.definitions(), platformSettingsApi.values()])
      .then(([defs, vals]) => {
        setDefinitions(defs);
        setValues(vals);
      })
      .catch((err) => setError(extractErrorMessage(err, tr("settings.failed_load"))))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const valuesByKey = useMemo(() => new Map(values.map((v) => [v.key, v])), [values]);

  const groups = useMemo(() => {
    if (!definitions) return [];
    const needle = search.trim().toLowerCase();
    const scoped = prefixes?.length ? definitions.filter((def) => prefixes.some((p) => def.key.startsWith(p))) : definitions;
    const filtered = needle
      ? scoped.filter(
          (def) =>
            (def.help ?? "").toLowerCase().includes(needle) ||
            (def.affects ?? "").toLowerCase().includes(needle) ||
            def.key.toLowerCase().includes(needle) ||
            def.group.toLowerCase().includes(needle),
        )
      : scoped;
    const byGroup = new Map<string, SettingDefinition[]>();
    for (const def of filtered) {
      const label = def.group || tr("settings.group_general");
      if (!byGroup.has(label)) byGroup.set(label, []);
      byGroup.get(label)!.push(def);
    }
    return Array.from(byGroup.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [definitions, search, prefixes]);

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" gutterBottom>
          {title ?? tr("settings.all.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {intro ?? tr("settings.all.intro")}
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}
        {saved && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(null)} role="status">
            {tr("settings.saved_ok", { name: saved })}
          </Alert>
        )}

        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" sx={{ mb: 2, rowGap: 1 }}>
          <TextField
            size="small"
            placeholder={tr("settings.search_example")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            sx={{ minWidth: 320 }}
          />
          <FormControlLabel control={<Switch checked={showKeys} onChange={(e) => setShowKeys(e.target.checked)} />} label={tr("comms.advanced")} />
        </Stack>

        {/* Part 31.4 proof: only the first load shows the spinner -- a reload after Save / Revert used to unmount every
            row and close the History dialog, so the "(revert to vN)" entry was never seen */}
        {loading && definitions === null ? (
          <CircularProgress size={24} />
        ) : groups.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {tr("settings.no_match", { q: search })}
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
                    <SettingRow key={def.key} def={def} row={valuesByKey.get(def.key)} onSaved={() => afterSave(def.help || friendlyName(def.key))} onError={(m) => { setSaved(null); setError(m); }} showKey={showKeys} />
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
