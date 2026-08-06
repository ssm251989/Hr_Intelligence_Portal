import { useEffect, useState } from "react";
import AccessTimeOutlinedIcon from "@mui/icons-material/AccessTimeOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import EmojiEventsOutlinedIcon from "@mui/icons-material/EmojiEventsOutlined";
import PersonAddAltOutlinedIcon from "@mui/icons-material/PersonAddAltOutlined";
import TaskAltOutlinedIcon from "@mui/icons-material/TaskAltOutlined";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CircularProgress from "@mui/material/CircularProgress";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, reportsApi } from "../api/client";
import type { JobsDashboardStatsResponse } from "../api/types";
import JobsLocationMap from "./JobsLocationMap";
import LabeledDonutChart from "./LabeledDonutChart";
import QuickActionsPanel from "./QuickActionsPanel";
import RecentActivityFeed from "./RecentActivityFeed";
import StatCard from "./StatCard";
import TopPerformingJobs from "./TopPerformingJobs";

// Fixed categorical order (see the dataviz skill's palette) -- decorative here since
// each stat tile is an independent metric, not a series, but still assigned in a fixed
// order rather than picked arbitrarily per card.
const BLUE = "#2a78d6";
const ORANGE = "#eb6834";
const AQUA = "#1baf7a";
const YELLOW = "#eda100";
const MAGENTA = "#e87ba4";
const GREEN = "#008300";

export default function JobsDashboardStats({
  refreshSignal,
  onCreateJob,
}: {
  refreshSignal: number;
  onCreateJob: () => void;
}) {
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
        <StatCard label="Total Jobs" value={stats.total_jobs} icon={WorkOutlineIcon} color={BLUE} />
        <StatCard label="Active Jobs" value={stats.active_jobs} icon={TaskAltOutlinedIcon} color={ORANGE} />
        <StatCard label="Open Positions" value={stats.open_positions} icon={PersonAddAltOutlinedIcon} color={AQUA} />
        <StatCard
          label="Total Applications"
          value={stats.total_applications}
          icon={DescriptionOutlinedIcon}
          color={YELLOW}
        />
        <StatCard
          label="Hires This Month"
          value={stats.hires_this_month}
          icon={EmojiEventsOutlinedIcon}
          color={MAGENTA}
        />
        <StatCard
          label="Avg Time to Hire"
          value={stats.avg_time_to_hire_days != null ? `${stats.avg_time_to_hire_days}d` : "—"}
          icon={AccessTimeOutlinedIcon}
          color={GREEN}
        />
      </Stack>

      <Grid container spacing={3} mb={3}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <LabeledDonutChart title="Jobs by Department" rows={stats.by_department} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Jobs by Location
              </Typography>
              {/* Donut answers "what share"; the map answers "where" -- kept together
                  since they're two views of the same by_location data, not duplicates. */}
              <LabeledDonutChart title="" rows={stats.by_location} />
              <Box mt={2}>
                <JobsLocationMap rows={stats.by_location} />
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Top Performing Jobs
              </Typography>
              <TopPerformingJobs jobs={stats.top_jobs} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Quick Actions
              </Typography>
              <QuickActionsPanel onCreateJob={onCreateJob} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Recent Activity
              </Typography>
              <RecentActivityFeed limit={8} refreshSignal={refreshSignal} dense />
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
