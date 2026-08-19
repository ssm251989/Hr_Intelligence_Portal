import { useEffect, useState } from "react";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import FilterAltOutlinedIcon from "@mui/icons-material/FilterAltOutlined";
import PendingActionsOutlinedIcon from "@mui/icons-material/PendingActionsOutlined";
import PersonAddAltOutlinedIcon from "@mui/icons-material/PersonAddAltOutlined";
import SpeedOutlinedIcon from "@mui/icons-material/SpeedOutlined";
import TrendingUpOutlinedIcon from "@mui/icons-material/TrendingUpOutlined";
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
import type { ShortlistingDashboardStatsResponse } from "../api/types";
import { formatMonthKey, pastMonthKeys } from "../utils/datetime";
import LabeledDonutChart from "./LabeledDonutChart";
import MatchScoreDistributionChart from "./MatchScoreDistributionChart";
import RecentShortlistedTable from "./RecentShortlistedTable";
import StatCard, { StatCardSkeleton } from "./StatCard";

// "From Screening" is every application screening has ever produced a composite_score
// for (see backend app/reports/stats.py shortlisting_funnel_counts) -- a superset of the
// other four, not a mutually-exclusive bucket of its own (some of those applications have
// since moved further downstream, past this stage entirely). A donut's slices must sum to
// one real whole, so it's shown as its own headline number instead of a 5th slice that
// would double-count against the other four and inflate the total.
const CURRENT_STAGE_LABELS = new Set(["Under Review", "Shortlisted", "On Hold", "Rejected"]);

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

export default function ShortlistingDashboardStats({ refreshSignal = 0 }: { refreshSignal?: number }) {
  const [stats, setStats] = useState<ShortlistingDashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [compareMonth, setCompareMonth] = useState(LAST_MONTH_SENTINEL);

  useEffect(() => {
    setLoading(true);
    setError(null);
    reportsApi
      .shortlistingDashboardStats(compareMonth === LAST_MONTH_SENTINEL ? undefined : compareMonth)
      .then(setStats)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load shortlisting dashboard")))
      .finally(() => setLoading(false));
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
          {Array.from({ length: 2 }).map((_, i) => (
            <Grid key={i} size={{ xs: 12, md: 6 }}>
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
          <InputLabel id="shortlisting-dashboard-compare-month-label">Compare</InputLabel>
          <Select
            labelId="shortlisting-dashboard-compare-month-label"
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
            label="Total in Shortlisting"
            value={stats.total_in_shortlisting}
            icon={PendingActionsOutlinedIcon}
            color={BLUE}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="New This Month"
            value={stats.new_this_month}
            icon={PersonAddAltOutlinedIcon}
            color={ORANGE}
            trend={stats.new_this_month_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Moved from Screening"
            value={stats.moved_from_screening_this_month}
            icon={FilterAltOutlinedIcon}
            color={AQUA}
            trend={stats.moved_from_screening_this_month_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Shortlisted This Month"
            value={stats.shortlisted_this_month}
            icon={TrendingUpOutlinedIcon}
            color={YELLOW}
            trend={stats.shortlisted_this_month_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Avg Score (Shortlisted)"
            value={stats.avg_composite_score_shortlisted != null ? `${Math.round(stats.avg_composite_score_shortlisted)}%` : "—"}
            icon={SpeedOutlinedIcon}
            color={MAGENTA}
            trend={stats.avg_composite_score_shortlisted_trend}
          />
        </Grid>
      </Grid>

      <Grid container spacing={3} mb={3}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="baseline" mb={2}>
                <Typography variant="h6">Shortlisting Breakdown</Typography>
                <Typography variant="caption" color="text.secondary">
                  {stats.funnel.find((stage) => stage.label === "From Screening")?.count ?? 0} screened overall
                </Typography>
              </Stack>
              <LabeledDonutChart
                title=""
                rows={stats.funnel.filter((stage) => CURRENT_STAGE_LABELS.has(stage.label))}
              />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Composite Score Distribution
              </Typography>
              <MatchScoreDistributionChart rows={stats.composite_score_distribution} />
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Grid container spacing={3} mb={3}>
        <Grid size={12}>
          <Card variant="outlined">
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center" mb={2}>
                <AutoAwesomeOutlinedIcon fontSize="small" color="primary" />
                <Typography variant="h6">AI Insights</Typography>
              </Stack>
              {stats.insights.length === 0 ? (
                <Typography color="text.secondary" variant="body2">
                  Not enough shortlisting activity yet to compute insights.
                </Typography>
              ) : (
                <Stack spacing={1}>
                  {stats.insights.map((insight, i) => (
                    <Typography key={i} variant="body2">
                      • {insight}
                    </Typography>
                  ))}
                </Stack>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="h6" mb={2}>
            Recent Shortlisted Candidates
          </Typography>
          <RecentShortlistedTable rows={stats.recent_shortlisted} />
        </CardContent>
      </Card>
    </Box>
  );
}
