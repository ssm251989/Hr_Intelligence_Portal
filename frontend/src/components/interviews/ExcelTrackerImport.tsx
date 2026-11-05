// Part 17.12: Settings > Data & privacy > Imports -- the ONE-TIME "Import from old Excel
// tracker": reads its "Interviewer Pool" + "Mails" sheets, shows what it will create, then
// copies them into the app (pools + interviewers). After that the file is never used again.
import { useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { interviewersApi, type TrackerImport } from "../../api/interviewersApi";
import { downloadBlob } from "../../api/scoringApi";
import { useT } from "../../i18n";
import { Emoji, FriendlyError } from "../../ui-kit";

export default function ExcelTrackerImport() {
  const t = useT();
  const [file, setFile] = useState<File | null>(null);
  const [check, setCheck] = useState<TrackerImport | null>(null);
  const [done, setDone] = useState<TrackerImport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const run = async (dry: boolean) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await interviewersApi.importExcel(file, dry);
      if (dry) setCheck(r);
      else { setDone(r); setCheck(null); setFile(null); }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
        <Emoji name="page" size={20} />
        <Typography sx={{ fontWeight: 700 }}>{t("interviewers.import.title")}</Typography>
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{t("interviewers.import.intro")}</Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Button variant="outlined" component="label" size="small">
          {file ? file.name : t("interviewers.import.choose")}
          <input hidden type="file" accept=".xlsx" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setCheck(null); setDone(null); e.target.value = ""; }} />
        </Button>
        <Button size="small" onClick={() => interviewersApi.importSample().then((b) => b && downloadBlob(b, "interviewer-tracker-sample.xlsx"))}>{t("interviewers.import.sample")}</Button>
        {file && !check && <Button size="small" variant="contained" disabled={busy} onClick={() => run(true)}>{t("interviewers.import.check")}</Button>}
      </Stack>
      {check && (
        <Alert severity={check.names_without_email.length ? "warning" : "info"} sx={{ mt: 1.5 }}
          action={<Button color="inherit" disabled={busy} onClick={() => run(false)}>{t("interviewers.import.copy")}</Button>}>
          {t("interviewers.import.plan", { pools: check.pools, people: check.interviewers })}
          {check.names_without_email.length > 0 && <div>{t("interviewers.import.no_email", { list: check.names_without_email.join(", ") })}</div>}
        </Alert>
      )}
      {done && <Alert severity="success" sx={{ mt: 1.5 }}>{t("interviewers.import.done", { pools: done.created_pools ?? 0, people: done.created_interviewers ?? 0 })}</Alert>}
      {error ? <Box sx={{ mt: 1 }}><FriendlyError error={error} compact /></Box> : null}
    </Box>
  );
}
