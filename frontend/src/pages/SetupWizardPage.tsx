// Part 14 section 1 / Part 17.10: the client admin finishes setup here. Every step opens a
// working form that saves, shows what is saved when reopened and can be edited again. Progress
// comes from the server's real data: a step turns green only after a real save; a skipped step
// is shown as skipped (never as done).
import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import FormControlLabel from "@mui/material/FormControlLabel";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Step from "@mui/material/Step";
import StepButton from "@mui/material/StepButton";
import Stepper from "@mui/material/Stepper";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { apiUrl, experienceApi, type SetupProgress } from "../api/client";
import { downloadBlob } from "../api/scoringApi";
import { setupApi, type EmployeesFileResult, type SetupValues } from "../api/setupApi";
import { useBootstrap } from "../bootstrap/BootstrapContext";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import LogoUploader from "../components/branding/LogoUploader";
import { useT } from "../i18n";
import { Emoji, FriendlyError, PageHeader, StatusChip } from "../ui-kit";

const TIMEZONES = ["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "America/New_York", "UTC"];
const LOCALES = ["en-IN", "hi-IN", "ta-IN", "en-GB", "en-US"];
const CURRENCIES = ["INR", "USD", "AED", "SGD", "GBP", "EUR"];

export default function SetupWizardPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [params, setParams] = useSearchParams();
  const { reload: reloadMe } = useMeBootstrap();
  const { reload: reloadBranding } = useBootstrap();
  const [progress, setProgress] = useState<SetupProgress | null>(null);
  const [values, setValues] = useState<SetupValues | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [company, setCompany] = useState({ display_name: "", legal_name: "", timezone: "Asia/Kolkata", locale: "en-IN", currency: "INR" });
  const [office, setOffice] = useState({ entity_name: "", location_name: "", city: "" });
  const [colour, setColour] = useState("#0E7C66");
  // Part 18.5: only the modules that exist, are allowed and are offered (from the server)
  const [moduleCodes, setModuleCodes] = useState<string[]>([]);
  const [modules, setModules] = useState<string[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [check, setCheck] = useState<EmployeesFileResult | null>(null);

  const load = useCallback(() => Promise.all([experienceApi.setupProgress(), setupApi.values()]).then(([p, v]) => {
    setProgress(p);
    setValues(v);
    // show what is saved (Part 17.10: reopening a step shows the saved values)
    setCompany({
      display_name: v.company.display_name ?? "", legal_name: v.company.legal_name ?? "", timezone: v.company.timezone ?? "Asia/Kolkata",
      locale: v.company.locale ?? "en-IN", currency: v.company.currency ?? "INR",
    });
    setOffice((o) => ({ ...o, entity_name: o.entity_name || v.entities[0]?.name || v.company.legal_name || "" }));
    if (v.branding.primary_color) setColour(v.branding.primary_color);
    const offered = (v.available_modules ?? []).map((m) => m.code);
    setModuleCodes(offered);
    setModules((v.available_modules ?? []).filter((m) => m.on).map((m) => m.code));
  }).catch(setError), []);
  useEffect(() => { load(); }, [load]);

  const steps = progress?.steps ?? [];
  const current = params.get("step") ?? steps.find((s) => !s.done && !s.skipped)?.step ?? "company";
  const index = Math.max(0, steps.findIndex((s) => s.step === current));
  const step = steps[index];
  const goto = (name: string) => { setParams({ step: name }); setNotice(null); setError(null); };

  const run = async (action: () => Promise<unknown>, message: string, next = true) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
      setNotice(message);
      if (next) {
        const p = await experienceApi.setupProgress();
        const upcoming = p.steps.find((s, i) => i > index && !s.done && !s.skipped);
        if (upcoming) setParams({ step: upcoming.step });
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const chip = (s: { done: boolean; skipped: boolean }) =>
    s.done ? <StatusChip tone="ok" emoji="check" label={t("setup.state.done")} />
      : s.skipped ? <StatusChip tone="muted" emoji="pause" label={t("setup.state.skipped")} />
      : <StatusChip tone="sun" emoji="hourglass" label={t("setup.state.todo")} />;

  return (
    <Box>
      <PageHeader emoji="rocket" title={t("setup.title")} purpose={t("setup.purpose")} />
      {progress && (
        <Box sx={{ mb: 2 }}>
          <LinearProgress variant="determinate" value={progress.percent} aria-label={t("setup.progress_aria", { pct: progress.percent })} />
          <Typography variant="caption" color="text.secondary">{t("setup.progress", { pct: progress.percent })}</Typography>
        </Box>
      )}
      <Stepper nonLinear activeStep={index} alternativeLabel sx={{ mb: 3, display: { xs: "none", md: "flex" } }}>
        {steps.map((s) => (
          <Step key={s.step} completed={s.done}>
            <StepButton onClick={() => goto(s.step)} optional={s.skipped ? <Typography variant="caption">{t("setup.state.skipped")}</Typography> : undefined}>
              {t(`setup.step.${s.step}`)}
            </StepButton>
          </Step>
        ))}
      </Stepper>
      <Stack direction="row" spacing={1} sx={{ mb: 2, display: { xs: "flex", md: "none" }, overflowX: "auto" }}>
        {steps.map((s) => <Chip key={s.step} label={t(`setup.step.${s.step}`)} color={s.done ? "success" : "default"} variant={s.step === current ? "filled" : "outlined"} onClick={() => goto(s.step)} />)}
      </Stack>
      {error ? <Box sx={{ mb: 2 }}><FriendlyError error={error} compact /></Box> : null}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}
      {progress?.complete && <Alert severity="success" sx={{ mb: 2 }}>{t("setup.complete")}</Alert>}

      {!progress || !values ? <CircularProgress aria-label={t("setup.loading")} /> : step && (
        <Card>
          <CardContent>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
              <Typography variant="h6" component="h2" sx={{ flex: 1 }}>{t(`setup.step.${step.step}`)}</Typography>
              {chip(step)}
            </Stack>
            <Typography sx={{ color: f.muted, mb: 2 }}>{t(`setup.hint.${step.step}`)}</Typography>

            {step.step === "company" && (
              <Stack spacing={2} sx={{ maxWidth: 480 }} component="form" onSubmit={(e) => { e.preventDefault(); run(() => experienceApi.setCompany(company).then(() => reloadBranding()), t("setup.saved.company")); }}>
                <TextField label={t("setup.company.display_name")} required value={company.display_name} onChange={(e) => setCompany({ ...company, display_name: e.target.value })} helperText={t("setup.company.display_name_hint")} />
                <TextField label={t("setup.company.legal_name")} value={company.legal_name} onChange={(e) => setCompany({ ...company, legal_name: e.target.value })} helperText={t("setup.company.legal_name_hint")} />
                <TextField select label={t("setup.company.timezone")} value={company.timezone} onChange={(e) => setCompany({ ...company, timezone: e.target.value })}>
                  {[...new Set([company.timezone, ...TIMEZONES])].map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
                </TextField>
                <Stack direction="row" spacing={2}>
                  <TextField select fullWidth label={t("setup.company.locale")} value={company.locale} onChange={(e) => setCompany({ ...company, locale: e.target.value })}>
                    {[...new Set([company.locale, ...LOCALES])].map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
                  </TextField>
                  <TextField select fullWidth label={t("setup.company.currency")} value={company.currency} onChange={(e) => setCompany({ ...company, currency: e.target.value })}>
                    {[...new Set([company.currency, ...CURRENCIES])].map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
                  </TextField>
                </Stack>
                <Button type="submit" variant="contained" disabled={busy || !company.display_name} sx={{ alignSelf: "flex-start" }}>{t("setup.save")}</Button>
              </Stack>
            )}

            {step.step === "entities_locations" && (
              <Stack spacing={2} sx={{ maxWidth: 520 }}>
                {(values.entities.length > 0 || values.locations.length > 0) && (
                  <Box>
                    <Typography sx={{ fontWeight: 700, fontSize: 14 }}>{t("setup.office.saved")}</Typography>
                    <Typography sx={{ fontSize: 14, color: f.muted }}>{t("setup.office.entities", { list: values.entities.map((e) => e.name).join(", ") || "—" })}</Typography>
                    <Typography sx={{ fontSize: 14, color: f.muted }}>{t("setup.office.locations", { list: values.locations.map((l) => l.name + (l.state ? ` (${l.state})` : "")).join(", ") || "—" })}</Typography>
                  </Box>
                )}
                <TextField label={t("setup.office.entity_name")} required value={office.entity_name} onChange={(e) => setOffice({ ...office, entity_name: e.target.value })} helperText={t("setup.office.entity_hint")} />
                <TextField label={t("setup.office.location_name")} required value={office.location_name} onChange={(e) => setOffice({ ...office, location_name: e.target.value })} placeholder={t("setup.office.location_ph")} />
                <TextField label={t("setup.office.city")} value={office.city} onChange={(e) => setOffice({ ...office, city: e.target.value })} helperText={t("setup.office.city_hint")} />
                <Button variant="contained" disabled={busy || !office.entity_name.trim() || !office.location_name.trim()} sx={{ alignSelf: "flex-start" }}
                  onClick={() => run(() => setupApi.addEntityLocation(office).then(() => setOffice((o) => ({ ...o, location_name: "", city: "" }))), t("setup.saved.office"))}>
                  {t("setup.office.add")}
                </Button>
                <Button component={RouterLink} to="/settings/onboarding/org" sx={{ alignSelf: "flex-start" }}>{t("setup.office.more")}</Button>
              </Stack>
            )}

            {step.step === "branding" && (
              <Stack spacing={2.5} sx={{ maxWidth: 560 }}>
                <LogoUploader currentUrl={apiUrl(values.branding.logo_url)} onSaved={() => { reloadBranding(); load(); setNotice(t("setup.saved.logo")); }} />
                <Stack direction="row" spacing={2} alignItems="center">
                  <TextField type="color" label={t("setup.brand.colour")} value={colour} onChange={(e) => setColour(e.target.value)} sx={{ width: 140 }} />
                  <Box sx={{ px: 2, py: 1, borderRadius: "10px", bgcolor: colour, color: "#fff", fontWeight: 700 }}>{t("setup.brand.sample")}</Box>
                  <Button variant="contained" disabled={busy} onClick={() => run(() => setupApi.saveBrandColours({ primary_color: colour }).then(() => reloadBranding()), t("setup.saved.colour"), false)}>{t("setup.save")}</Button>
                </Stack>
              </Stack>
            )}

            {step.step === "mailbox" && (
              <Stack spacing={1.5}>
                <Alert severity={values.mailbox.connected ? "success" : "info"}>{values.mailbox.detail}</Alert>
                <Stack direction="row" spacing={1}>
                  <Button variant="contained" component={RouterLink} to="/settings/communication/mailboxes">{values.mailbox.connected ? t("setup.mailbox.open") : t("setup.mailbox.connect")}</Button>
                  <Button onClick={() => run(async () => undefined, t("setup.checked"), false)}>{t("setup.check_again")}</Button>
                </Stack>
              </Stack>
            )}

            {step.step === "import_employees" && (
              <Stack spacing={1.5} sx={{ maxWidth: 560 }}>
                <Typography sx={{ fontSize: 14 }}>{t("setup.people.count", { count: values.employees.count })}</Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Button variant="outlined" component="label" startIcon={<Emoji name="page" size={16} />}>
                    {file ? file.name : t("setup.people.choose")}
                    <input hidden type="file" accept=".csv,.xlsx" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setCheck(null); e.target.value = ""; }} />
                  </Button>
                  <Button onClick={() => setupApi.employeesSample().then((b) => b && downloadBlob(b, "employees-sample.csv"))}>{t("setup.people.sample")}</Button>
                </Stack>
                {file && !check && <Button variant="contained" disabled={busy} sx={{ alignSelf: "flex-start" }}
                  onClick={() => run(() => setupApi.employeesFile(file, false).then(setCheck), t("setup.people.checked"), false)}>{t("setup.people.check")}</Button>}
                {check && check.committed === 0 && (
                  <Alert severity={check.errors ? "warning" : "success"}
                    action={<Button color="inherit" disabled={busy || check.rows === check.errors}
                      onClick={() => run(() => setupApi.employeesFile(file as File, true).then((r) => { setCheck(r); setFile(null); }), t("setup.saved.people"))}>
                      {t("setup.people.add", { count: check.rows - check.errors })}</Button>}>
                    {t("setup.people.result", { rows: check.rows, errors: check.errors })}
                  </Alert>
                )}
                <Button component={RouterLink} to="/people?view=hr" sx={{ alignSelf: "flex-start" }}>{t("setup.people.open")}</Button>
              </Stack>
            )}

            {step.step === "modules" && (
              <Stack>
                {moduleCodes.map((m) => (
                  <FormControlLabel key={m} label={t(`setup.module.${m}`)}
                    control={<Checkbox checked={modules.includes(m)} onChange={(e) => setModules((prev) => (e.target.checked ? [...prev, m] : prev.filter((c) => c !== m)))} />} />
                ))}
                <Button variant="contained" disabled={busy} sx={{ alignSelf: "flex-start", mt: 1 }}
                  onClick={() => run(() => experienceApi.setModules(modules).then(() => reloadMe()), t("setup.saved.modules"))}>{t("setup.save")}</Button>
              </Stack>
            )}

            <Stack direction="row" spacing={1} sx={{ mt: 3 }}>
              {!step.done && !step.skipped && step.skippable && (
                <Button color="inherit" disabled={busy} onClick={() => run(() => experienceApi.skipStep(step.step), t("setup.skipped_msg", { step: t(`setup.step.${step.step}`) }))}>{t("setup.skip")}</Button>
              )}
              {step.skipped && (
                <Button color="inherit" disabled={busy} onClick={() => run(() => experienceApi.skipStep(step.step, true), t("setup.unskipped"), false)}>{t("setup.unskip")}</Button>
              )}
            </Stack>
          </CardContent>
        </Card>
      )}
    </Box>
  );
}
