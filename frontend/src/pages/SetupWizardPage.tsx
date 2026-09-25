import { useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Step from "@mui/material/Step";
import StepButton from "@mui/material/StepButton";
import Stepper from "@mui/material/Stepper";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { experienceApi, extractErrorMessage, type SetupProgress } from "../api/client";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";

// Part 14 section 1 (docs/HRMS_COMPLETE_SPEC.txt; decision A5): the client admin finishes
// setup here. Progress is computed on the server from real data, so a step shows "done"
// because the thing exists (a tested mailbox, imported employees...), not because someone
// clicked Next. Steps whose editor already exists elsewhere link straight to it.

const STEP_LABELS: Record<string, string> = {
  company: "Company details", entities_locations: "Entities & locations", branding: "Branding", mailbox: "Connect your mailbox",
  import_employees: "Import employees", modules: "Choose modules", config_pack: "Apply a configuration pack", invite_admins: "Invite admins",
};
const ELSEWHERE: Record<string, { text: string; path: string }> = {
  entities_locations: { text: "Add at least one legal entity and one location in Core HR.", path: "/settings#core-hr" },
  branding: { text: "Upload your logo and set colours in Branding.", path: "/settings#branding" },
  mailbox: { text: "Connect your organisation's mailbox (SMTP/IMAP, password or OAuth2) and send a test email.", path: "/settings#connections" },
  import_employees: { text: "Use the Excel import wizard (preview → dry run → commit).", path: "/settings#core-hr" },
};
const MODULE_OPTIONS = [
  { code: "onboarding", label: "Pre-boarding & onboarding" }, { code: "core_hr", label: "Core HR" }, { code: "performance", label: "Performance & goals" },
  { code: "helpdesk", label: "Helpdesk" }, { code: "assets", label: "Assets" }, { code: "separation", label: "Exit & separation" },
  { code: "analytics", label: "Analytics & report builder" }, { code: "copilot", label: "HR Copilot" },
];

export default function SetupWizardPage() {
  const [params, setParams] = useSearchParams();
  const { data: me, reload } = useMeBootstrap();
  const [progress, setProgress] = useState<SetupProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [company, setCompany] = useState({ display_name: "", legal_name: "", timezone: "Asia/Kolkata" });
  const [modules, setModules] = useState<string[]>(me?.modules ?? MODULE_OPTIONS.map((m) => m.code));
  const [invite, setInvite] = useState("");
  const [packText, setPackText] = useState("");

  const load = () => experienceApi.setupProgress().then(setProgress).catch((err) => setError(extractErrorMessage(err, "Failed to load setup progress")));
  useEffect(() => {
    load();
  }, []);

  const steps = progress?.steps ?? [];
  const current = params.get("step") ?? steps.find((s) => !s.done)?.step ?? "company";
  const index = Math.max(0, steps.findIndex((s) => s.step === current));
  const step = steps[index];
  const goto = (name: string) => setParams({ step: name });
  const after = (p: SetupProgress, message: string) => {
    setProgress(p);
    setNotice(message);
    setError(null);
    const next = p.steps.find((s) => !s.done);
    if (next) goto(next.step);
  };
  const fail = (fallback: string) => (err: unknown) => setError(extractErrorMessage(err, fallback));

  return (
    <Box sx={{ maxWidth: 960 }}>
      <Typography variant="h5" component="h1" gutterBottom>Set up your organisation</Typography>
      {progress && (
        <Box sx={{ mb: 2 }}>
          <LinearProgress variant="determinate" value={progress.percent} aria-label={`Setup ${progress.percent}% complete`} />
          <Typography variant="caption" color="text.secondary">{progress.percent}% complete</Typography>
        </Box>
      )}
      <Stepper nonLinear activeStep={index} alternativeLabel sx={{ mb: 3, display: { xs: "none", md: "flex" } }}>
        {steps.map((s) => (
          <Step key={s.step} completed={s.done}>
            <StepButton onClick={() => goto(s.step)}>{STEP_LABELS[s.step]}</StepButton>
          </Step>
        ))}
      </Stepper>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>{notice}</Alert>}
      {progress?.complete && <Alert severity="success" sx={{ mb: 2 }}>Setup is complete. The checklist has been removed from your home page.</Alert>}

      {step && (
        <Card>
          <CardContent>
            <Typography variant="h6" gutterBottom>{STEP_LABELS[step.step]}</Typography>
            <Typography color="text.secondary" gutterBottom>{step.done ? "Done: " : "Status: "}{step.detail}</Typography>

            {step.step === "company" && (
              <Stack spacing={2} sx={{ maxWidth: 480, mt: 1 }} component="form" onSubmit={(e) => { e.preventDefault(); experienceApi.setCompany(company).then((p) => after(p, "Company details saved.")).catch(fail("Save failed")); }}>
                <TextField label="Display name" required value={company.display_name} onChange={(e) => setCompany({ ...company, display_name: e.target.value })} helperText="Shown in the app, emails and the career site." />
                <TextField label="Legal name" value={company.legal_name} onChange={(e) => setCompany({ ...company, legal_name: e.target.value })} helperText="Used on letters. Defaults to the display name." />
                <TextField label="Timezone" required value={company.timezone} onChange={(e) => setCompany({ ...company, timezone: e.target.value })} helperText="IANA name, e.g. Asia/Kolkata." />
                <Button type="submit" variant="contained" disabled={!company.display_name}>Save</Button>
              </Stack>
            )}

            {ELSEWHERE[step.step] && (
              <Stack spacing={1} sx={{ mt: 1 }}>
                <Typography>{ELSEWHERE[step.step].text}</Typography>
                <Button component={RouterLink} to={ELSEWHERE[step.step].path} variant="outlined" sx={{ alignSelf: "flex-start" }}>Open</Button>
                <Button onClick={load} sx={{ alignSelf: "flex-start" }}>I've done this — check again</Button>
              </Stack>
            )}

            {step.step === "modules" && (
              <Stack sx={{ mt: 1 }}>
                {MODULE_OPTIONS.map((m) => (
                  <FormControlLabel key={m.code} label={m.label}
                    control={<Checkbox checked={modules.includes(m.code)} onChange={(e) => setModules((prev) => (e.target.checked ? [...prev, m.code] : prev.filter((c) => c !== m.code)))} />} />
                ))}
                <Button variant="contained" sx={{ alignSelf: "flex-start", mt: 1 }}
                  onClick={() => experienceApi.setModules(modules).then((p) => { reload(); after(p, "Modules saved -- the menu now shows exactly these."); }).catch(fail("Save failed"))}>Save modules</Button>
              </Stack>
            )}

            {step.step === "config_pack" && (
              <Stack spacing={1} sx={{ mt: 1 }}>
                <Typography variant="body2">Paste a configuration pack (exported from another environment with hrctl config-pack export). It is checked first; nothing is written until you apply it.</Typography>
                <TextField multiline minRows={6} value={packText} onChange={(e) => setPackText(e.target.value)} inputProps={{ "aria-label": "Configuration pack JSON" }} />
                <Stack direction="row" spacing={1}>
                  <Button onClick={() => { try { experienceApi.applyConfigPack(JSON.parse(packText), true).then((r) => setNotice(`Check passed: ${JSON.stringify(r.tables)}`)).catch(fail("Check failed")); } catch { setError("That isn't valid JSON."); } }}>Check</Button>
                  <Button variant="contained" onClick={() => { try { experienceApi.applyConfigPack(JSON.parse(packText), false).then(() => load().then(() => setNotice("Configuration pack applied."))).catch(fail("Apply failed")); } catch { setError("That isn't valid JSON."); } }}>Apply</Button>
                </Stack>
              </Stack>
            )}

            {step.step === "invite_admins" && (
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}>
                <TextField label="Admin email" type="email" value={invite} onChange={(e) => setInvite(e.target.value)} />
                <Button variant="contained" disabled={!invite}
                  onClick={() => experienceApi.inviteAdmin(invite).then((r) => { setInvite(""); setNotice(r.email_sent ? "Invitation sent." : `Email couldn't be sent yet -- share this one-time link: ${r.link}`); load(); }).catch(fail("Invite failed"))}>Invite</Button>
              </Stack>
            )}

            {!step.done && step.skippable && (
              <Button color="inherit" sx={{ mt: 2 }} onClick={() => experienceApi.skipStep(step.step).then((p) => after(p, `Skipped "${STEP_LABELS[step.step]}". You can come back any time.`)).catch(fail("Skip failed"))}>Skip for now</Button>
            )}
            {step.skipped && (
              <Button color="inherit" sx={{ mt: 2 }} onClick={() => experienceApi.skipStep(step.step, true).then(setProgress).catch(fail("Failed"))}>Un-skip</Button>
            )}
          </CardContent>
        </Card>
      )}
    </Box>
  );
}
