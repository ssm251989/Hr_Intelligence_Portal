import { useEffect, useState } from "react";
import ErrorOutlineOutlinedIcon from "@mui/icons-material/ErrorOutlineOutlined";
import LeaderboardOutlinedIcon from "@mui/icons-material/LeaderboardOutlined";
import PendingActionsOutlinedIcon from "@mui/icons-material/PendingActionsOutlined";
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
import type { ScreeningDashboardStatsResponse } from "../api/types";
import { formatMonthKey, pastMonthKeys } from "../utils/datetime";
import LabeledDonutChart from "./LabeledDonutChart";
import MatchScoreDistributionChart from "./MatchScoreDistributionChart";
import StatCard, { StatCardSkeleton } from "./StatCard";
import TopSkillsBarChart from "./TopSkillsBarChart";

const LAST_MONTH_SENTINEL = "last_month";
const COMPARE_OPTIONS = [
  { value: LAST_MONTH_SENTINEL, label: "vs last month" },
  ...pastMonthKeys(12).map((key) => ({ value: key, label: `vs ${formatMonthKey(key)}` })),
];

// Same 5-color palette as CandidatesDashboardStats -- one visual language across every
// dashboard in the app, not a per-module color scheme.
const BLUE = "#2a78d6";
const ORANGE = "#eb6834";
const AQUA = "#1baf7a";
const YELLOW = "#eda100";
const MAGENTA = "#e87ba4";

export default function ScreeningDashboardStats({ refreshSignal = 0 }: { refreshSignal?: number }) {
  const [stats, setStats] = useState<ScreeningDashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [compareMonth, setCompareMonth] = useState(LAST_MONTH_SENTINEL);

  useEffect(() => {
    setLoading(true);
    setError(null);
    reportsApi
      .screeningDashboardStats(compareMonth === LAST_MONTH_SENTINEL ? undefined : compareMonth)
      .then(setStats)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load screening dashboard")))
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
          <InputLabel id="screening-dashboard-compare-month-label">Compare</InputLabel>
          <Select
            labelId="screening-dashboard-compare-month-label"
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
            label="Awaiting Screening"
            value={stats.awaiting_screening}
            icon={PendingActionsOutlinedIcon}
            color={BLUE}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Awaiting Ranking"
            value={stats.awaiting_ranking}
            icon={LeaderboardOutlinedIcon}
            color={ORANGE}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Auto-Advanced This Month"
            value={stats.auto_advanced_this_month}
            icon={TrendingUpOutlinedIcon}
            color={AQUA}
            trend={stats.auto_advanced_this_month_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Failed This Month"
            value={stats.failed_this_month}
            icon={ErrorOutlineOutlinedIcon}
            color={YELLOW}
            trend={stats.failed_this_month_trend}
            higherIsBetter={false}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Avg Composite Score"
            value={stats.avg_composite_score != null ? `${Math.round(stats.avg_composite_score)}%` : "—"}
            icon={SpeedOutlinedIcon}
            color={MAGENTA}
            trend={stats.avg_composite_score_trend}
          />
        </Grid>
      </Grid>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <LabeledDonutChart title="Recommendation Breakdown" rows={stats.recommendation_breakdown} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Composite Score Distribution
              </Typography>
              <MatchScoreDistributionChart rows={stats.composite_score_distribution} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Top Missing Skills
              </Typography>
              <TopSkillsBarChart rows={stats.top_missing_skills} />
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
