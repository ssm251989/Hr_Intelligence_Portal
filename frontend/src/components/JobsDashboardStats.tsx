import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";

import { extractErrorMessage, reportsApi } from "../api/client";
import type { JobsDashboardStatsResponse } from "../api/types";
import LabeledDonutChart from "./LabeledDonutChart";
import StatCard from "./StatCard";

export default function JobsDashboardStats({ refreshSignal }: { refreshSignal: number }) {
  const [stats, setStats] = useState<JobsDashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    reportsApi
      .jobsDashboardStats()
      .then(setStats)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load dashboard stats")))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  if (loading) {
    return <CircularProgress sx={{ mb: 3 }} />;
  }

  if (error) {
    return (
      <Alert severity="error" sx={{ mb: 3 }}>
        {error}
      </Alert>
    );
  }

  if (!stats) {
    return null;
  }

  return (
    <Box mb={4}>
      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap mb={3}>
        <StatCard label="Total Jobs" value={stats.total_jobs} />
        <StatCard label="Active Jobs" value={stats.active_jobs} />
        <StatCard label="Open Positions" value={stats.open_positions} />
        <StatCard label="Total Applications" value={stats.total_applications} />
        <StatCard label="Hires This Month" value={stats.hires_this_month} />
        <StatCard
          label="Avg Time to Hire"
          value={stats.avg_time_to_hire_days != null ? `${stats.avg_time_to_hire_days}d` : "—"}
        />
      </Stack>

      <Stack direction={{ xs: "column", md: "row" }} spacing={3}>
        <Card variant="outlined" sx={{ flex: 1 }}>
          <CardContent>
            <LabeledDonutChart title="Jobs by Department" rows={stats.by_department} />
          </CardContent>
        </Card>
        <Card variant="outlined" sx={{ flex: 1 }}>
          <CardContent>
            <LabeledDonutChart title="Jobs by Location" rows={stats.by_location} />
          </CardContent>
        </Card>
      </Stack>
    </Box>
  );
}
