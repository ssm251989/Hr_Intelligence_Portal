import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { reportsApi } from "../api/client";
import type { JobStatusOverviewResponse } from "../api/types";
import { useT } from "../i18n";
import { Emoji, FriendlyError, statusStyle } from "../ui-kit";
import LabeledDonutChart from "./LabeledDonutChart";

// Real status values from app/models/job_role.py's JOB_ROLE_STATUSES -- no invented
// statuses, just the same plain-language words the status chips use.
const PERIOD_OPTIONS = [
  { value: "this_month", key: "jobs.so.this_month" },
  { value: "last_3_months", key: "jobs.so.last_3" },
  { value: "this_year", key: "jobs.so.this_year" },
  { value: "all_time", key: "jobs.so.all_time" },
];

export default function JobStatusOverviewPanel() {
  const t = useT();
  const [period, setPeriod] = useState("this_month");
  const [data, setData] = useState<JobStatusOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setLoading(true);
    setError(null);
    reportsApi
      .jobStatusOverview(period)
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [period, attempt]);

  const label = (status: string) => {
    const key = `status.${status}`;
    const translated = t(key);
    return translated !== key ? translated : statusStyle(status).label;
  };
  const rows = (data?.by_status ?? []).map((row) => ({ label: label(row.label), count: row.count }));

  return (
    <Box>
      <Stack direction="row" alignItems="center" justifyContent="space-between" mb={2} flexWrap="wrap" gap={1}>
        <Typography variant="h6" component="h3" sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <Emoji name="bar_chart" size={20} />
          {t("jobs.so.title")}
        </Typography>
        <TextField select size="small" label={t("jobs.so.period")} value={period} onChange={(e) => setPeriod(e.target.value)} sx={{ minWidth: 160 }}>
          {PERIOD_OPTIONS.map((option) => (
            <MenuItem key={option.value} value={option.value}>
              {t(option.key)}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
      {loading ? (
        <Skeleton variant="circular" width={140} height={140} sx={{ mx: "auto" }} />
      ) : error ? (
        <FriendlyError compact error={error} onRetry={() => setAttempt((a) => a + 1)} />
      ) : (
        <LabeledDonutChart title="" rows={rows} />
      )}
    </Box>
  );
}
