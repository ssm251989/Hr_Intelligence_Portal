import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import LinearProgress from "@mui/material/LinearProgress";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { experienceApi, type HealthIssue, type SetupProgress } from "../api/client";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";

// Part 14 sections 1-2 / L-A3: on the admin home, the setup checklist stays until setup is
// 100%, and configuration-health problems (errors first) are always listed with a direct
// link to the page that fixes each one. Hidden for anyone who can't configure settings.

export default function AdminHomeChecklist() {
  const { can } = useMeBootstrap();
  const [progress, setProgress] = useState<SetupProgress | null>(null);
  const [issues, setIssues] = useState<HealthIssue[]>([]);
  const allowed = can("platform.settings.configure");

  useEffect(() => {
    if (!allowed) return;
    experienceApi.setupProgress().then(setProgress).catch(() => undefined);
    experienceApi.configHealth().then((r) => setIssues(r.issues)).catch(() => undefined);
  }, [allowed]);

  if (!allowed || (!progress && issues.length === 0) || (progress?.complete && issues.length === 0)) return null;

  return (
    <Stack spacing={2} sx={{ mb: 3 }}>
      {progress && !progress.complete && (
        <Card>
          <CardContent>
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Typography variant="h6">Finish setting up ({progress.percent}%)</Typography>
              <Button component={RouterLink} to="/setup" variant="contained">Continue setup</Button>
            </Stack>
            <LinearProgress variant="determinate" value={progress.percent} sx={{ my: 1 }} aria-label="Setup progress" />
            <List dense>
              {progress.steps.filter((s) => !s.done).slice(0, 4).map((s) => (
                <ListItem key={s.step} secondaryAction={<Button size="small" component={RouterLink} to={s.fix_path}>Open</Button>}>
                  <ListItemText primary={s.step.replace(/_/g, " ")} secondary={s.detail} />
                </ListItem>
              ))}
            </List>
          </CardContent>
        </Card>
      )}
      {issues.length > 0 && (
        <Card>
          <CardContent>
            <Typography variant="h6" gutterBottom>Configuration health</Typography>
            {issues.slice(0, 6).map((issue, i) => (
              <Alert key={`${issue.code}-${i}`} severity={issue.severity} sx={{ mb: 1 }}
                action={issue.fix_path ? <Button size="small" component={RouterLink} to={issue.fix_path}>Fix</Button> : undefined}>
                <strong>{issue.message}</strong> {issue.fix}
              </Alert>
            ))}
            {issues.length > 6 && <Typography variant="caption" color="text.secondary">{issues.length - 6} more on the Setup page.</Typography>}
          </CardContent>
        </Card>
      )}
    </Stack>
  );
}
