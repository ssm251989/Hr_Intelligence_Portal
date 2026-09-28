import { useCallback, useEffect, useRef, useState } from "react";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import Alert from "@mui/material/Alert";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Collapse from "@mui/material/Collapse";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { candidatesApi, jobsApi, metadataApi, type CustomFieldDefRow } from "../../api/client";
import type { CandidateApplicationRow, JobRoleRead } from "../../api/types";
import {
  FACTOR_KEYS, KNOCKOUT_TYPES, downloadBlob, scoringApi,
  type FactorKey, type Knockout, type KnockoutType, type PreviewResponse, type RecalcRun, type RulesResponse, type ScoringCatalog, type ScoringRules,
} from "../../api/scoringApi";
import { useI18n, useT } from "../../i18n";
import { Emoji, FriendlyError, InfoTip, useConfirmLeave } from "../../ui-kit";

// Part 17.5: the one place to set how the Match score is worked out -- for the whole company
// (no jobId) or for one job (jobId). Weights of the switched-on factors add up to 100; knock-out
// rules only flag candidates. Nothing is saved until the person presses Save; each save is a
// new version and every open application is rescored in the background.

type Band = Record<string, number | null>;

const DEFAULT_BANDS: Record<string, { param: string; key: string; bands: Band[] }> = {
  location: { param: "km_bands", key: "km", bands: [{ km: 25, score: 100 }, { km: 100, score: 75 }, { km: 300, score: 45 }, { km: null, score: 15 }] },
  notice: { param: "day_bands", key: "days", bands: [{ days: 15, score: 100 }, { days: 30, score: 90 }, { days: 60, score: 70 }, { days: 90, score: 40 }, { days: null, score: 10 }] },
  salary: { param: "over_pct_bands", key: "pct", bands: [{ pct: 10, score: 60 }, { pct: 20, score: 30 }, { pct: null, score: 0 }] },
};
const HAS_SETTINGS: FactorKey[] = ["experience", "location", "notice", "salary", "education", "languages", "custom", "domain"];
const EDU_LEVELS = ["Any", "Diploma", "Bachelor's", "Master's", "PhD"];
const PREVIEW_DELAY = 400;

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const numOrNull = (s: string): number | null => (s.trim() === "" || !Number.isFinite(Number(s)) ? null : Number(s));
const totalOf = (rules: ScoringRules | null) =>
  rules ? Object.values(rules.factors).reduce((sum, f) => sum + (f.enabled ? f.weight : 0), 0) : 0;

export default function ScoringRulesEditor({ jobId, onDirtyChange }: { jobId?: string; onDirtyChange?: (dirty: boolean) => void }) {
  const t = useT();
  const { locale } = useI18n();
  const f = useTheme().palette.fresh;

  const [catalog, setCatalog] = useState<ScoringCatalog | null>(null);
  const [info, setInfo] = useState<RulesResponse | null>(null);
  const [rules, setRules] = useState<ScoringRules | null>(null);
  const [baseline, setBaseline] = useState("");
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [preset, setPreset] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [customFields, setCustomFields] = useState<CustomFieldDefRow[]>([]);
  const [imported, setImported] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [savedVersion, setSavedVersion] = useState<number | null>(null);
  const [run, setRun] = useState<RecalcRun | null>(null);
  const [confirmRevert, setConfirmRevert] = useState<number | null>(null);
  const [confirmCompany, setConfirmCompany] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // preview
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [previewJob, setPreviewJob] = useState<string>(jobId ?? "");
  const [apps, setApps] = useState<CandidateApplicationRow[]>([]);
  const [picked, setPicked] = useState<CandidateApplicationRow[]>([]);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [cat, res] = await Promise.all([scoringApi.catalog(), scoringApi.rules(jobId)]);
      setCatalog(cat);
      setInfo(res);
      setRules(clone(res.rules));
      setBaseline(JSON.stringify(res.rules));
      setImported(false);
    } catch (err) {
      setLoadError(err);
    }
  }, [jobId]);

  useEffect(() => {
    void load();
    metadataApi.customFields("candidate").then((rows) => setCustomFields(rows.filter((r) => r.is_active))).catch(() => undefined);
    if (!jobId) jobsApi.list().then(setJobs).catch(() => undefined);
  }, [load, jobId]);

  useEffect(() => setPreviewJob(jobId ?? ""), [jobId]);

  const dirty = rules != null && JSON.stringify(rules) !== baseline;
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);
  useConfirmLeave(dirty); // Part 17.13: ask before leaving with unsaved rule changes

  // the job's candidates to choose from for the preview
  useEffect(() => {
    setPicked([]);
    setApps([]);
    setPreview(null);
    if (!previewJob) return;
    candidatesApi.listApplications({ jobRoleId: previewJob, pageSize: 50 }).then((p) => setApps(p.items)).catch(() => undefined);
  }, [previewJob]);

  // live preview (debounced)
  const rulesKey = rules ? JSON.stringify(rules) : "";
  const pickedKey = picked.map((p) => p.application_id).join(",");
  useEffect(() => {
    if (!previewJob || !rules) return;
    const timer = window.setTimeout(() => {
      setPreviewing(true);
      setPreviewError(null);
      scoringApi.preview(previewJob, rules, pickedKey ? pickedKey.split(",") : undefined)
        .then(setPreview)
        .catch(setPreviewError)
        .finally(() => setPreviewing(false));
    }, PREVIEW_DELAY);
    return () => window.clearTimeout(timer);
  }, [previewJob, rulesKey, pickedKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // recalculation progress
  const runActive = run != null && (run.status === "queued" || run.status === "running");
  useEffect(() => {
    if (!run || !runActive) return;
    const timer = window.setInterval(() => {
      scoringApi.run(run.id).then(setRun).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [run?.id, runActive]); // eslint-disable-line react-hooks/exhaustive-deps

  const readOnly = !info?.can_edit;
  const total = totalOf(rules);
  const totalOk = total === 100;
  const when = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString(locale === "en" ? "en-IN" : `${locale}-IN`, { dateStyle: "medium", timeStyle: "short" }) : "";

  const setFactor = (key: string, patch: Partial<ScoringRules["factors"][string]>) =>
    setRules((r) => (r ? { ...r, factors: { ...r.factors, [key]: { ...r.factors[key], ...patch } } } : r));
  const setParams = (key: string, patch: Record<string, unknown>) =>
    setRules((r) => {
      if (!r) return r;
      const params = { ...r.factors[key].params, ...patch };
      for (const k of Object.keys(params)) if (params[k] === null || params[k] === undefined || params[k] === "") delete params[k];
      return { ...r, factors: { ...r.factors, [key]: { ...r.factors[key], params } } };
    });
  const setKnockouts = (knockouts: Knockout[]) => setRules((r) => (r ? { ...r, knockouts } : r));

  const pickPreset = (key: string) => {
    setPreset(key);
    const p = catalog?.presets.find((x) => x.key === key);
    if (p) setRules((r) => ({ ...(r ?? p.rules), factors: clone(p.rules.factors) }));
  };

  const run_ = async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setActionError(null);
    try {
      return await fn();
    } catch (err) {
      setActionError(err);
      return null;
    } finally {
      setBusy(false);
    }
  };

  const balance = () => rules && run_(async () => {
    const res = await scoringApi.balance(rules);
    setRules(res.rules);
  });

  const afterSave = async (version: number | null, newRun: RecalcRun) => {
    setSavedVersion(version);
    setRun(newRun);
    setNote("");
    setPreset("");
    await load();
  };

  const save = () => rules && run_(async () => {
    const res = await scoringApi.save(rules, note.trim() || null, jobId);
    await afterSave(res.version, res.run);
  });

  const revert = (version: number) => run_(async () => {
    setConfirmRevert(null);
    const res = await scoringApi.revert(version, jobId);
    await afterSave(res.version, res.run);
  });

  const backToCompany = () => jobId && run_(async () => {
    setConfirmCompany(false);
    const res = await scoringApi.useCompany(jobId);
    await afterSave(null, res.run);
  });

  const exportAs = (format: "json" | "xlsx") => run_(async () => {
    const blob = await scoringApi.exportFile(format, jobId);
    if (!blob) throw new Error(t("scoring.export.failed"));
    downloadBlob(blob, `scoring-rules${jobId ? "-job" : "-company"}.${format}`);
  });

  const importFile = (file: File) => run_(async () => {
    const res = await scoringApi.importFile(file);
    setRules(res.rules);
    setImported(true);
    setPreset("");
  });

  const undoChanges = () => {
    setRules(JSON.parse(baseline) as ScoringRules);
    setImported(false);
    setPreset("");
  };

  if (loadError) return <FriendlyError error={loadError} what={t("scoring.err.load")} onRetry={() => void load()} />;
  if (!rules || !catalog || !info) return <CircularProgress size={24} aria-label={t("scoring.loading")} />;

  const sourceText = jobId
    ? info.source === "job" ? t("scoring.source.job_own", { version: info.version ?? 1 }) : info.source === "company" ? t("scoring.source.job_company", { version: info.version ?? 1 }) : t("scoring.source.job_preset")
    : info.source === "company" ? t("scoring.source.company", { version: info.version ?? 1 }) : t("scoring.source.company_preset");

  const numField = (label: string, value: unknown, onChange: (v: number | null) => void, opts: { placeholder?: string; width?: number; min?: number; max?: number } = {}) => (
    <TextField size="small" type="number" label={label} value={value ?? ""} disabled={readOnly} placeholder={opts.placeholder}
      onChange={(e) => onChange(numOrNull(e.target.value))} sx={{ width: opts.width ?? 140 }}
      slotProps={{ htmlInput: { min: opts.min ?? 0, max: opts.max } }} />
  );

  const chipsField = (label: string, value: string[], onChange: (v: string[]) => void, helper?: string) => (
    <Autocomplete multiple freeSolo autoSelect options={[] as string[]} value={value} disabled={readOnly}
      onChange={(_e, v) => onChange((v as string[]).flatMap((x) => x.split(",")).map((x) => x.trim()).filter(Boolean))}
      renderTags={(selected, getTagProps) => selected.map((s, i) => { const { key, ...rest } = getTagProps({ index: i }); return <Chip key={key} size="small" label={s} {...rest} />; })}
      renderInput={(params) => <TextField {...params} size="small" label={label} helperText={helper} />} sx={{ minWidth: 260, flex: 1 }} />
  );

  const bandsEditor = (factor: "location" | "notice" | "salary") => {
    const def = DEFAULT_BANDS[factor];
    const params = rules.factors[factor].params;
    const bands = ((params[def.param] as Band[] | undefined)?.length ? (params[def.param] as Band[]) : def.bands).map((b) => ({ ...b }));
    const write = (next: Band[]) => setParams(factor, { [def.param]: next });
    return (
      <Stack spacing={1}>
        <Typography sx={{ fontSize: 13, color: f.muted }}>{t(`scoring.bands.${factor}.intro`)}</Typography>
        {bands.map((b, i) => {
          const last = i === bands.length - 1;
          return (
            <Stack key={i} direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              {last ? (
                <Typography sx={{ fontSize: 14, width: 180 }}>{t(`scoring.bands.${factor}.beyond`)}</Typography>
              ) : (
                numField(t(`scoring.bands.${factor}.upto`), b[def.key], (v) => { bands[i] = { ...b, [def.key]: v ?? 0 }; write(bands); }, { width: 180 })
              )}
              <Typography aria-hidden sx={{ color: f.muted }}>→</Typography>
              {numField(t("scoring.bands.score"), b.score, (v) => { bands[i] = { ...b, score: Math.max(0, Math.min(100, v ?? 0)) }; write(bands); }, { width: 110, max: 100 })}
              {!last && !readOnly && bands.length > 2 && (
                <IconButton size="small" aria-label={t("scoring.bands.remove")} onClick={() => write(bands.filter((_x, j) => j !== i))}><DeleteOutlineIcon fontSize="small" /></IconButton>
              )}
            </Stack>
          );
        })}
        {!readOnly && (
          <Box>
            <Button size="small" startIcon={<AddIcon />} onClick={() => {
              const prev = bands.length > 1 ? Number(bands[bands.length - 2][def.key] ?? 0) : 0;
              write([...bands.slice(0, -1), { [def.key]: prev + (factor === "salary" ? 10 : factor === "notice" ? 30 : 100), score: 50 }, bands[bands.length - 1]]);
            }}>{t("scoring.bands.add")}</Button>
          </Box>
        )}
      </Stack>
    );
  };

  const settingsFor = (key: FactorKey) => {
    const p = rules.factors[key].params;
    switch (key) {
      case "experience":
        return (
          <Stack spacing={1}>
            <Typography sx={{ fontSize: 13, color: f.muted }}>{t("scoring.set.experience.intro")}</Typography>
            <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
              {numField(t("scoring.set.experience.min"), p.min, (v) => setParams(key, { min: v }), { placeholder: t("scoring.set.job_value") })}
              {numField(t("scoring.set.experience.ideal"), p.ideal, (v) => setParams(key, { ideal: v }), { placeholder: t("scoring.set.optional") })}
              {numField(t("scoring.set.experience.max"), p.max, (v) => setParams(key, { max: v }), { placeholder: t("scoring.set.job_value") })}
            </Stack>
          </Stack>
        );
      case "location":
        return (
          <Stack spacing={1.5}>
            {bandsEditor("location")}
            {numField(t("scoring.set.location.relocation"), p.relocation_score ?? 70, (v) => setParams(key, { relocation_score: v == null ? null : Math.min(100, v) }), { width: 260, max: 100 })}
          </Stack>
        );
      case "notice":
        return bandsEditor("notice");
      case "salary":
        return bandsEditor("salary");
      case "education":
        return (
          <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
            <TextField select size="small" label={t("scoring.set.education.level")} value={(p.level as string) ?? ""} disabled={readOnly}
              onChange={(e) => setParams(key, { level: e.target.value })} sx={{ minWidth: 220 }}>
              <MenuItem value="">{t("scoring.set.job_value")}</MenuItem>
              {EDU_LEVELS.map((lv) => <MenuItem key={lv} value={lv}>{t(`scoring.edu.${lv === "Bachelor's" ? "bachelor" : lv === "Master's" ? "master" : lv.toLowerCase()}`)}</MenuItem>)}
            </TextField>
            <TextField size="small" label={t("scoring.set.education.field")} value={(p.field as string) ?? ""} disabled={readOnly}
              placeholder={t("scoring.set.job_value")} onChange={(e) => setParams(key, { field: e.target.value })} sx={{ minWidth: 240 }} />
          </Stack>
        );
      case "languages":
        return chipsField(t("scoring.set.languages.list"), (p.list as string[]) ?? [], (v) => setParams(key, { list: v.length ? v : null }), t("scoring.set.languages.hint"));
      case "domain":
        return (
          <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap alignItems="flex-start">
            {chipsField(t("scoring.set.domain.keywords"), (p.keywords as string[]) ?? [], (v) => setParams(key, { keywords: v.length ? v : null }), t("scoring.set.domain.hint"))}
            {numField(t("scoring.set.domain.years"), p.years_for_full, (v) => setParams(key, { years_for_full: v }), { width: 220, placeholder: t("scoring.set.job_value") })}
          </Stack>
        );
      case "custom": {
        const kind = (p.kind as string) === "yes_no" ? "yes_no" : "numeric";
        return (
          <Stack spacing={1.5}>
            {customFields.length === 0 && <Typography sx={{ fontSize: 13, color: f.muted }}>{t("scoring.set.custom.none")}</Typography>}
            <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
              <TextField select size="small" label={t("scoring.set.custom.field")} value={(p.field as string) ?? ""} disabled={readOnly}
                onChange={(e) => setParams(key, { field: e.target.value })} sx={{ minWidth: 240 }}
                error={rules.factors.custom.enabled && !p.field} helperText={rules.factors.custom.enabled && !p.field ? t("scoring.set.custom.pick") : undefined}>
                <MenuItem value="">{t("scoring.set.custom.choose")}</MenuItem>
                {customFields.map((cf) => <MenuItem key={cf.code} value={cf.code}>{cf.label_i18n?.[locale] || cf.label_i18n?.en || cf.code}</MenuItem>)}
              </TextField>
              <TextField select size="small" label={t("scoring.set.custom.kind")} value={kind} disabled={readOnly}
                onChange={(e) => setParams(key, { kind: e.target.value })} sx={{ minWidth: 200 }}>
                <MenuItem value="numeric">{t("scoring.set.custom.numeric")}</MenuItem>
                <MenuItem value="yes_no">{t("scoring.set.custom.yes_no")}</MenuItem>
              </TextField>
            </Stack>
            {kind === "numeric" ? (
              <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
                {numField(t("scoring.set.custom.min"), p.min, (v) => setParams(key, { min: v }), { width: 200, min: undefined })}
                {numField(t("scoring.set.custom.max"), p.max, (v) => setParams(key, { max: v }), { width: 200, min: undefined })}
              </Stack>
            ) : (
              <TextField select size="small" label={t("scoring.set.custom.want")} value={p.want === false ? "no" : "yes"} disabled={readOnly}
                onChange={(e) => setParams(key, { want: e.target.value === "yes" })} sx={{ maxWidth: 260 }}>
                <MenuItem value="yes">{t("scoring.set.custom.want_yes")}</MenuItem>
                <MenuItem value="no">{t("scoring.set.custom.want_no")}</MenuItem>
              </TextField>
            )}
          </Stack>
        );
      }
      default:
        return null;
    }
  };

  // ---------------------------------------------------------------- knock-outs
  const knockoutRow = (k: Knockout, i: number) => {
    const update = (patch: Partial<Knockout>) => setKnockouts(rules.knockouts.map((x, j) => (j === i ? { ...x, ...patch } : x)));
    return (
      <Stack key={i} direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}
        sx={{ p: 1.25, borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
        <Typography sx={{ fontWeight: 700, minWidth: 190 }}>{t(`scoring.ko.${k.type}`)}</Typography>
        <Box sx={{ flex: 1, display: "flex", gap: 1.5, flexWrap: "wrap", alignItems: "center" }}>
          {k.type === "must_have_skill" && (
            <TextField size="small" label={t("scoring.ko.skill")} value={k.skill ?? ""} disabled={readOnly} onChange={(e) => update({ skill: e.target.value })} sx={{ minWidth: 220 }} />
          )}
          {k.type === "max_notice_days" && numField(t("scoring.ko.days"), k.days, (v) => update({ days: v }), { width: 200 })}
          {k.type === "min_experience" && numField(t("scoring.ko.years"), k.years, (v) => update({ years: v }), { width: 200 })}
          {k.type === "max_expected_salary" && numField(t("scoring.ko.amount"), k.amount, (v) => update({ amount: v }), { width: 220 })}
          {k.type === "location_in" && (
            <>
              {chipsField(t("scoring.ko.places"), k.places ?? [], (v) => update({ places: v }))}
              <FormControlLabel disabled={readOnly} label={t("scoring.ko.allow_relocation")}
                control={<Switch checked={k.allow_relocation ?? true} onChange={(e) => update({ allow_relocation: e.target.checked })} />} />
            </>
          )}
        </Box>
        {!readOnly && (
          <IconButton aria-label={t("scoring.ko.remove")} onClick={() => setKnockouts(rules.knockouts.filter((_x, j) => j !== i))}><DeleteOutlineIcon /></IconButton>
        )}
      </Stack>
    );
  };

  const addKnockout = (type: KnockoutType) => {
    const base: Knockout = type === "location_in" ? { type, places: [], allow_relocation: true } : type === "must_have_skill" ? { type, skill: "" } : { type };
    setKnockouts([...rules.knockouts, base]);
  };

  const pct = run && run.total > 0 ? Math.round((100 * run.done) / run.total) : run?.status === "done" ? 100 : 0;
  const scoreText = (n: number | null | undefined) => (n == null ? "—" : String(Math.round(n)));

  return (
    <Stack spacing={2.5}>
      {/* where the rules come from */}
      <Card sx={{ p: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
          <Emoji name={info.source === "job" ? "briefcase" : "building"} size={22} />
          <Box sx={{ flex: 1 }}>
            <Typography sx={{ fontWeight: 700 }}>{sourceText}</Typography>
            <Typography sx={{ fontSize: 13, color: f.muted }}>
              {jobId ? (info.source === "job" ? t("scoring.source.job_own_hint") : t("scoring.source.job_company_hint")) : t("scoring.source.company_hint")}
            </Typography>
          </Box>
          {jobId && info.source === "job" && !readOnly && (
            <Button variant="outlined" onClick={() => setConfirmCompany(true)} disabled={busy}>{t("scoring.use_company")}</Button>
          )}
        </Stack>
        {readOnly && <Alert severity="info" sx={{ mt: 1.5 }}>{t("scoring.read_only")}</Alert>}
      </Card>

      {imported && (
        <Alert severity="warning" action={<Button color="inherit" size="small" onClick={undoChanges}>{t("scoring.undo_changes")}</Button>}>
          {t("scoring.import.banner")}
        </Alert>
      )}
      {actionError != null && <FriendlyError compact error={actionError} what={t("scoring.err.action")} />}

      {/* factors */}
      <Card sx={{ p: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }} sx={{ mb: 1.5 }}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="h6" component="h3" sx={{ fontWeight: 700 }}>
              {t("scoring.factors.title")}
              <InfoTip text={t("scoring.factors.info")} />
            </Typography>
            <Typography sx={{ fontSize: 13, color: f.muted }}>{t("scoring.factors.hint")}</Typography>
          </Box>
          {!readOnly && (
            <TextField select size="small" label={t("scoring.preset.label")} value={preset} onChange={(e) => pickPreset(e.target.value)} sx={{ minWidth: 220 }}>
              {catalog.presets.map((p) => <MenuItem key={p.key} value={p.key}>{t(`scoring.preset.${p.key}`)}</MenuItem>)}
            </TextField>
          )}
        </Stack>
        {preset && <Typography sx={{ fontSize: 13, color: f.muted, mb: 1 }}>{t("scoring.preset.picked")}</Typography>}

        <Stack spacing={1}>
          {FACTOR_KEYS.filter((k) => rules.factors[k]).map((key) => {
            const fr = rules.factors[key];
            const hasSettings = HAS_SETTINGS.includes(key);
            const isOpen = Boolean(open[key]);
            return (
              <Box key={key} sx={{ p: 1.25, borderRadius: "10px", border: `1px solid ${f.line}`, bgcolor: fr.enabled ? f.surface : f.surface2 }}>
                <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ flex: 1, minWidth: 0 }}>
                    <Switch checked={fr.enabled} disabled={readOnly} onChange={(e) => setFactor(key, { enabled: e.target.checked })}
                      slotProps={{ input: { "aria-label": t("scoring.factor.switch", { name: t(`scoring.factor.${key}`) }) } }} />
                    <Box sx={{ minWidth: 0 }}>
                      <Typography sx={{ fontWeight: 700, color: fr.enabled ? f.ink : f.muted }}>{t(`scoring.factor.${key}`)}</Typography>
                      <Typography sx={{ fontSize: 12.5, color: f.muted }}>{t(`scoring.factor.${key}.hint`)}</Typography>
                    </Box>
                  </Stack>
                  <Stack direction="row" spacing={1.5} alignItems="center" sx={{ width: { xs: "100%", md: 320 } }}>
                    <Slider value={fr.weight} min={0} max={100} step={1} disabled={readOnly || !fr.enabled} sx={{ flex: 1 }}
                      onChange={(_e, v) => setFactor(key, { weight: v as number })}
                      aria-label={t("scoring.factor.weight_of", { name: t(`scoring.factor.${key}`) })} />
                    <Typography sx={{ width: 44, textAlign: "right", fontWeight: 700, fontVariantNumeric: "tabular-nums", color: fr.enabled ? f.ink : f.muted }}>
                      {fr.weight}%
                    </Typography>
                    {hasSettings ? (
                      <IconButton size="small" onClick={() => setOpen((o) => ({ ...o, [key]: !isOpen }))} aria-expanded={isOpen}
                        aria-label={t("scoring.factor.settings", { name: t(`scoring.factor.${key}`) })}>
                        {isOpen ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                      </IconButton>
                    ) : <Box sx={{ width: 34 }} />}
                  </Stack>
                </Stack>
                {hasSettings && (
                  <Collapse in={isOpen} unmountOnExit>
                    <Box sx={{ pt: 1.5, pl: { md: 7 } }}>{settingsFor(key)}</Box>
                  </Collapse>
                )}
              </Box>
            );
          })}
        </Stack>

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }} sx={{ mt: 2 }}>
          <Typography role="status" sx={{ fontWeight: 800, fontSize: 16, color: totalOk ? f.ok : f.coral, flex: 1 }}>
            {totalOk ? t("scoring.total.ok", { total }) : t("scoring.total.bad", { total })}
          </Typography>
          {!readOnly && <Button variant="outlined" onClick={() => void balance()} disabled={busy || totalOk}>{t("scoring.balance")}</Button>}
        </Stack>
      </Card>

      {/* knock-outs */}
      <Card sx={{ p: 2 }}>
        <Typography variant="h6" component="h3" sx={{ fontWeight: 700 }}>{t("scoring.ko.title")}</Typography>
        <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("scoring.ko.hint")}</Typography>
        <Stack spacing={1}>
          {rules.knockouts.length === 0 && <Typography sx={{ color: f.muted, fontSize: 14 }}>{t("scoring.ko.none")}</Typography>}
          {rules.knockouts.map(knockoutRow)}
        </Stack>
        {!readOnly && (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.5 }}>
            {KNOCKOUT_TYPES.map((type) => (
              <Button key={type} size="small" variant="outlined" startIcon={<AddIcon />} onClick={() => addKnockout(type)}>{t(`scoring.ko.${type}`)}</Button>
            ))}
          </Stack>
        )}
      </Card>

      {/* live preview */}
      <Card sx={{ p: 2 }}>
        <Typography variant="h6" component="h3" sx={{ fontWeight: 700 }}>{t("scoring.preview.title")}</Typography>
        <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("scoring.preview.hint")}</Typography>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ mb: 1.5 }}>
          {!jobId && (
            <TextField select size="small" label={t("scoring.preview.job")} value={previewJob} onChange={(e) => setPreviewJob(e.target.value)} sx={{ minWidth: 260 }}>
              <MenuItem value="">{t("scoring.preview.job_choose")}</MenuItem>
              {jobs.map((j) => <MenuItem key={j.id} value={j.id}>{j.title}</MenuItem>)}
            </TextField>
          )}
          {previewJob && (
            <Autocomplete multiple size="small" options={apps} value={picked} sx={{ flex: 1, minWidth: 260 }}
              getOptionLabel={(o) => o.candidate_name || o.candidate_email || t("scoring.preview.unnamed")}
              isOptionEqualToValue={(a, b) => a.application_id === b.application_id}
              getOptionDisabled={(o) => picked.length >= 3 && !picked.some((p) => p.application_id === o.application_id)}
              onChange={(_e, v) => setPicked(v.slice(0, 3))}
              renderInput={(params) => <TextField {...params} label={t("scoring.preview.pick")} placeholder={picked.length ? "" : t("scoring.preview.pick_default")} />} />
          )}
        </Stack>
        {!previewJob ? (
          <Typography sx={{ color: f.muted, fontSize: 14 }}>{t("scoring.preview.need_job")}</Typography>
        ) : previewError ? (
          <FriendlyError compact error={previewError} what={t("scoring.preview.err")} />
        ) : preview == null ? (
          <CircularProgress size={20} aria-label={t("scoring.loading")} />
        ) : preview.candidates.length === 0 ? (
          <Typography sx={{ color: f.muted, fontSize: 14 }}>{t("scoring.preview.empty")}</Typography>
        ) : (
          <Box sx={{ opacity: previewing ? 0.6 : 1, transition: "opacity .2s" }} aria-busy={previewing}>
            <Typography sx={{ fontSize: 13, color: f.muted, mb: 1 }}>
              {t("scoring.preview.threshold", { threshold: preview.threshold })}
              {preview.weights_total !== 100 && ` ${t("scoring.preview.not_100")}`}
            </Typography>
            <Box sx={{ display: "grid", gap: 1.25, gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" } }}>
              {preview.candidates.map((c) => {
                const diff = c.current_score == null ? null : Math.round(c.new_score) - Math.round(c.current_score);
                return (
                  <Box key={c.application_id} sx={{ p: 1.5, borderRadius: "10px", border: `1px solid ${f.line}`, bgcolor: f.surface2 }}>
                    <Typography sx={{ fontWeight: 700 }} noWrap>{c.candidate_name || t("scoring.preview.unnamed")}</Typography>
                    <Stack direction="row" spacing={1} alignItems="baseline" sx={{ mt: 0.5 }}>
                      <Typography sx={{ fontSize: 13, color: f.muted }}>{t("scoring.preview.now", { score: scoreText(c.current_score) })}</Typography>
                      <Typography aria-hidden sx={{ color: f.muted }}>→</Typography>
                      <Typography sx={{ fontSize: 22, fontWeight: 800 }}>{scoreText(c.new_score)}</Typography>
                      {diff != null && diff !== 0 && (
                        <Typography sx={{ fontSize: 13, fontWeight: 700, color: diff > 0 ? f.ok : f.coral }}>{diff > 0 ? `+${diff}` : diff}</Typography>
                      )}
                    </Stack>
                    <Typography sx={{ fontSize: 12.5, mt: 0.5, fontWeight: 600, color: c.knocked_out ? f.coral : c.above_threshold ? f.ok : f.muted }}>
                      {c.knocked_out ? t("scoring.preview.knocked_out") : c.above_threshold ? t("scoring.preview.above") : t("scoring.preview.below")}
                    </Typography>
                  </Box>
                );
              })}
            </Box>
          </Box>
        )}
      </Card>

      {/* save + recalculation */}
      {!readOnly && (
        <Card sx={{ p: 2 }}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }}>
            <TextField size="small" label={t("scoring.save.note")} placeholder={t("scoring.save.note_ph")} value={note}
              onChange={(e) => setNote(e.target.value.slice(0, 300))} sx={{ flex: 1 }} />
            {dirty && <Button onClick={undoChanges} disabled={busy}>{t("scoring.undo_changes")}</Button>}
            <Button variant="contained" onClick={() => void save()} disabled={busy || !totalOk || (!dirty && info.source === (jobId ? "job" : "company"))}>
              {busy ? t("scoring.save.saving") : t("scoring.save.button")}
            </Button>
          </Stack>
          <Typography sx={{ fontSize: 13, color: f.muted, mt: 1 }}>
            {!totalOk ? t("scoring.save.need_100") : dirty ? t("scoring.save.unsaved") : t("scoring.save.nothing")}
            {jobId && info.source !== "job" ? ` ${t("scoring.save.job_own")}` : ""}
          </Typography>
          {(savedVersion != null || run) && (
            <Box sx={{ mt: 1.5 }} role="status">
              {savedVersion != null && <Typography sx={{ fontWeight: 700, color: f.ok }}>{t("scoring.save.saved", { version: savedVersion })}</Typography>}
              {run && (
                <Box sx={{ mt: 1 }}>
                  <LinearProgress variant={run.status === "queued" && run.total === 0 ? "indeterminate" : "determinate"} value={pct}
                    color={run.status === "failed" ? "error" : run.status === "done" ? "success" : "primary"} sx={{ height: 8, borderRadius: 4 }} />
                  <Typography sx={{ fontSize: 13, mt: 0.5, color: run.status === "failed" ? f.coral : f.ink }}>
                    {run.status === "failed"
                      ? t("scoring.run.failed", { error: run.error ?? "" })
                      : run.status === "done"
                        ? t("scoring.run.done", { done: run.done, total: run.total, changed: run.changed })
                        : run.status === "queued" && run.total === 0
                          ? t("scoring.run.queued")
                          : t("scoring.run.progress", { done: run.done, total: run.total, changed: run.changed })}
                  </Typography>
                </Box>
              )}
            </Box>
          )}
        </Card>
      )}

      {/* export / import */}
      <Card sx={{ p: 2 }}>
        <Typography variant="h6" component="h3" sx={{ fontWeight: 700 }}>{t("scoring.file.title")}</Typography>
        <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("scoring.file.hint")}</Typography>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Button variant="outlined" onClick={() => void exportAs("xlsx")} disabled={busy}>{t("scoring.export.xlsx")}</Button>
          <Button variant="outlined" onClick={() => void exportAs("json")} disabled={busy}>{t("scoring.export.json")}</Button>
          {!readOnly && (
            <>
              <Button variant="outlined" onClick={() => fileRef.current?.click()} disabled={busy}>{t("scoring.import.button")}</Button>
              <input ref={fileRef} type="file" hidden accept=".json,.xlsx,application/json,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void importFile(file); }} />
            </>
          )}
        </Stack>
      </Card>

      {/* history */}
      <Card sx={{ p: 2 }}>
        <Typography variant="h6" component="h3" sx={{ fontWeight: 700 }}>{t("scoring.history.title")}</Typography>
        <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("scoring.history.hint")}</Typography>
        {info.versions.length === 0 ? (
          <Typography sx={{ color: f.muted, fontSize: 14 }}>{t("scoring.history.none")}</Typography>
        ) : (
          <Stack spacing={0.75}>
            {info.versions.map((v) => (
              <Stack key={v.id} direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}
                sx={{ p: 1.25, borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                <Chip size="small" label={t("scoring.history.version", { version: v.version })}
                  color={v.version === info.version && info.source === (jobId ? "job" : "company") ? "success" : "default"} />
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography sx={{ fontSize: 14, fontWeight: 600 }}>{v.note || t("scoring.history.no_note")}</Typography>
                  <Typography sx={{ fontSize: 12, color: f.muted }}>{t("scoring.history.by", { who: v.created_by ?? "—", when: when(v.created_at) })}</Typography>
                </Box>
                {v.version === info.version && info.source === (jobId ? "job" : "company") ? (
                  <Typography sx={{ fontSize: 13, color: f.ok, fontWeight: 700 }}>{t("scoring.history.in_use")}</Typography>
                ) : !readOnly && (
                  <Button size="small" onClick={() => setConfirmRevert(v.version)} disabled={busy}>{t("scoring.history.revert")}</Button>
                )}
              </Stack>
            ))}
          </Stack>
        )}
      </Card>

      <Dialog open={confirmRevert != null} onClose={() => setConfirmRevert(null)}>
        <DialogTitle>{t("scoring.history.confirm_title", { version: confirmRevert ?? "" })}</DialogTitle>
        <DialogContent><Typography>{t("scoring.history.confirm_body")}</Typography></DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmRevert(null)}>{t("action.cancel")}</Button>
          <Button variant="contained" onClick={() => confirmRevert != null && void revert(confirmRevert)}>{t("scoring.history.revert")}</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={confirmCompany} onClose={() => setConfirmCompany(false)}>
        <DialogTitle>{t("scoring.use_company.confirm_title")}</DialogTitle>
        <DialogContent><Typography>{t("scoring.use_company.confirm_body")}</Typography></DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmCompany(false)}>{t("action.cancel")}</Button>
          <Button variant="contained" onClick={() => void backToCompany()}>{t("scoring.use_company")}</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
