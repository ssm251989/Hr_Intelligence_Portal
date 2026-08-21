import { useEffect, useState } from "react";
import CheckCircleOutlinedIcon from "@mui/icons-material/CheckCircleOutlined";
import EventAvailableOutlinedIcon from "@mui/icons-material/EventAvailableOutlined";
import EventOutlinedIcon from "@mui/icons-material/EventOutlined";
import HighlightOffOutlinedIcon from "@mui/icons-material/HighlightOffOutlined";
import UpcomingOutlinedIcon from "@mui/icons-material/UpcomingOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import FormControl from "@mui/material/FormControl";
import Grid from "@mui/material/Grid";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, reportsApi } from "../api/client";
import type { InterviewsDashboardStatsResponse } from "../api/types";
import { formatMonthKey, pastMonthKeys } from "../utils/datetime";
import LabeledDonutChart from "./LabeledDonutChart";
import RecentInterviewsTable from "./RecentInterviewsTable";
import StatCard, { StatCardSkeleton } from "./StatCard";
import TopSkillsBarChart from "./TopSkillsBarChart";

const LAST_MONTH_SENTINEL = "last_month";
const COMPARE_OPTIONS = [
  { value: LAST_MONTH_SENTINEL, label: "vs last month" },
  ...pastMonthKeys(12).map((key) => ({ value: key, label: `vs ${formatMonthKey(key)}` })),
];

// Same 5-color palette as every other dashboard in the app.
const BLUE = "#2a78d6";
const ORANGE = "#eb6834";
const AQUA = "#1baf7a";
const YELLOW = "#eda100";
const MAGENTA = "#e87ba4";

// onLoadingChange is optional -- purely so the page's own RefreshButton can show an
// accurate in-flight spinner for this fetch; nothing here changes because of it.
export default function InterviewsDashboardStats({
  refreshSignal = 0,
  onLoadingChange,
}: {
  refreshSignal?: number;
  onLoadingChange?: (loading: boolean) => void;
}) {
  const [stats, setStats] = useState<InterviewsDashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [compareMonth, setCompareMonth] = useState(LAST_MONTH_SENTINEL);

  useEffect(() => {
    setLoading(true);
    onLoadingChange?.(true);
    setError(null);
    reportsApi
      .interviewsDashboardStats(compareMonth === LAST_MONTH_SENTINEL ? undefined : compareMonth)
      .then(setStats)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load interview dashboard")))
      .finally(() => {
        setLoading(false);
        onLoadingChange?.(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal, compareMonth]);

  const handleCompareMonthChange = (event: SelectChangeEvent) => setCompareMonth(event.target.value);

  if (loading) {
    return (
      <Box mb={4}>
        <Stack direction="row" justifyContent="flex-end" mb={1.5}>
          <Skeleton variant="rounded" width={200} height={40} />
        </Stack>
        <Grid container spacing={2} mb={3}>
          {Array.from({ length: 5 }).map((_, i) => (
            <Grid key={i} size={{ xs: 12, sm: 6, md: 2.4 }}>
              <StatCardSkeleton variant="compact" />
            </Grid>
          ))}
        </Grid>
        <Grid container spacing={3}>
          {Array.from({ length: 3 }).map((_, i) => (
            <Grid key={i} size={{ xs: 12, md: 4 }}>
              <Card variant="outlined" sx={{ height: "100%" }}>
                <CardContent>
                  <Skeleton variant="text" width="50%" height={32} sx={{ mb: 2 }} />
                  <Skeleton variant="rounded" height={140} />
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Box>
    );
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
    <Box mb={3}>
      <Stack direction="row" justifyContent="flex-end" mb={1.5}>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="interviews-dashboard-compare-month-label">Compare</InputLabel>
          <Select
            labelId="interviews-dashboard-compare-month-label"
            label="Compare"
            value={compareMonth}
            onChange={handleCompareMonthChange}
          >
            {COMPARE_OPTIONS.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      <Grid container spacing={2} mb={3}>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Scheduled This Month"
            value={stats.total_interviews_scheduled_this_month}
            icon={EventOutlinedIcon}
            color={BLUE}
            trend={stats.total_interviews_scheduled_this_month_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Upcoming"
            value={stats.upcoming}
            icon={UpcomingOutlinedIcon}
            color={ORANGE}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Completed"
            value={stats.completed}
            icon={EventAvailableOutlinedIcon}
            color={AQUA}
            trend={stats.completed_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Selected"
            value={stats.selected}
            icon={CheckCircleOutlinedIcon}
            color={YELLOW}
            trend={stats.selected_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Rejected"
            value={stats.rejected}
            icon={HighlightOffOutlinedIcon}
            color={MAGENTA}
            trend={stats.rejected_trend}
            higherIsBetter={false}
          />
        </Grid>
      </Grid>

      <Grid container spacing={3} mb={3}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <LabeledDonutChart title="Interview Outcome Breakdown" rows={stats.outcome_breakdown} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Interviewer Workload
              </Typography>
              <TopSkillsBarChart rows={stats.interviewer_workload} emptyMessage="No interviews scheduled yet." />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <LabeledDonutChart title="Scheduling Method" rows={stats.scheduling_method_breakdown} />
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="h6" mb={2}>
            Recent Interviews
          </Typography>
          <RecentInterviewsTable rows={stats.recent_interviews} />
        </CardContent>
      </Card>
    </Box>
  );
}
