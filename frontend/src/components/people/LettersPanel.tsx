import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { peopleApi, type LetterRow, type LetterTemplateOption } from "../../api/peopleApi";
import { useT } from "../../i18n";
import { EmptyState, Emoji, FriendlyError, InfoTip } from "../../ui-kit";
import { SectionCard, useFormatDate } from "./shared";

// E5: standard letters are made instantly from the company's published letter templates and
// previewed in a sandboxed frame (no scripts, no same-origin access) so letter HTML can never
// touch the app.

export function LetterPreview({ html, title }: { html: string; title: string }) {
  const f = useTheme().palette.fresh;
  return (
    <Box
      component="iframe"
      title={title}
      sandbox=""
      srcDoc={html}
      referrerPolicy="no-referrer"
      sx={{ width: "100%", height: { xs: 420, md: 620 }, border: `1px solid ${f.line}`, borderRadius: "12px", bgcolor: "common.white", display: "block" }}
    />
  );
}

export default function LettersPanel({ employeeId, canCreate, context }: { employeeId: string; canCreate: boolean; context: Record<string, unknown> }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useFormatDate();
  const [templates, setTemplates] = useState<LetterTemplateOption[] | null>(null);
  const [letters, setLetters] = useState<LetterRow[] | null>(null);
  const [picked, setPicked] = useState("");
  const [preview, setPreview] = useState<{ id: string; key: string; html: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [loadError, setLoadError] = useState<unknown>(null);

  const letterName = (key: string) => {
    const known = t(`people.letter.${key}`);
    return known !== `people.letter.${key}` ? known : templates?.find((x) => x.key === key)?.name ?? t("people.letter.other");
  };

  const load = () => {
    setLoadError(null);
    Promise.all([peopleApi.letterTemplates().catch(() => [] as LetterTemplateOption[]), peopleApi.letters(employeeId)])
      .then(([tpl, rows]) => {
        setTemplates(tpl);
        setLetters(rows);
        setPicked((p) => p || tpl[0]?.key || "");
      })
      .catch(setLoadError);
  };
  useEffect(load, [employeeId]);

  const generate = async () => {
    if (!picked) return;
    setBusy(true);
    setError(null);
    try {
      const res = await peopleApi.generateLetter(employeeId, picked, context);
      setPreview({ id: res.id, key: picked, html: res.rendered_html });
      load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const open = async (row: LetterRow) => {
    setError(null);
    try {
      const res = await peopleApi.letter(row.id);
      setPreview({ id: row.id, key: row.template_key, html: res.rendered_html });
    } catch (err) {
      setError(err);
    }
  };

  // Download as a file rather than opening the letter in a live window of this app.
  const download = () => {
    if (!preview) return;
    const url = URL.createObjectURL(new Blob([preview.html], { type: 'text/html;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${letterName(preview.key).replace(/[^\p{L}\p{N} _-]+/gu, "").trim() || "letter"}.html`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loadError) return <FriendlyError error={loadError} what={t("people.letters.load_failed")} onRetry={load} />;

  return (
    <Grid container spacing={2.5}>
      <Grid size={{ xs: 12, lg: 5 }}>
        <Stack spacing={2.5}>
          {canCreate && (
            <SectionCard emoji="magic" title={t("people.letters.make_title")}>
              {templates === null ? <Skeleton variant="rounded" height={56} /> : templates.length === 0 ? (
                <EmptyState compact illustration="signed-document" title={t("people.letters.no_templates")}
                  action={<Button variant="outlined" component={RouterLink} to="/settings">{t("people.letters.open_settings")}</Button>} />
              ) : (
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "flex-start" }}>
                  <TextField select fullWidth size="small" label={t("people.letters.which")} value={picked} onChange={(e) => setPicked(e.target.value)} helperText={t("people.letters.which_hint")}>
                    {templates.map((tp) => <MenuItem key={tp.key} value={tp.key}>{letterName(tp.key)}</MenuItem>)}
                  </TextField>
                  <Button variant="contained" onClick={generate} disabled={busy || !picked} sx={{ whiteSpace: "nowrap", flexShrink: 0 }} startIcon={<Emoji name="page" size={16} />}>
                    {busy ? t("people.letters.making") : t("people.letters.make")}
                  </Button>
                </Stack>
              )}
              {error != null && <Box sx={{ mt: 1.5 }}><FriendlyError compact error={error} what={t("people.letters.failed")} /></Box>}
            </SectionCard>
          )}
          <SectionCard emoji="file_folder" title={t("people.letters.made_title")}>
            {letters === null ? <Skeleton variant="rounded" height={80} /> : letters.length === 0 ? (
              <Typography sx={{ color: f.muted }}>{t("people.letters.none")}</Typography>
            ) : (
              <Stack spacing={1} component="ul" sx={{ listStyle: "none", m: 0, p: 0 }}>
                {letters.map((l) => (
                  <Box component="li" key={l.id}>
                    <Button fullWidth onClick={() => open(l)} variant={preview?.id === l.id ? "contained" : "text"} color={preview?.id === l.id ? "primary" : "inherit"}
                      sx={{ justifyContent: "flex-start", textAlign: "left", gap: 1.25, py: 1 }}>
                      <Emoji name="page" size={20} />
                      <Box sx={{ minWidth: 0 }}>
                        <Typography sx={{ fontWeight: 700, fontSize: 14 }}>{letterName(l.template_key)}</Typography>
                        <Typography sx={{ fontSize: 12, opacity: 0.8 }}>{t("people.letters.made_on", { date: fmt(l.generated_at, true) })}</Typography>
                      </Box>
                    </Button>
                  </Box>
                ))}
              </Stack>
            )}
          </SectionCard>
        </Stack>
      </Grid>
      <Grid size={{ xs: 12, lg: 7 }}>
        <SectionCard
          emoji="eyes"
          title={<>{t("people.letters.preview")}<InfoTip text={t("people.letters.preview_tip")} /></>}
          action={preview ? <Button size="small" variant="outlined" onClick={download}>{t("people.letters.download")}</Button> : undefined}
        >
          {preview ? (
            <Box sx={{ maxWidth: "90ch" }}>
              <LetterPreview html={preview.html} title={letterName(preview.key)} />
            </Box>
          ) : (
            <EmptyState compact illustration="signed-document" title={t("people.letters.pick")} />
          )}
        </SectionCard>
      </Grid>
    </Grid>
  );
}
