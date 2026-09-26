import { useEffect, useMemo, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { commsApi, extractErrorMessage, http, type MessageTemplateRow } from "../../api/client";
import { useT } from "../../i18n";
import { EmptyState, Emoji, InfoTip, StatusChip } from "../../ui-kit";

// Part 16.2: email templates in plain words. The list shows a friendly name + who gets it and
// when; the key is only under "Advanced". In the editor, placeholders read «Job title» (never
// {{ job_title }}) and are inserted from a picker that shows a sample value; the preview fills
// them with those samples.

interface Catalog {
  templates: Record<string, { name: string; description: string }>;
  variables: { key: string; name: string; sample: string }[];
}

const CHANNEL_EMOJI: Record<string, string> = { email: "mail", in_app: "bell", sms: "speech", whatsapp: "speech" };

function humanise(key: string): string {
  const last = key.split(".").pop() ?? key;
  const words = last.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** {{ job_title }} -> «Job title» (and back). Unknown keys become «Job title» from their key. */
export function toFriendly(text: string, vars: Catalog["variables"]): string {
  return text.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_m, key: string) => `«${vars.find((v) => v.key === key)?.name ?? humanise(key)}»`);
}
export function fromFriendly(text: string, vars: Catalog["variables"]): string {
  return text.replace(/«([^»]+)»/g, (m, name: string) => {
    const hit = vars.find((v) => v.name.toLowerCase() === name.trim().toLowerCase());
    return hit ? `{{ ${hit.key} }}` : m;
  });
}
function fillSamples(text: string, vars: Catalog["variables"]): string {
  return text.replace(/«([^»]+)»/g, (_m, name: string) => vars.find((v) => v.name.toLowerCase() === name.trim().toLowerCase())?.sample ?? name);
}

function TemplateEditor({ template, catalog, onClose, onSaved }: {
  template: MessageTemplateRow; catalog: Catalog; onClose: () => void; onSaved: () => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const vars = catalog.variables;
  const [subject, setSubject] = useState(() => toFriendly(template.subject_tpl ?? "", vars));
  const [body, setBody] = useState(() => toFriendly(template.html_tpl ?? template.text_tpl ?? "", vars));
  const [focus, setFocus] = useState<"subject" | "body">("body");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const subjectRef = useRef<HTMLInputElement>(null);
  const info = catalog.templates[template.key] ?? { name: humanise(template.key), description: "" };

  const insert = (name: string) => {
    const token = `«${name}»`;
    const el = focus === "subject" ? subjectRef.current : bodyRef.current;
    const value = focus === "subject" ? subject : body;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    const next = value.slice(0, start) + token + value.slice(end);
    (focus === "subject" ? setSubject : setBody)(next);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const save = async (publishToo: boolean) => {
    setSaving(true);
    setError(null);
    try {
      const html = fromFriendly(body, vars);
      const draft = await commsApi.createTemplateDraft({
        key: template.key, channel: template.channel, locale: template.locale,
        subject_tpl: fromFriendly(subject, vars), html_tpl: template.html_tpl !== null ? html : undefined,
        text_tpl: template.html_tpl === null ? html : template.text_tpl ?? undefined,
        variables_schema: template.variables_schema_json,
      });
      if (publishToo) await commsApi.publishTemplate(draft.id);
      onSaved();
    } catch (err) {
      setError(extractErrorMessage(err, t("comms.save_failed")));
    } finally {
      setSaving(false);
    }
  };

  const previewHtml = useMemo(() => {
    const filled = fillSamples(body, vars);
    return template.html_tpl !== null ? filled : `<pre style="font:inherit;white-space:pre-wrap">${filled.replace(/</g, "&lt;")}</pre>`;
  }, [body, vars, template.html_tpl]);

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="lg" aria-labelledby="tpl-editor-title">
      <DialogTitle id="tpl-editor-title">
        {info.name}
        {info.description && <Typography sx={{ color: f.muted, fontSize: 14 }}>{info.description}</Typography>}
      </DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <Box sx={{ display: "grid", gap: 2.5, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" } }}>
          <Stack spacing={2}>
            <TextField label={t("comms.subject")} value={subject} onChange={(e) => setSubject(e.target.value)} onFocus={() => setFocus("subject")}
              inputRef={subjectRef} fullWidth placeholder={t("comms.subject_example")} helperText={t("comms.subject_hint")} />
            <TextField label={t("comms.body")} value={body} onChange={(e) => setBody(e.target.value)} onFocus={() => setFocus("body")}
              inputRef={bodyRef} fullWidth multiline minRows={12} placeholder={t("comms.body_example")} helperText={t("comms.body_hint")} />
            <Box>
              <Stack direction="row" alignItems="center" spacing={0.5} sx={{ mb: 1 }}>
                <Typography sx={{ fontWeight: 700, fontSize: 14 }}>{t("comms.insert")}</Typography>
                <InfoTip text={t("comms.insert_info")} />
              </Stack>
              <Stack direction="row" flexWrap="wrap" gap={1}>
                {vars.map((v) => (
                  <Chip key={v.key} onClick={() => insert(v.name)} label={<span><b>{v.name}</b> → {v.sample}</span>}
                    variant="outlined" sx={{ maxWidth: "100%" }} />
                ))}
              </Stack>
            </Box>
          </Stack>
          <Box>
            <Typography sx={{ fontWeight: 700, fontSize: 14, mb: 1 }}>{t("comms.preview")}</Typography>
            <Box sx={{ border: `1px solid ${f.line}`, borderRadius: "14px", overflow: "hidden", bgcolor: f.surface }}>
              <Box sx={{ px: 2, py: 1.25, borderBottom: `1px solid ${f.line}`, bgcolor: f.surface2 }}>
                <Typography variant="caption" component="div">{t("comms.subject")}</Typography>
                <Typography sx={{ fontWeight: 700 }}>{fillSamples(subject, vars) || "—"}</Typography>
              </Box>
              {/* Sandboxed: the template's HTML never runs inside the app. */}
              <Box component="iframe" title={t("comms.preview")} sandbox="" srcDoc={previewHtml}
                sx={{ width: "100%", height: 420, border: 0, bgcolor: "common.white", display: "block" }} />
            </Box>
            <Typography variant="caption" component="div" sx={{ mt: 1 }}>{t("comms.preview_hint")}</Typography>
          </Box>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="outlined" disabled={saving} onClick={() => save(false)}>{t("comms.save_draft")}</Button>
        <Button variant="contained" disabled={saving} onClick={() => save(true)}>{t("comms.save_publish")}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function EmailTemplates() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [templates, setTemplates] = useState<MessageTemplateRow[] | null>(null);
  const [catalog, setCatalog] = useState<Catalog>({ templates: {}, variables: [] });
  const [advanced, setAdvanced] = useState(false);
  const [editing, setEditing] = useState<MessageTemplateRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    commsApi.templates().then(setTemplates).catch((err) => {
      setTemplates([]);
      setError(extractErrorMessage(err, t("comms.load_failed")));
    });
  };
  useEffect(() => {
    load();
    http.get<Catalog>("/api/v1/comms/template-catalog").then(setCatalog).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // One row per template (its newest version), friendly name order.
  const rows = useMemo(() => {
    const latest = new Map<string, MessageTemplateRow>();
    for (const tpl of templates ?? []) {
      const k = `${tpl.key}|${tpl.channel}|${tpl.locale}`;
      const cur = latest.get(k);
      if (!cur || tpl.version > cur.version) latest.set(k, tpl);
    }
    const name = (tpl: MessageTemplateRow) => catalog.templates[tpl.key]?.name ?? humanise(tpl.key);
    return [...latest.values()].sort((a, b) => name(a).localeCompare(name(b)));
  }, [templates, catalog]);

  return (
    <Box>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
        <Typography sx={{ color: f.muted }}>{t("comms.list_intro")}</Typography>
        <FormControlLabel control={<Switch checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />} label={t("comms.advanced")} />
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {templates === null ? (
        <Stack spacing={1}>{[0, 1, 2].map((i) => <Skeleton key={i} variant="rounded" height={56} />)}</Stack>
      ) : rows.length === 0 ? (
        <EmptyState compact illustration="empty-mailbox" title={t("comms.empty")} />
      ) : (
        <Stack spacing={1}>
          {rows.map((tpl) => {
            const info = catalog.templates[tpl.key] ?? { name: humanise(tpl.key), description: "" };
            return (
              <Stack key={tpl.id} direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}
                sx={{ p: "12px 14px", borderRadius: "12px", border: `1px solid ${f.line}`, bgcolor: f.surface2 }}>
                <Emoji name={CHANNEL_EMOJI[tpl.channel] ?? "mail"} size={22} label={tpl.channel} />
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography sx={{ fontWeight: 700 }}>{info.name}</Typography>
                  {info.description && <Typography sx={{ color: f.muted, fontSize: 13 }}>{info.description}</Typography>}
                  {advanced && <Typography variant="caption" component="div" sx={{ fontFamily: "monospace" }}>{tpl.key} · v{tpl.version} · {tpl.locale}</Typography>}
                </Box>
                {tpl.status === "published" ? <StatusChip status="done" label={t("comms.live")} /> : <StatusChip status="draft" label={t("comms.draft")} />}
                <Button size="small" variant="outlined" onClick={() => setEditing(tpl)}>{t("comms.edit")}</Button>
                {tpl.status !== "published" && (
                  <Button size="small" variant="contained" onClick={() => commsApi.publishTemplate(tpl.id).then(load).catch((err) => setError(extractErrorMessage(err, t("comms.save_failed"))))}>
                    {t("comms.publish")}
                  </Button>
                )}
              </Stack>
            );
          })}
        </Stack>
      )}
      {editing && <TemplateEditor template={editing} catalog={catalog} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
    </Box>
  );
}
