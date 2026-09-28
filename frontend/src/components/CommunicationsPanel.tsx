import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import {
  commsApi,
  extractErrorMessage,
  type BrandThemeRow,
  type NotificationRuleRow,
  type OutboundMessageRow,
  type SuppressionRow,
} from "../api/client";
import { t as tr } from "../i18n";
import { apiUrl } from "../api/client";
import { useBootstrap } from "../bootstrap/BootstrapContext";
import LogoUploader from "./branding/LogoUploader";
import EmailTemplates from "./comms/EmailTemplates";

function TemplatesTab() {
  return <EmailTemplates />;
}

// "recruitment.application.received" -> "application received" (no dotted keys on screen).
function plainEvent(key: string): string {
  const parts = key.split(".");
  return (parts.length > 1 ? parts.slice(1) : parts).join(" ").replace(/_/g, " ");
}

function RulesTab() {
  const [rules, setRules] = useState<NotificationRuleRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    commsApi
      .rules()
      .then(setRules)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load rules")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleToggle = async (rule: NotificationRuleRow) => {
    setToggling(rule.id);
    try {
      await commsApi.updateRule(rule.id, { enabled: !rule.enabled });
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to update rule"));
    } finally {
      setToggling(null);
    }
  };

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {loading ? (
        <CircularProgress size={24} />
      ) : rules.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {tr("comms.rules_empty")}
        </Typography>
      ) : (
        <List dense disablePadding>
          {rules.map((r) => (
            <ListItem
              key={r.id}
              divider
              secondaryAction={
                <Button size="small" onClick={() => handleToggle(r)} disabled={toggling === r.id}>
                  {r.enabled ? tr("comms.rule_disable") : tr("comms.rule_enable")}
                </Button>
              }
            >
              <ListItemText
                primary={
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="body2">{r.name}</Typography>
                    <Chip label={r.enabled ? tr("comms.rule_on") : tr("comms.rule_off")} size="small" color={r.enabled ? "success" : "default"} />
                  </Stack>
                }
                secondary={tr("comms.rule_line", { event: plainEvent(r.event_type), template: plainEvent(r.template_key), channels: r.channels.map((c) => (c === "in_app" ? "app" : c)).join(", ") })}
              />
            </ListItem>
          ))}
        </List>
      )}
    </Box>
  );
}

function BrandThemeTab() {
  const [theme, setTheme] = useState<BrandThemeRow | null>(null);
  const [form, setForm] = useState({ name: "Default", primary_color: "", gradient_from: "", gradient_to: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    commsApi
      .brandTheme()
      .then((t) => {
        setTheme(t);
        if (t) setForm({ name: t.name, primary_color: t.primary_color ?? "", gradient_from: t.gradient_from ?? "", gradient_to: t.gradient_to ?? "" });
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load brand theme")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const { reload: reloadBranding, branding } = useBootstrap();
  const [savedMsg, setSavedMsg] = useState(false);
  const handleSave = async () => {
    setSaving(true);
    setSavedMsg(false);
    try {
      await commsApi.upsertBrandTheme(form);
      load();
      reloadBranding(); // Part 17.11: the new colours show straight away
      setSavedMsg(true);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to save brand theme"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <CircularProgress size={24} />;

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      {savedMsg && <Alert severity="success" sx={{ mb: 2 }} role="status" onClose={() => setSavedMsg(false)}>{tr("settings.brand.saved")}</Alert>}
      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{tr("settings.brand.logo_title")}</Typography>
      <Typography variant="body2" color="text.secondary" mb={1.5}>{tr("settings.brand.logo_intro")}</Typography>
      <Box sx={{ mb: 3 }}>
        <LogoUploader currentUrl={apiUrl(branding?.logo_url)} onSaved={() => { reloadBranding(); setSavedMsg(true); }} />
      </Box>
      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{tr("settings.brand.colours_title")}</Typography>
      <Typography variant="body2" color="text.secondary" mb={2}>
        {tr("settings.brand.colours_intro")} {theme ? "" : tr("settings.brand.no_theme")}
      </Typography>
      <Stack spacing={2} maxWidth={360}>
        <TextField size="small" label="Name" value={form.name} onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} />
        <TextField
          size="small"
          label="Primary color"
          placeholder="#2563eb"
          value={form.primary_color}
          onChange={(e) => setForm((prev) => ({ ...prev, primary_color: e.target.value }))}
        />
        <TextField
          size="small"
          label="Gradient from"
          placeholder="#1e293b"
          value={form.gradient_from}
          onChange={(e) => setForm((prev) => ({ ...prev, gradient_from: e.target.value }))}
        />
        <TextField
          size="small"
          label="Gradient to"
          placeholder="#2563eb"
          value={form.gradient_to}
          onChange={(e) => setForm((prev) => ({ ...prev, gradient_to: e.target.value }))}
        />
        <Button variant="contained" onClick={handleSave} disabled={saving} sx={{ alignSelf: "flex-start" }}>
          {saving ? "Saving..." : "Save"}
        </Button>
      </Stack>
    </Box>
  );
}

function MessageLogTab() {
  const [messages, setMessages] = useState<OutboundMessageRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resending, setResending] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    commsApi
      .outbound()
      .then(setMessages)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load message log")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleResend = async (id: string) => {
    setResending(id);
    try {
      await commsApi.resendOutbound(id);
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to resend message"));
    } finally {
      setResending(null);
    }
  };

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {loading ? (
        <CircularProgress size={24} />
      ) : messages.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No messages sent yet.
        </Typography>
      ) : (
        <List dense disablePadding>
          {messages.map((m) => (
            <ListItem
              key={m.id}
              divider
              secondaryAction={
                (m.status === "failed" || m.status === "bounced") && (
                  <Button size="small" onClick={() => handleResend(m.id)} disabled={resending === m.id}>
                    {resending === m.id ? "Resending..." : "Resend"}
                  </Button>
                )
              }
            >
              <ListItemText
                primary={
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="body2">{m.subject || "(no subject)"}</Typography>
                    <Chip
                      label={m.status}
                      size="small"
                      color={m.status === "sent" || m.status === "delivered" ? "success" : m.status === "failed" || m.status === "bounced" ? "error" : "default"}
                    />
                  </Stack>
                }
                secondary={`${m.to_addresses.join(", ")}${m.error ? ` -- ${m.error}` : ""}`}
              />
            </ListItem>
          ))}
        </List>
      )}
    </Box>
  );
}

function SuppressionTab() {
  const [rows, setRows] = useState<SuppressionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    commsApi
      .suppression()
      .then(setRows)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load suppression list")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleRemove = async (address: string) => {
    try {
      await commsApi.removeSuppression(address);
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to remove suppression"));
    }
  };

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {loading ? (
        <CircularProgress size={24} />
      ) : rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No suppressed addresses.
        </Typography>
      ) : (
        <List dense disablePadding>
          {rows.map((r) => (
            <ListItem key={r.address} divider secondaryAction={<Button size="small" onClick={() => handleRemove(r.address)}>Remove</Button>}>
              <ListItemText primary={r.address} secondary={`Reason: ${r.reason}`} />
            </ListItem>
          ))}
        </List>
      )}
    </Box>
  );
}

const TABS = ["templates", "rules", "brand", "log", "suppression"] as const;

/** Part 16.3: `only` shows a single tab (one Settings sub-page) without the tab bar. */
export default function CommunicationsPanel({ only }: { only?: (typeof TABS)[number] } = {}) {
  const [picked, setTab] = useState<(typeof TABS)[number]>(only ?? "templates");
  // Part 18.22: `only` always wins -- Settings pages that reuse this panel used to keep the first page's tab
  const tab = only ?? picked;

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" mb={1}>
          {tr("settings.comms.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          {tr("settings.comms.intro")}
        </Typography>
        {!only && (<Tabs value={tab} onChange={(_e, value) => setTab(value)} sx={{ mb: 2 }}>
          {TABS.map((t) => (
            <Tab key={t} label={tr(`comms.tab.${t}`)} value={t} />
          ))}
        </Tabs>)}
        {tab === "templates" && <TemplatesTab />}
        {tab === "rules" && <RulesTab />}
        {tab === "brand" && <BrandThemeTab />}
        {tab === "log" && <MessageLogTab />}
        {tab === "suppression" && <SuppressionTab />}
      </CardContent>
    </Card>
  );
}
