import { useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Collapse from "@mui/material/Collapse";
import FormControlLabel from "@mui/material/FormControlLabel";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { onboardingExtraApi, type FieldShow, type JoiningFormSettings } from "../../api/onboardingExtra";
import { useI18n } from "../../i18n";

// Change 2026-10-05: Settings > Onboarding & employees > Joining details form. Every field of the
// joiner's "Your joining details" form (and every document on "Upload documents") is Required,
// Optional or Hidden; fields also get help text (en/hi/ta) and a format check on/off. Default:
// every field Optional. Save = a new version (applies to forms opened after saving); history + revert.

type Rules = JoiningFormSettings;
const SHOWS: FieldShow[] = ["required", "optional", "hidden"];
const SHOW_KEYS: Record<FieldShow, string> = { required: "jform.show.required", optional: "jform.show.optional", hidden: "jform.show.hidden" };
const SECTION_KEYS: Record<string, string> = {
  personal: "wsteps.g.personal", address: "wsteps.g.address", emergency: "wsteps.g.emergency", bank_id: "wsteps.g.bank",
};
const LANGS = [{ code: "en", key: "jform.lang.en" }, { code: "hi", key: "jform.lang.hi" }, { code: "ta", key: "jform.lang.ta" }] as const;

function payload(r: Rules) {
  return {
    fields: Object.fromEntries(r.fields.map((x) => [x.key, { show: x.show, help: x.help, check: x.check }])),
    documents: Object.fromEntries(r.documents.filter((x) => x.show !== x.default).map((x) => [x.code, x.show])),
  };
}

export default function JoiningFormSettingsPage() {
  const f = useTheme().palette.fresh;
  const { t } = useI18n();
  const [saved, setSaved] = useState<Rules | null>(null);
  const [draft, setDraft] = useState<Rules | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const take = (r: Rules) => { setSaved(r); setDraft(r); };
  useEffect(() => { onboardingExtraApi.joiningForm().then(take).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, "") })); }, []);
  const dirty = useMemo(() => Boolean(saved && draft && JSON.stringify(payload(saved)) !== JSON.stringify(payload(draft))), [saved, draft]);

  if (!draft) return msg ? <Alert severity="error">{msg.text}</Alert> : <Skeleton variant="rounded" height={320} />;

  const setField = (key: string, patch: Partial<Rules["fields"][number]>) =>
    setDraft({ ...draft, fields: draft.fields.map((x) => (x.key === key ? { ...x, ...patch } : x)) });
  const setDoc = (code: string, show: FieldShow) => setDraft({ ...draft, documents: draft.documents.map((x) => (x.code === code ? { ...x, show } : x)) });
  const run = async (fn: () => Promise<Rules>, ok: string) => {
    setBusy(true);
    setMsg(null);
    try {
      take(await fn());
      setMsg({ ok: true, text: ok });
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, "") });
    } finally {
      setBusy(false);
    }
  };
  const save = () => run(() => onboardingExtraApi.saveJoiningForm(payload(draft)), t("jform.saved"));
  const showGroup = (value: FieldShow, onChange: (v: FieldShow) => void, label: string) => (
    <ToggleButtonGroup size="small" exclusive value={value} onChange={(_, v) => v && onChange(v)} aria-label={label}>
      {SHOWS.map((s) => <ToggleButton key={s} value={s} sx={{ px: 1.25, textTransform: "none" }}>{t(SHOW_KEYS[s])}</ToggleButton>)}
    </ToggleButtonGroup>
  );

  return (
    <Stack spacing={2.5}>
      <Typography color="text.secondary">{t("jform.intro")}</Typography>
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography sx={{ fontSize: 13, color: f.muted, flex: 1 }}>
          {draft.version ? t("jform.version", { v: draft.version }) : t("jform.version_default")}
        </Typography>
        <Button size="small" onClick={() => setDraft({ ...draft, fields: draft.fields.map((x) => ({ ...x, show: "optional" })) })}>{t("jform.all_optional")}</Button>
      </Stack>

      {draft.sections.map((sec) => (
        <Card key={sec.key}>
          <CardContent>
            <Typography sx={{ fontWeight: 800, mb: 1 }}>{t(SECTION_KEYS[sec.key] ?? sec.label)}</Typography>
            <Stack spacing={1}>
              {draft.fields.filter((x) => x.section === sec.key).map((x) => (
                <Box key={x.key} data-testid={`jform-field-${x.key}`} sx={{ p: 1.25, border: `1px solid ${f.line}`, borderRadius: "10px", opacity: x.show === "hidden" ? 0.7 : 1 }}>
                  <Stack direction={{ xs: "column", md: "row" }} spacing={1.25} alignItems={{ md: "center" }}>
                    <Typography sx={{ fontWeight: 600, flex: 1, minWidth: 160 }}>{t(`wsteps.f.${x.key}`)}</Typography>
                    {showGroup(x.show, (v) => setField(x.key, { show: v }), t(`wsteps.f.${x.key}`))}
                    {x.checkable
                      ? <FormControlLabel control={<Switch size="small" checked={x.check} onChange={(e) => setField(x.key, { check: e.target.checked })} />} label={t("jform.check")} sx={{ minWidth: 150 }} />
                      : <Box sx={{ minWidth: 150 }} />}
                    <Button size="small" sx={{ whiteSpace: "nowrap", flexShrink: 0 }} onClick={() => setOpen(open === x.key ? null : x.key)}>
                      {x.help.en || x.help.hi || x.help.ta ? t("jform.help_edit") : t("jform.help_add")}
                    </Button>
                  </Stack>
                  <Collapse in={open === x.key} unmountOnExit>
                    <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mt: 1.25 }}>
                      {LANGS.map((l) => (
                        <TextField key={l.code} size="small" fullWidth label={t(l.key)} value={x.help[l.code] ?? ""}
                          onChange={(e) => setField(x.key, { help: { ...x.help, [l.code]: e.target.value } })} inputProps={{ maxLength: 300 }} />
                      ))}
                    </Stack>
                  </Collapse>
                </Box>
              ))}
            </Stack>
          </CardContent>
        </Card>
      ))}

      <Card>
        <CardContent>
          <Typography sx={{ fontWeight: 800 }}>{t("jform.docs.title")}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t("jform.docs.intro")}</Typography>
          <Stack spacing={1}>
            {draft.documents.map((x) => (
              <Stack key={x.code} direction={{ xs: "column", md: "row" }} spacing={1.25} alignItems={{ md: "center" }} sx={{ p: 1.25, border: `1px solid ${f.line}`, borderRadius: "10px" }}>
                <Box sx={{ flex: 1 }}>
                  <Typography sx={{ fontWeight: 600 }}>{x.label}</Typography>
                  <Typography sx={{ fontSize: 12, color: f.muted }}>{t("jform.docs.default", { show: t(SHOW_KEYS[x.default]) })}</Typography>
                </Box>
                {showGroup(x.show, (v) => setDoc(x.code, v), x.label)}
              </Stack>
            ))}
          </Stack>
        </CardContent>
      </Card>

      <Box sx={{ position: "sticky", bottom: 12, zIndex: 2 }}>
        <Card sx={{ boxShadow: dirty ? f.shadowHover : undefined }}>
          <CardContent sx={{ py: 1.5, pr: { xs: 2, sm: 10 }, "&:last-child": { pb: 1.5 } }}>{/* room for the assistant button */}
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography sx={{ flex: 1, fontSize: 14 }}>{dirty ? t("jform.unsaved") : t("jform.no_changes")}</Typography>
              <Button disabled={!dirty || busy} onClick={() => setDraft(saved)}>{t("jform.discard")}</Button>
              <Button variant="contained" disabled={!dirty || busy} onClick={save}>{t("jform.save")}</Button>
            </Stack>
          </CardContent>
        </Card>
      </Box>

      <Card>
        <CardContent>
          <Typography sx={{ fontWeight: 800, mb: 1 }}>{t("jform.history")}</Typography>
          {draft.history.length === 0 && <Typography variant="body2" color="text.secondary">{t("jform.history_none")}</Typography>}
          <Stack spacing={1}>
            {draft.history.map((h) => (
              <Stack key={h.version} direction="row" spacing={1} alignItems="flex-start" sx={{ p: 1, borderBottom: `1px solid ${f.line}` }}>
                <Box sx={{ flex: 1 }}>
                  <Typography sx={{ fontSize: 14, fontWeight: 600 }}>
                    {t("jform.history_row", { v: h.version, who: h.updated_by ?? "—", when: h.updated_at ? new Date(h.updated_at).toLocaleString() : "—" })}
                  </Typography>
                  <Typography sx={{ fontSize: 12, color: f.muted }}>{h.changes.length ? h.changes.join(" · ") : t("jform.history_nochange")}</Typography>
                </Box>
                {h.version !== draft.version && (
                  <Button size="small" disabled={busy} onClick={() => run(() => onboardingExtraApi.revertJoiningForm(h.version), t("jform.reverted", { v: h.version }))}>
                    {t("jform.revert")}
                  </Button>
                )}
              </Stack>
            ))}
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  );
}
