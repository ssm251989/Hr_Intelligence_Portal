import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { TopJobItem } from "../api/types";

export default function TopPerformingJobs({ jobs }: { jobs: TopJobItem[] }) {
  if (jobs.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        No applications yet.
      </Typography>
    );
  }

  const maxCount = Math.max(...jobs.map((job) => job.application_count), 1);

  return (
    <Stack spacing={1.5}>
      {jobs.map((job, index) => (
        <Stack key={job.job_id} direction="row" spacing={1.5} alignItems="center">
          <Typography variant="body2" color="text.secondary" sx={{ width: 20 }}>
            {index + 1}
          </Typography>
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="body2" noWrap>
              {job.title}
            </Typography>
            <Box
              sx={{
                height: 6,
                borderRadius: 1,
                bgcolor: "primary.main",
                width: `${(job.application_count / maxCount) * 100}%`,
                minWidth: job.application_count > 0 ? 4 : 0,
                mt: 0.5,
              }}
            />
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ minWidth: 70, textAlign: "right" }}>
            {job.application_count} {job.application_count === 1 ? "app" : "apps"}
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}
