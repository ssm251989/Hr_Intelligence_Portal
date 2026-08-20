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
import { formatExperienceRange } from "../utils/experience";
import { categorizeSkills } from "../utils/skills";
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
              {[
                job.department,
                job.location,
                formatExperienceRange(job.experience_min_years, job.experience_max_years),
                job.job_type,
              ]
                .filter(Boolean)
                .join(" · ") || "No details set"}
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

            {(() => {
              const { mustHave, goodToHave } = categorizeSkills(job);
              if (mustHave.length === 0 && goodToHave.length === 0) return null;
              return (
                <Stack spacing={0.75}>
                  {mustHave.length > 0 && (
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
                      <Typography variant="caption" color="text.secondary">
                        Must Have:
                      </Typography>
                      {mustHave.map((skill) => (
                        <Chip key={`must-${skill}`} label={skill} size="small" />
                      ))}
                    </Stack>
                  )}
                  {goodToHave.length > 0 && (
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
                      <Typography variant="caption" color="text.secondary">
                        Good to Have:
                      </Typography>
                      {goodToHave.map((skill) => (
                        <Chip key={`good-${skill}`} label={skill} size="small" variant="outlined" />
                      ))}
                    </Stack>
                  )}
                </Stack>
              );
            })()}

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
