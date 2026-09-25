import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, onboardingApi, type BgvCaseRow, type OnboardingDashboard, type PreboardingCaseRow } from "../api/client";

// Part 9 (docs/HRMS_COMPLETE_SPEC.txt): onboarding dashboard + pre-boarding cases + BGV
// status -- an HR admin surface. The new-hire portal itself is the public
// /api/v1/public/onboarding/portal/{token} API; its mobile page is not built yet (see
// docs/build_log.md's own Part 9 note).

export default function OnboardingPanel() {
  const [summary, setSummary] = useState<OnboardingDashboard | null>(null);
  const [cases, setCases] = useState<PreboardingCaseRow[]>([]);
  const [bgvCases, setBgvCases] = useState<BgvCaseRow[]>([]);
  const [form, setForm] = useState({ email: "", first_name: "", joining_date: "" });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = () => {
    onboardingApi.dashboard().then(setSummary).catch((err) => setError(extractErrorMessage(err, "Failed to load onboarding dashboard")));
    onboardingApi.cases().then(setCases).catch(() => undefined);
    onboardingApi.bgvCases().then(setBgvCases).catch(() => undefined);
  };

  useEffect(load, []);

  const createCase = () => {
    setError(null);
    onboardingApi
      .createCase(form)
      .then((row) => {
        setNotice(`Case created for ${row.email}. Send the portal link from Communications.`);
        setForm({ email: "", first_name: "", joining_date: "" });
        load();
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to create case")));
  };

  const convert = (row: PreboardingCaseRow) => {
    onboardingApi
      .convert(row.id)
      .then((res) => {
        setNotice(`${row.email} is now employee ${res.employee_code}.`);
        load();
      })
      .catch((err) => setError(extractErrorMessage(err, "Conversion failed")));
  };

  return (
    <Card sx={{ mt: 3 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Pre-boarding & onboarding
        </Typography>
        {error && <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>{error}</Alert>}
        {notice && <Alert severity="success" onClose={() => setNotice(null)} sx={{ mb: 2 }}>{notice}</Alert>}

        {summary && (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
            <Chip label={`Upcoming joiners: ${summary.upcoming_joiners.length}`} />
            <Chip label={`Documents to verify: ${summary.documents_pending_verification}`} />
            <Chip label={`Overdue tasks: ${Object.values(summary.overdue_tasks_by_owner).reduce((a, b) => a + b, 0)}`} />
            <Chip label={`Offer-to-join drop-off: ${summary.offer_to_join_drop_off_percent}%`} />
          </Stack>
        )}

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 2 }}>
          <TextField size="small" label="Email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <TextField size="small" label="First name" required value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          <TextField size="small" type="date" label="Joining date" required InputLabelProps={{ shrink: true }} value={form.joining_date} onChange={(e) => setForm({ ...form, joining_date: e.target.value })} />
          <Button variant="contained" onClick={createCase} disabled={!form.email || !form.first_name || !form.joining_date}>
            Start pre-boarding
          </Button>
        </Stack>

        {cases.length === 0 ? (
          <Typography color="text.secondary">No pre-boarding cases yet. Start one above when a candidate accepts an offer.</Typography>
        ) : (
          <List dense>
            {cases.map((row) => {
              const joiner = summary?.upcoming_joiners.find((j) => j.case_id === row.id);
              return (
                <ListItem
                  key={row.id}
                  secondaryAction={
                    row.status !== "joined" && row.status !== "revoked" && row.status !== "no_show" ? (
                      <Box>
                        <Button size="small" onClick={() => convert(row)}>Mark joined</Button>
                        <Button size="small" color="warning" onClick={() => onboardingApi.noShow(row.id).then(load)}>No-show</Button>
                      </Box>
                    ) : null
                  }
                >
                  <ListItemText
                    primary={`${row.email} — joins ${row.joining_date}`}
                    secondary={`${row.status}${joiner ? ` · ${joiner.readiness_percent}% ready` : ""}`}
                  />
                </ListItem>
              );
            })}
          </List>
        )}

        {bgvCases.length > 0 && (
          <>
            <Typography variant="subtitle1" sx={{ mt: 2 }}>Background verification</Typography>
            <List dense>
              {bgvCases.map((row) => (
                <ListItem key={row.id}>
                  <ListItemText primary={`${row.status} · decision: ${row.decision}`} secondary={row.checks.map((c) => `${c.type}: ${c.status}`).join(", ")} />
                </ListItem>
              ))}
            </List>
          </>
        )}
      </CardContent>
    </Card>
  );
}
