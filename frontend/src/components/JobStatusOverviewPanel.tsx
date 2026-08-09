import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, reportsApi } from "../api/client";
import type { JobStatusOverviewResponse } from "../api/types";
import LabeledDonutChart from "./LabeledDonutChart";

// Real status values from app/models/job_role.py's JOB_ROLE_STATUSES -- no invented
// statuses, just human-readable labels for the same five the backend returns.
const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  ready_for_publishing: "Ready for Publishing",
  published: "Published",
  closed: "Closed",
  on_hold: "On Hold",
};

const PERIOD_OPTIONS = [
  { value: "this_month", label: "This Month" },
  { value: "last_3_months", label: "Last 3 Months" },
  { value: "this_year", label: "This Year" },
  { value: "all_time", label: "All Time" },
];

export default function JobStatusOverviewPanel() {
  const [period, setPeriod] = useState("this_month");
  const [data, setData] = useState<JobStatusOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    reportsApi
      .jobStatusOverview(period)
      .then(setData)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load job status overview")))
      .finally(() => setLoading(false));
  }, [period]);

  const rows = (data?.by_status ?? []).map((row) => ({
    label: STATUS_LABELS[row.label] ?? row.label,
    count: row.count,
  }));

  return (
    <Box>
      <Stack direction="row" alignItems="center" justifyContent="space-between" mb={2} flexWrap="wrap" gap={1}>
        <Typography variant="h6">Job Status Overview</Typography>
        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel id="job-status-period-label">Period</InputLabel>
          <Select
            labelId="job-status-period-label"
            label="Period"
            value={period}
            onChange={(event: SelectChangeEvent) => setPeriod(event.target.value)}
          >
            {PERIOD_OPTIONS.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>
      {loading ? (
        <CircularProgress size={24} />
      ) : error ? (
        <Alert severity="error">{error}</Alert>
      ) : (
        <LabeledDonutChart title="" rows={rows} />
      )}
    </Box>
  );
}
