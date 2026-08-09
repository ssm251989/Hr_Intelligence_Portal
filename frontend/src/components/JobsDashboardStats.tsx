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
import FormControl from "@mui/material/FormControl";
import Grid from "@mui/material/Grid";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";

import { extractErrorMessage, reportsApi } from "../api/client";
import type { JobsDashboardStatsResponse, LabeledCount, TopJobItem } from "../api/types";
import { formatMonthKey, pastMonthKeys } from "../utils/datetime";
import DepartmentBreakdownPanel from "./DepartmentBreakdownPanel";
import JobStatusOverviewPanel from "./JobStatusOverviewPanel";
import LocationBreakdownPanel from "./LocationBreakdownPanel";
import StatCard, { StatCardSkeleton } from "./StatCard";

// Sentinel for the default comparison period -- maps to no compare_month query param,
// which the backend resolves to last month. Kept distinct from that same month's real
// "YYYY-MM" key (which also appears further down the list) since the two are offered
// as separate options per the spec: a quick default plus each of the past 12 months by name.
const LAST_MONTH_SENTINEL = "last_month";

// One dropdown shared by all 6 cards, rather than 6 independent ones: every stat should
// be read against the same comparison period so the numbers stay comparable to each
// other, and the dataviz skill's own filter convention -- one row, above the content it
// scopes, never per-chart -- argues for a single shared control over a repeated per-card one.
const COMPARE_OPTIONS = [
  { value: LAST_MONTH_SENTINEL, label: "vs last month" },
  ...pastMonthKeys(12).map((key) => ({ value: key, label: `vs ${formatMonthKey(key)}` })),
];

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
  onTopJobsChange,
  onDepartmentBreakdownChange,
}: {
  refreshSignal: number;
  // Top Performing Jobs now lives in the page's sidebar, outside this component, but
  // its data (stats.top_jobs) only exists here -- this hands it up rather than
  // duplicating the fetch or lifting this whole component's state to the page.
  onTopJobsChange?: (jobs: TopJobItem[]) => void;
  // Same reasoning: the job list table's per-row department icon color needs to match
  // this donut's color-by-rank exactly, which means reusing this same by_department
  // dataset (not a client-side recount from whatever subset of jobs happens to be
  // currently filtered/paginated in the table).
  onDepartmentBreakdownChange?: (rows: LabeledCount[]) => void;
}) {
  const [stats, setStats] = useState<JobsDashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [compareMonth, setCompareMonth] = useState(LAST_MONTH_SENTINEL);

  useEffect(() => {
    setLoading(true);
    setError(null);
    reportsApi
      .jobsDashboardStats(compareMonth === LAST_MONTH_SENTINEL ? undefined : compareMonth)
      .then((data) => {
        setStats(data);
        onTopJobsChange?.(data.top_jobs);
        onDepartmentBreakdownChange?.(data.by_department);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load dashboard stats")))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal, compareMonth]);

  const handleCompareMonthChange = (event: SelectChangeEvent) => setCompareMonth(event.target.value);

  if (loading) {
    // Mirrors the real layout below (same Grid sizes) so nothing shifts once the real
    // data swaps in -- a spinner alone gives no sense of the shape about to appear.
    return (
      <Box mb={4}>
        <Stack direction="row" justifyContent="flex-end" mb={1.5}>
          <Skeleton variant="rounded" width={200} height={40} />
        </Stack>
        <Grid container spacing={2} mb={3}>
          {Array.from({ length: 6 }).map((_, i) => (
            <Grid key={i} size={{ xs: 12, sm: 6, md: 2 }}>
              <StatCardSkeleton />
            </Grid>
          ))}
        </Grid>
        <Grid container spacing={3}>
          {Array.from({ length: 3 }).map((_, i) => (
            <Grid key={i} size={{ xs: 12, md: 4 }}>
              <Card variant="outlined" sx={{ height: "100%" }}>
                <CardContent>
                  <Skeleton variant="text" width="50%" height={32} sx={{ mb: 2 }} />
                  <Skeleton variant="circular" width={140} height={140} sx={{ mx: "auto" }} />
                  <Skeleton variant="text" sx={{ mt: 2 }} />
                  <Skeleton variant="text" width="80%" />
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
          <InputLabel id="dashboard-compare-month-label">Compare</InputLabel>
          <Select
            labelId="dashboard-compare-month-label"
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
      {/* A flex-wrap Stack with a fixed per-card min-width wraps unpredictably once the
          row gets narrower than 6 cards' worth of that minimum (5-per-row-then-1 was the
          exact symptom) -- a Grid with an explicit 6th-of-the-row size keeps all 6 on one
          row at md+ regardless of the row's actual pixel width, and degrades gracefully
          (3-per-row, then 2, then 1) as the viewport narrows instead of wrapping oddly. */}
      <Grid container spacing={2} mb={3}>
        <Grid size={{ xs: 12, sm: 6, md: 2 }}>
          <StatCard
            label="Total Jobs"
            value={stats.total_jobs}
            icon={WorkOutlineIcon}
            color={BLUE}
            trend={stats.total_jobs_trend}
            hero
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2 }}>
          <StatCard
            label="Active Jobs"
            value={stats.active_jobs}
            icon={TaskAltOutlinedIcon}
            color={ORANGE}
            trend={stats.active_jobs_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2 }}>
          <StatCard
            label="Open Positions"
            value={stats.open_positions}
            icon={PersonAddAltOutlinedIcon}
            color={AQUA}
            trend={stats.open_positions_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2 }}>
          <StatCard
            label="Total Applications"
            value={stats.total_applications}
            icon={DescriptionOutlinedIcon}
            color={YELLOW}
            trend={stats.total_applications_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2 }}>
          <StatCard
            label="Hires This Month"
            value={stats.hires_this_month}
            icon={EmojiEventsOutlinedIcon}
            color={MAGENTA}
            trend={stats.hires_this_month_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2 }}>
          <StatCard
            label="Avg Time to Hire"
            value={stats.avg_time_to_hire_days != null ? `${stats.avg_time_to_hire_days}d` : "—"}
            icon={AccessTimeOutlinedIcon}
            color={GREEN}
            trend={stats.avg_time_to_hire_trend}
            higherIsBetter={false}
            formatSparklineValue={(v) => `${v}d`}
          />
        </Grid>
      </Grid>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 6, lg: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <DepartmentBreakdownPanel rows={stats.by_department} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6, lg: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <LocationBreakdownPanel rows={stats.by_location} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6, lg: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <JobStatusOverviewPanel />
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
