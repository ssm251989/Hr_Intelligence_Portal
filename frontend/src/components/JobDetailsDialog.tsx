import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Button from "@mui/material/Button";
import Divider from "@mui/material/Divider";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { JobRoleRead } from "../api/types";
import PostingLinksEditor from "./PostingLinksEditor";
import StatusChip from "./StatusChip";

export default function JobDetailsDialog({
  job,
  canWrite,
  onClose,
  onUpdated,
}: {
  job: JobRoleRead | null;
  canWrite: boolean;
  onClose: () => void;
  onUpdated: (job: JobRoleRead) => void;
}) {
  return (
    <Dialog open={job !== null} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Job Details</DialogTitle>
      <DialogContent>
        {job && (
          <Stack spacing={1.5} mt={0.5}>
            <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
              <Typography variant="h6">{job.title}</Typography>
              <StatusChip status={job.status} />
            </Stack>
            <Typography variant="body2" color="text.secondary">
              {[job.department, job.location, job.experience_level, job.job_type].filter(Boolean).join(" · ") ||
                "No details set"}
            </Typography>

            <Divider />

            <Typography variant="body2">
              Openings: {job.positions_count}
              {job.salary_band_min != null && job.salary_band_max != null
                ? ` · Salary band: ${job.salary_band_min} - ${job.salary_band_max}`
                : ""}
            </Typography>
            <Typography variant="body2">
              Applications: {job.application_count}
              {job.avg_time_to_hire_days != null ? ` · Avg time to hire: ${job.avg_time_to_hire_days}d` : ""}
            </Typography>

            {job.skills && job.skills.length > 0 && (
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {job.skills.map((skill) => (
                  <Chip key={skill} label={skill} size="small" variant="outlined" />
                ))}
              </Stack>
            )}

            {job.benefits && (
              <Typography variant="body2" color="text.secondary">
                Benefits: {job.benefits}
              </Typography>
            )}
            {job.additional_notes && (
              <Typography variant="body2" color="text.secondary">
                Notes: {job.additional_notes}
              </Typography>
            )}

            <PostingLinksEditor job={job} canWrite={canWrite} onUpdated={onUpdated} />

            {job.jd_text && (
              <Box mt={1} p={1.5} bgcolor="action.hover" borderRadius={1}>
                <Typography variant="subtitle2" gutterBottom>
                  Job Description
                </Typography>
                <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", fontFamily: "monospace" }}>
                  {job.jd_text}
                </Typography>
              </Box>
            )}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
