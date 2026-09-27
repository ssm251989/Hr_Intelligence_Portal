import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormGroup from "@mui/material/FormGroup";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { scoringApi, type ShortlistingIn, type ShortlistingRules } from "../../api/scoringApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";
import { FriendlyError, InfoTip } from "../../ui-kit";

// Part 17.6: when a candidate's Match score reaches the shortlist threshold they can be moved to
// Shortlisted automatically (with an undo window) -- company defaults (no jobId) or one job's own
// settings. Nobody is ever rejected automatically.

interface FormState {
  auto_shortlist: boolean;
  threshold: string;
  max_size: string;
  undo_hours: string;
  notify: string[];
}

const ROLES = ["job_owner", "hiring_manager"];
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function toForm(r: ShortlistingRules, jobId?: string): FormState {
  const ownThreshold = r.own?.threshold;
  return {
    auto_shortlist: Boolean(r.auto_shortlist),
    threshold: jobId ? (typeof ownThreshold === "number" ? String(ownThreshold) : "") : String(r.threshold ?? r.company_threshold),
    max_size: String(r.max_size ?? 0),
    undo_hours: String(r.undo_hours ?? 4),
    notify: r.notify ?? [],
  };
}

export default function ShortlistingRulesForm({ jobId, onDirtyChange }: { jobId?: string; onDirtyChange?: (dirty: boolean) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { can } = useMeBootstrap();
  const canEdit = can(jobId ? "recruitment.job.edit" : "recruitment.pipeline.configure");

  const [data, setData] = useState<ShortlistingRules | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [loaded, setLoaded] = useState<FormState | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const apply = useCallback((r: ShortlistingRules) => {
    setData(r);
    const next = toForm(r, jobId);
    setForm(next);
    setLoaded(next);
  }, [jobId]);

  const load = useCallback(() => {
    setLoadError(null);
    scoringApi.shortlisting(jobId).then(apply).catch(setLoadError);
  }, [jobId, apply]);

  useEffect(load, [load]);

  const dirty = form != null && loaded != null && JSON.stringify(form) !== JSON.stringify(loaded);
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  if (loadError) return <FriendlyError error={loadError} what={t("scoring.sl.err_load")} onRetry={load} />;
  if (!form || !data || !loaded) return <CircularProgress size={24} aria-label={t("scoring.loading")} />;

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setSaved(false);
    setForm((s) => (s ? { ...s, [key]: value } : s));
  };
  const hasOwn = Boolean(jobId && data.own && Object.keys(data.own).length > 0);
  const emails = form.notify.filter((n) => !ROLES.includes(n));

  const save = async (useCompany = false) => {
    setProblem(null);
    setSaveError(null);
    const payload: ShortlistingIn = {};
    if (useCompany) {
      payload.use_company = true;
    } else {
      const threshold = form.threshold.trim() === "" ? null : Number(form.threshold);
      const maxSize = Number(form.max_size || 0);
      const undo = Number(form.undo_hours || 0);
      if (threshold != null && (!Number.isInteger(threshold) || threshold < 0 || threshold > 100)) return setProblem(t("scoring.sl.v_threshold"));
      if (!jobId && threshold == null) return setProblem(t("scoring.sl.v_threshold"));
      if (!Number.isInteger(maxSize) || maxSize < 0) return setProblem(t("scoring.sl.v_max"));
      if (!Number.isInteger(undo) || undo < 0 || undo > 72) return setProblem(t("scoring.sl.v_undo"));
      const bad = emails.find((e) => !EMAIL.test(e));
      if (bad) return setProblem(t("scoring.sl.v_email", { email: bad }));
      // a job keeps only what was changed here, so everything else follows the company defaults
      if (!jobId || form.auto_shortlist !== loaded.auto_shortlist) payload.auto_shortlist = form.auto_shortlist;
      if (!jobId || form.threshold !== loaded.threshold) payload.threshold = threshold;
      if (!jobId || form.max_size !== loaded.max_size) payload.max_size = maxSize;
      if (!jobId || form.undo_hours !== loaded.undo_hours) payload.undo_hours = undo;
      if (!jobId || JSON.stringify(form.notify) !== JSON.stringify(loaded.notify)) payload.notify = form.notify;
    }
    setSaving(true);
    try {
      apply(await scoringApi.saveShortlisting(payload, jobId));
      setSaved(true);
    } catch (err) {
      setSaveError(err);
    } finally {
      setSaving(false);
    }
  };

  const toggleRole = (role: string, on: boolean) =>
    set("notify", on ? [...form.notify.filter((n) => n !== role), role] : form.notify.filter((n) => n !== role));

  return (
    <Card sx={{ p: 2 }}>
      <Typography variant="h6" component="h3" sx={{ fontWeight: 700 }}>
        {jobId ? t("scoring.sl.title_job") : t("scoring.sl.title_company")}
      </Typography>
      <Typography sx={{ fontSize: 13, color: f.muted, mb: 1 }}>{t("scoring.sl.hint")}</Typography>
      <Alert severity="info" sx={{ mb: 2 }}>{t("scoring.sl.never_reject")}</Alert>
      {jobId && (
        <Typography sx={{ fontSize: 13, fontWeight: 600, mb: 1.5 }}>
          {hasOwn ? t("scoring.sl.job_own") : t("scoring.sl.job_company")}
        </Typography>
      )}

      <Stack spacing={2}>
        <FormControlLabel disabled={!canEdit} label={t("scoring.sl.auto")}
          control={<Switch checked={form.auto_shortlist} onChange={(e) => set("auto_shortlist", e.target.checked)} />} />
        <Typography sx={{ fontSize: 13, color: f.muted, mt: "-8px !important" }}>{t("scoring.sl.auto_hint")}</Typography>

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
          <TextField size="small" type="number" disabled={!canEdit} label={t("scoring.sl.threshold")} value={form.threshold}
            placeholder={jobId ? t("scoring.sl.threshold_ph", { value: data.company_threshold }) : undefined}
            helperText={jobId ? t("scoring.sl.threshold_job_hint", { value: data.company_threshold }) : t("scoring.sl.threshold_hint")}
            onChange={(e) => set("threshold", e.target.value)} slotProps={{ htmlInput: { min: 0, max: 100 }, inputLabel: { shrink: true } }} sx={{ width: { sm: 240 } }} />
          <TextField size="small" type="number" disabled={!canEdit} label={t("scoring.sl.max")} value={form.max_size}
            helperText={t("scoring.sl.max_hint")} onChange={(e) => set("max_size", e.target.value)} slotProps={{ htmlInput: { min: 0 } }} sx={{ width: { sm: 220 } }} />
          <TextField size="small" type="number" disabled={!canEdit} label={t("scoring.sl.undo")} value={form.undo_hours}
            helperText={t("scoring.sl.undo_hint")} onChange={(e) => set("undo_hours", e.target.value)} slotProps={{ htmlInput: { min: 0, max: 72 } }} sx={{ width: { sm: 240 } }} />
        </Stack>

        <Box>
          <Typography sx={{ fontWeight: 700, fontSize: 14 }}>
            {t("scoring.sl.notify")}
            <InfoTip text={t("scoring.sl.notify_info")} />
          </Typography>
          <FormGroup row>
            {ROLES.map((role) => (
              <FormControlLabel key={role} disabled={!canEdit} label={t(`scoring.sl.notify.${role}`)}
                control={<Checkbox checked={form.notify.includes(role)} onChange={(e) => toggleRole(role, e.target.checked)} />} />
            ))}
          </FormGroup>
          <Autocomplete multiple freeSolo autoSelect options={[] as string[]} value={emails} disabled={!canEdit}
            onChange={(_e, v) => set("notify", [...form.notify.filter((n) => ROLES.includes(n)), ...(v as string[]).flatMap((x) => x.split(",")).map((x) => x.trim()).filter(Boolean)])}
            renderTags={(selected, getTagProps) => selected.map((s, i) => { const { key, ...rest } = getTagProps({ index: i }); return <Chip key={key} size="small" label={s} color={EMAIL.test(s) ? "default" : "error"} {...rest} />; })}
            renderInput={(params) => <TextField {...params} size="small" label={t("scoring.sl.notify_emails")} helperText={t("scoring.sl.notify_emails_hint")} />}
            sx={{ maxWidth: 520, mt: 0.5 }} />
        </Box>

        {problem && <Typography role="alert" sx={{ color: f.coral, fontWeight: 600 }}>{problem}</Typography>}
        {saveError != null && <FriendlyError compact error={saveError} what={t("scoring.sl.err_save")} />}

        {canEdit ? (
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
            <Button variant="contained" onClick={() => void save()} disabled={saving || !dirty}>
              {saving ? t("scoring.save.saving") : t("scoring.sl.save")}
            </Button>
            {dirty && <Button onClick={() => { setForm(loaded); setProblem(null); }} disabled={saving}>{t("scoring.undo_changes")}</Button>}
            {jobId && hasOwn && (
              <Button variant="outlined" onClick={() => void save(true)} disabled={saving}>{t("scoring.sl.use_company")}</Button>
            )}
            <Typography role="status" sx={{ fontSize: 13, color: saved ? f.ok : f.muted, fontWeight: saved ? 700 : 400 }}>
              {saved ? t("scoring.sl.saved") : dirty ? t("scoring.save.unsaved") : ""}
            </Typography>
          </Stack>
        ) : (
          <Typography sx={{ fontSize: 13, color: f.muted }}>{t("scoring.read_only")}</Typography>
        )}
      </Stack>
    </Card>
  );
}
