import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { Link as RouterLink } from "react-router-dom";

import { interviewSchedulingApi, type SchedulingProblem } from "../../api/client";
import { useT } from "../../i18n";

// fix 2026-10-04: on the job, every shortlisted candidate whose interview isn't being arranged,
// with the plain reason and what to do -- never silent.
export default function JobSchedulingProblems({ jobId }: { jobId: string }) {
  const t = useT();
  const [rows, setRows] = useState<SchedulingProblem[]>([]);
  useEffect(() => { interviewSchedulingApi.problems(jobId).then(setRows).catch(() => setRows([])); }, [jobId]);
  if (!rows.length) return null;
  return (
    <Stack spacing={1}>
      {rows.map((p) => (
        <Alert key={p.application_id} severity="error"
          action={(
            <Stack direction="row" spacing={1}>
              {p.kind === "mailbox"
                ? <Button size="small" color="inherit" component={RouterLink} to="/settings/communication/mailboxes">{t("home.alert.action.fix_mailbox")}</Button>
                : <Button size="small" color="inherit" component={RouterLink} to="/interviews/interviewers">{t("home.alert.action.add_availability")}</Button>}
              <Button size="small" color="inherit" component={RouterLink} to={`/candidates/${p.application_id}?book=1`}>{t("home.alert.action.schedule_manually")}</Button>
            </Stack>
          )}>
          <Typography sx={{ fontSize: 13.5 }}>
            {p.kind === "mailbox" ? t("home.alert.interview_email_not_sent", { name: p.name }) : t("home.alert.interview_not_scheduled", { name: p.name, reason: p.reason ?? "" })}
          </Typography>
        </Alert>
      ))}
    </Stack>
  );
}
