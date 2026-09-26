import { useMemo, useState } from "react";
import SearchIcon from "@mui/icons-material/Search";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Grid from "@mui/material/Grid";
import InputAdornment from "@mui/material/InputAdornment";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import type { JobRoleRead } from "../../api/types";
import { useT } from "../../i18n";
import { EmptyState, Emoji, StatusChip } from "../../ui-kit";

// J2 template library. The backend has no separate "job template" store, so -- simply and
// honestly -- a template is any job you have posted before: picking one copies its fields
// into a NEW job (the original is never changed).
export function skillCount(job: JobRoleRead): number {
  return [job.technical_skills_must_have, job.technical_skills_good_to_have, job.soft_skills_must_have, job.soft_skills_good_to_have]
    .reduce((n, list) => n + (list?.length ?? 0), 0);
}

export default function JobTemplateLibrary({
  open, jobs, onClose, onPick,
}: {
  open: boolean;
  jobs: JobRoleRead[];
  onClose: () => void;
  onPick: (job: JobRoleRead) => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [query, setQuery] = useState("");

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return jobs
      .filter((j) => !q || [j.title, j.department, j.location].some((v) => (v ?? "").toLowerCase().includes(q)))
      .slice(0, 60);
  }, [jobs, query]);

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md" aria-labelledby="job-template-title">
      <DialogTitle id="job-template-title" sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <Emoji name="clipboard" size={24} />
        {t("jobs.tpl.title")}
      </DialogTitle>
      <DialogContent>
        <Typography sx={{ color: f.muted, mb: 2 }}>{t("jobs.tpl.intro")}</Typography>
        {jobs.length > 0 && (
          <TextField
            size="small" fullWidth placeholder={t("jobs.tpl.search")} value={query} onChange={(e) => setQuery(e.target.value)} sx={{ mb: 2 }}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }, htmlInput: { "aria-label": t("jobs.tpl.search") } }}
          />
        )}
        {shown.length === 0 ? (
          <EmptyState compact illustration="job-offers" title={t(jobs.length === 0 ? "jobs.tpl.empty" : "jobs.tpl.no_match")} />
        ) : (
          <Grid container spacing={1.5}>
            {shown.map((job) => (
              <Grid key={job.id} size={{ xs: 12, sm: 6 }}>
                <Card sx={{ p: 2, height: "100%", display: "flex", flexDirection: "column", gap: 1, bgcolor: f.surface2, boxShadow: "none", border: `1px solid ${f.line}` }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
                    <Typography sx={{ fontWeight: 700 }}>{job.title}</Typography>
                    <StatusChip status={job.status} />
                  </Stack>
                  <Typography variant="body2" sx={{ color: f.muted }}>
                    {[job.department, job.location, t("jobs.tpl.skills", { count: skillCount(job) })].filter(Boolean).join(" · ")}
                  </Typography>
                  <Box sx={{ mt: "auto", pt: 0.5 }}>
                    <Button size="small" variant="outlined" onClick={() => onPick(job)} aria-label={`${t("jobs.tpl.use")}: ${job.title}`}>
                      {t("jobs.tpl.use")}
                    </Button>
                  </Box>
                </Card>
              </Grid>
            ))}
          </Grid>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.close")}</Button>
      </DialogActions>
    </Dialog>
  );
}
