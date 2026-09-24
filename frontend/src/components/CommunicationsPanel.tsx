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
  type MessageTemplateRow,
  type NotificationRuleRow,
  type OutboundMessageRow,
  type SuppressionRow,
} from "../api/client";

// Part 4 (docs/HRMS_COMPLETE_SPEC.txt section 6's UI, scoped down the same way Part 2's
// PlatformSettingsPanel / Part 3's ConnectionsPanel were): a plain list + publish/preview
// for templates, a read-only rules list with an enable/disable toggle, a single default
// brand theme form, and a message log with resend. Deliberately NOT the full spec vision
// (split-view code/visual template editor with device/dark-mode live preview, a drag-drop
// "when X and Y send Z" rule builder, per-message delivery timelines, diff/versions UI) --
// see docs/build_log.md's own Part 4 note.

function TemplatesTab() {
  const [templates, setTemplates] = useState<MessageTemplateRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState<MessageTemplateRow | null>(null);
  const [previewResult, setPreviewResult] = useState<{ subject: string; html: string; text: string } | null>(null);
  const [publishing, setPublishing] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    commsApi
      .templates()
      .then(setTemplates)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load templates")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handlePublish = async (id: string) => {
    setPublishing(id);
    try {
      await commsApi.publishTemplate(id);
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to publish template"));
    } finally {
      setPublishing(null);
    }
  };

  const openPreview = async (template: MessageTemplateRow) => {
    setPreviewOpen(template);
    setPreviewResult(null);
    try {
      const sample = Object.fromEntries((template.variables_schema_json.required ?? []).map((key) => [key, `[${key}]`]));
      const rendered = await commsApi.previewTemplate(template.id, sample);
      setPreviewResult(rendered);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to render preview"));
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
      ) : templates.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No templates yet.
        </Typography>
      ) : (
        <List dense disablePadding>
          {templates.map((t) => (
            <ListItem
              key={t.id}
              divider
              secondaryAction={
                <Stack direction="row" spacing={1}>
                  <Button size="small" onClick={() => openPreview(t)}>
                    Preview
                  </Button>
                  {t.status === "draft" && (
                    <Button size="small" variant="contained" onClick={() => handlePublish(t.id)} disabled={publishing === t.id}>
                      {publishing === t.id ? "Publishing..." : "Publish"}
                    </Button>
                  )}
                </Stack>
              }
            >
              <ListItemText
                primary={
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="body2">{t.key}</Typography>
                    <Chip label={`v${t.version}`} size="small" variant="outlined" />
                    <Chip label={t.status} size="small" color={t.status === "published" ? "success" : "default"} />
                  </Stack>
                }
                secondary={t.subject_tpl || "(no subject template)"}
              />
            </ListItem>
          ))}
        </List>
      )}

      <Dialog open={previewOpen !== null} onClose={() => setPreviewOpen(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Preview: {previewOpen?.key}</DialogTitle>
        <DialogContent>
          {previewResult === null ? (
            <CircularProgress size={24} />
          ) : (
            <Stack spacing={2}>
              <TextField size="small" label="Subject" value={previewResult.subject} InputProps={{ readOnly: true }} fullWidth />
              <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 2, maxHeight: 400, overflow: "auto" }}>
                <div dangerouslySetInnerHTML={{ __html: previewResult.html }} />
              </Box>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPreviewOpen(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
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
          No notification rules yet.
        </Typography>
      ) : (
        <List dense disablePadding>
          {rules.map((r) => (
            <ListItem
              key={r.id}
              divider
              secondaryAction={
                <Button size="small" onClick={() => handleToggle(r)} disabled={toggling === r.id}>
                  {r.enabled ? "Disable" : "Enable"}
                </Button>
              }
            >
              <ListItemText
                primary={
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="body2">{r.name}</Typography>
                    <Chip label={r.enabled ? "enabled" : "disabled"} size="small" color={r.enabled ? "success" : "default"} />
                  </Stack>
                }
                secondary={`When ${r.event_type} → send ${r.template_key} via ${r.channels.join(", ")}`}
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

  const handleSave = async () => {
    setSaving(true);
    try {
      await commsApi.upsertBrandTheme(form);
      load();
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
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Typography variant="body2" color="text.secondary" mb={2}>
        This is the palette every negotiation/confirmation email and page (interview
        picker, confirm page) renders with. {theme ? "" : "No theme configured yet -- a generic default is used until you save one."}
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

const TABS = ["Templates", "Rules", "Brand theme", "Message log", "Suppression"] as const;

export default function CommunicationsPanel() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Templates");

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" mb={1}>
          Communications
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          Every email template, notification rule, and brand color this tenant uses (Part
          4's Communication Engine) -- no wording, layout, or recipient list is in code.
        </Typography>
        <Tabs value={tab} onChange={(_e, value) => setTab(value)} sx={{ mb: 2 }}>
          {TABS.map((t) => (
            <Tab key={t} label={t} value={t} />
          ))}
        </Tabs>
        {tab === "Templates" && <TemplatesTab />}
        {tab === "Rules" && <RulesTab />}
        {tab === "Brand theme" && <BrandThemeTab />}
        {tab === "Message log" && <MessageLogTab />}
        {tab === "Suppression" && <SuppressionTab />}
      </CardContent>
    </Card>
  );
}
