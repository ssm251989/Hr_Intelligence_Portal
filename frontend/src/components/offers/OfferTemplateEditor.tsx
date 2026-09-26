import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { offersExtraApi } from "../../api/offersExtra";
import { useT } from "../../i18n";
import { Emoji, FriendlyError, InfoTip, StatusChip } from "../../ui-kit";

// L-B6: offer letter template editor with a LIVE preview -- editor on the left, the
// rendered letter on the right. The preview uses the server's own safe letter renderer
// (debounced while typing); if that can't be reached it fills the blanks here instead.
// The preview is shown inside a sandboxed frame (no scripts), so pasted markup is harmless.

const FIELDS = ["candidate_name", "job_title", "salary", "start_date", "reporting_manager", "expiry_date", "org.display_name"];

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}

function renderLocally(tpl: string, sample: Record<string, string>): string {
  return tpl.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (m, name: string) => (name in sample ? escapeHtml(sample[name]) : `<mark>${escapeHtml(m)}</mark>`));
}

export default function OfferTemplateEditor({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const theme = useTheme();
  const f = theme.palette.fresh;
  const small = useMediaQuery(theme.breakpoints.down("md"));
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [text, setText] = useState("");
  const [sample, setSample] = useState<Record<string, string>>({});
  const [meta, setMeta] = useState<{ version: number; status: string } | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [preview, setPreview] = useState("");
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = () => {
    setLoadError(null);
    offersExtraApi
      .template()
      .then((tpl) => {
        setText(tpl.html_tpl);
        setSample({ ...tpl.sample_context, "org.display_name": tpl.sample_context["org.display_name"] ?? t("offers.editor.sample_company") });
        setMeta({ version: tpl.version, status: tpl.status });
      })
      .catch(setLoadError);
  };

  useEffect(() => {
    if (open) {
      setSaved(false);
      setSaveError(null);
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Debounced live preview.
  useEffect(() => {
    if (!open || !text) return;
    const handle = window.setTimeout(() => {
      offersExtraApi
        .previewTemplate(text)
        .then((r) => {
          setOffline(false);
          if (r.error) setPreviewError(r.error);
          else {
            setPreviewError(null);
            setPreview(r.html ?? "");
          }
        })
        .catch(() => {
          setOffline(true);
          setPreviewError(null);
          setPreview(renderLocally(text, sample));
        });
    }, 450);
    return () => window.clearTimeout(handle);
  }, [text, open, sample]);

  const insert = (field: string) => {
    const token = `{{ ${field} }}`;
    const el = inputRef.current;
    if (!el) {
      setText((prev) => prev + token);
      return;
    }
    const start = el.selectionStart ?? text.length;
    const end = el.selectionEnd ?? text.length;
    const next = text.slice(0, start) + token + text.slice(end);
    setText(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const r = await offersExtraApi.saveTemplate(text, true);
      setMeta({ version: r.version, status: r.status });
      setSaved(true);
    } catch (err) {
      setSaveError(extractErrorMessage(err, t("offers.editor.save_failed")));
    } finally {
      setSaving(false);
    }
  };

  const doc = `<!doctype html><html><head><meta charset="utf-8"><style>
    body{font-family:${theme.typography.fontFamily};color:${f.ink};background:${f.surface};margin:0;padding:24px 28px;line-height:1.6;font-size:14px}
    mark{background:${f.sunSoft};color:${f.sunInk};border-radius:4px;padding:0 2px}
  </style></head><body>${preview}</body></html>`;

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="lg" fullScreen={small} aria-labelledby="offer-template-title">
      <DialogTitle id="offer-template-title" sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <Emoji name="memo" size={22} />
        {t("offers.editor.title")}
        {meta && (
          <Box sx={{ ml: "auto" }}>
            <StatusChip
              status={meta.status === "published" ? "active" : meta.status === "default" ? "new" : "draft"}
              label={meta.status === "default" ? t("offers.editor.starter") : t("offers.editor.version", { n: meta.version })}
            />
          </Box>
        )}
      </DialogTitle>
      <DialogContent dividers>
        {loadError ? (
          <FriendlyError error={loadError} onRetry={load} compact />
        ) : (
          <>
            <Typography sx={{ color: f.muted, mb: 2, fontSize: 14 }}>{t("offers.editor.intro")}</Typography>
            <Grid container spacing={2.5}>
              <Grid size={{ xs: 12, md: 6 }}>
                <Typography component="h3" sx={{ fontWeight: 700, mb: 1, display: "flex", alignItems: "center" }}>
                  {t("offers.editor.left")}
                  <InfoTip text={t("offers.editor.fields_tip")} />
                </Typography>
                <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }} aria-label={t("offers.editor.insert")}>
                  {FIELDS.map((field) => (
                    <Chip key={field} size="small" variant="outlined" label={`＋ ${t(`offers.editor.field.${field}`)}`} onClick={() => insert(field)} aria-label={t("offers.editor.insert_field", { field: t(`offers.editor.field.${field}`) })} />
                  ))}
                </Stack>
                <TextField
                  inputRef={inputRef}
                  value={text}
                  onChange={(e) => {
                    setText(e.target.value);
                    setSaved(false);
                  }}
                  multiline
                  minRows={16}
                  maxRows={28}
                  fullWidth
                  label={t("offers.editor.text_label")}
                  InputProps={{ sx: { fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace", fontSize: 13 } }}
                />
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <Typography component="h3" sx={{ fontWeight: 700, mb: 1 }}>{t("offers.editor.right")}</Typography>
                {previewError && (
                  <Alert severity="warning" sx={{ mb: 1 }}>
                    {t("offers.editor.preview_error", { error: previewError })}
                  </Alert>
                )}
                {offline && (
                  <Typography sx={{ fontSize: 12, color: f.muted, mb: 1 }}>{t("offers.editor.offline")}</Typography>
                )}
                <Box sx={{ borderRadius: "12px", border: `1px solid ${f.line}`, overflow: "hidden", boxShadow: f.shadow, bgcolor: f.surface }}>
                  <Box
                    component="iframe"
                    title={t("offers.editor.right")}
                    sandbox=""
                    srcDoc={doc}
                    sx={{ width: "100%", height: { xs: 360, md: 480 }, border: 0, display: "block" }}
                  />
                </Box>
              </Grid>
            </Grid>
            {saveError && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {saveError}
              </Alert>
            )}
            {saved && (
              <Alert severity="success" sx={{ mt: 2 }}>
                {t("offers.editor.saved")}
              </Alert>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.close")}</Button>
        <Button variant="contained" onClick={save} disabled={saving || !text || Boolean(loadError)}>
          {saving ? t("offers.editor.saving") : t("offers.editor.save")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
