import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { jobsExtraApi, type JobPipelineRow } from "../../api/jobsExtra";
import type { JobRoleRead } from "../../api/types";
import { useT } from "../../i18n";
import { Emoji, FriendlyError, InfoTip } from "../../ui-kit";

// J5: a closed job (by hand or by itself) can be reopened. A new closing date and/or more
// openings stop it from closing again straight away.
export default function ReopenJobDialog({
  job, pipeline, onClose, onReopened,
}: {
  job: JobRoleRead | null;
  pipeline?: JobPipelineRow;
  onClose: () => void;
  onReopened: (job: JobRoleRead) => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const hired = pipeline?.hired ?? 0;
  const [deadline, setDeadline] = useState("");
  const [openings, setOpenings] = useState("1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!job) return;
    setDeadline("");
    setOpenings(String(Math.max(job.positions_count ?? 1, hired + 1)));
    setError(null);
  }, [job, hired]);

  const today = new Date().toISOString().slice(0, 10);
  const openingsNum = Number(openings);
  const invalid = !Number.isFinite(openingsNum) || openingsNum < 1 || openingsNum <= hired;

  const submit = async () => {
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      await jobsExtraApi.reopen(job.id, { application_deadline: deadline || null, positions_count: openingsNum });
      onReopened({ ...job, status: "published", positions_count: openingsNum, publish_settings: { ...job.publish_settings, application_deadline: deadline || null } });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={job !== null} onClose={busy ? undefined : onClose} fullWidth maxWidth="xs" aria-labelledby="reopen-job-title">
      <DialogTitle id="reopen-job-title" sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <Emoji name="key" size={22} />
        {job ? t("jobs.reopen.title", { title: job.title }) : ""}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2.5} sx={{ pt: 0.5 }}>
          <Typography sx={{ color: f.muted }}>{t("jobs.reopen.intro")}</Typography>
          <Box>
            <Stack direction="row" alignItems="center" sx={{ mb: 0.75 }}>
              <Typography component="label" htmlFor="reopen-openings" sx={{ fontWeight: 600, fontSize: 14 }}>{t("jobs.reopen.openings")}</Typography>
              <InfoTip text={t("jobs.reopen.openings_tip", { hired })} />
            </Stack>
            <TextField id="reopen-openings" type="number" size="small" fullWidth value={openings} onChange={(e) => setOpenings(e.target.value)}
              slotProps={{ htmlInput: { min: hired + 1 } }} error={invalid}
              helperText={invalid ? t("jobs.reopen.openings_low", { hired }) : undefined} />
          </Box>
          <Box>
            <Stack direction="row" alignItems="center" sx={{ mb: 0.75 }}>
              <Typography component="label" htmlFor="reopen-deadline" sx={{ fontWeight: 600, fontSize: 14 }}>{t("jobs.reopen.deadline")}</Typography>
              <InfoTip text={t("jobs.reopen.deadline_tip")} />
            </Stack>
            <TextField id="reopen-deadline" type="date" size="small" fullWidth value={deadline} onChange={(e) => setDeadline(e.target.value)}
              slotProps={{ htmlInput: { min: today } }} />
          </Box>
          {error != null && <FriendlyError compact error={error} />}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={submit} disabled={busy || invalid}>{t("jobs.reopen.confirm")}</Button>
      </DialogActions>
    </Dialog>
  );
}
