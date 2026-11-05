import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { reportsApi } from "../api/client";
import type { JobsDashboardStatsResponse, LabeledCount, StatTrend, TopJobItem } from "../api/types";
import { useT, type TFunction } from "../i18n";
import { FriendlyError, InfoTip, StatTile, type Tone } from "../ui-kit";
import { formatMonthKey, pastMonthKeys } from "../utils/datetime";
import DepartmentBreakdownPanel from "./DepartmentBreakdownPanel";
import JobStatusOverviewPanel from "./JobStatusOverviewPanel";
import LocationBreakdownPanel from "./LocationBreakdownPanel";

// Sentinel for the default comparison period -- maps to no compare_month query param,
// which the backend resolves to last month.
const LAST_MONTH_SENTINEL = "last_month";

// Same trend maths as StatCard's TrendIndicator (app/reports/stats.py::pct_change): a null
// pct with a 0 compare value means "grew from nothing" (+100%); a null compare value means
// there is nothing to compare at all.
function trendOf(trend: StatTrend, higherIsBetter: boolean, period: string, t: TFunction): { text?: string; direction: "up" | "down" | "flat" } {
  const zeroBaseline = trend.pct_change == null && trend.compare_value === 0;
  const pct = zeroBaseline ? 100 : trend.pct_change;
  if (pct == null) return { direction: "flat" };
  const text = t("jobs.stats.trend", { pct: Math.abs(pct), period });
  if (pct === 0) return { text, direction: "flat" };
  const good = pct > 0 === higherIsBetter;
  return { text, direction: good ? "up" : "down" };
}

export default function JobsDashboardStats({
  refreshSignal,
  onTopJobsChange,
  onDepartmentBreakdownChange,
  onStatsChange,
  showBreakdowns = true,
}: {
  refreshSignal: number;
  // Top jobs + the department breakdown only exist in this response -- handed up so the
  // page can show them elsewhere without fetching twice.
  onTopJobsChange?: (jobs: TopJobItem[]) => void;
  onDepartmentBreakdownChange?: (rows: LabeledCount[]) => void;
  /** Whole response, for pages that lay the breakdown panels out themselves (showBreakdowns=false). */
  onStatsChange?: (stats: JobsDashboardStatsResponse) => void;
  showBreakdowns?: boolean;
}) {
  const t = useT();
  const [stats, setStats] = useState<JobsDashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [compareMonth, setCompareMonth] = useState(LAST_MONTH_SENTINEL);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setLoading(true);
    setError(null);
    reportsApi
      .jobsDashboardStats(compareMonth === LAST_MONTH_SENTINEL ? undefined : compareMonth)
      .then((data) => {
        setStats(data);
        onTopJobsChange?.(data.top_jobs);
        onDepartmentBreakdownChange?.(data.by_department);
        onStatsChange?.(data);
      })
      .catch(setError)
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal, compareMonth, attempt]);

  const compareOptions = [
    { value: LAST_MONTH_SENTINEL, label: t("jobs.stats.vs_last_month") },
    ...pastMonthKeys(12).map((key) => ({ value: key, label: t("jobs.stats.vs_month", { month: formatMonthKey(key) }) })),
  ];
  const period = compareOptions.find((o) => o.value === compareMonth)?.label ?? "";

  if (error) {
    return (
      <Box mb={3}>
        <FriendlyError compact error={error} what={t("jobs.stats.error")} onRetry={() => setAttempt((a) => a + 1)} />
      </Box>
    );
  }

  const tiles: { emoji: string; tone: Tone; label: string; value: number | string; trend?: StatTrend; higherIsBetter?: boolean; tip?: string }[] = stats
    ? [
        { emoji: "briefcase", tone: "sky", label: t("jobs.stats.total"), value: stats.total_jobs, trend: stats.total_jobs_trend },
        { emoji: "globe", tone: "brand", label: t("jobs.stats.active"), value: stats.active_jobs, trend: stats.active_jobs_trend },
        { emoji: "people", tone: "sun", label: t("jobs.stats.positions"), value: stats.open_positions, trend: stats.open_positions_trend, tip: t("jobs.stats.positions_tip") },
        { emoji: "inbox", tone: "sky", label: t("jobs.stats.applications"), value: stats.total_applications, trend: stats.total_applications_trend },
        { emoji: "party", tone: "coral", label: t("jobs.stats.hires"), value: stats.hires_this_month, trend: stats.hires_this_month_trend },
        {
          emoji: "hourglass", tone: "ok", label: t("jobs.stats.time_to_hire"), value: stats.avg_time_to_hire_days != null ? stats.avg_time_to_hire_days : "—",
          trend: stats.avg_time_to_hire_trend, higherIsBetter: false, tip: t("jobs.stats.time_to_hire_tip"),
        },
      ]
    : [];

  return (
    <Box mb={3}>
      <Stack direction="row" justifyContent="flex-end" alignItems="center" mb={1.5}>
        <TextField select size="small" label={t("jobs.stats.compare")} value={compareMonth} onChange={(e) => setCompareMonth(e.target.value)} sx={{ minWidth: 200 }}>
          {compareOptions.map((option) => (
            <MenuItem key={option.value} value={option.value}>
              {option.label}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
      <Grid container spacing={2} mb={showBreakdowns ? 3 : 0}>
        {loading || !stats
          ? Array.from({ length: 6 }).map((_, i) => (
              <Grid key={i} size={{ xs: 6, md: 4, lg: 2 }}>
                <Skeleton variant="rounded" height={150} sx={{ borderRadius: "18px" }} />
              </Grid>
            ))
          : tiles.map((tile) => {
              const trend = tile.trend ? trendOf(tile.trend, tile.higherIsBetter ?? true, period, t) : { direction: "flat" as const };
              return (
                <Grid key={tile.label} size={{ xs: 6, md: 4, lg: 2 }} sx={{ position: "relative" }}>
                  <StatTile emoji={tile.emoji} tone={tile.tone} value={tile.value} label={tile.label} trend={trend.text} trendDirection={trend.direction} />
                  {tile.tip && (
                    <Box sx={{ position: "absolute", top: 10, right: 10 }}>
                      <InfoTip text={tile.tip} />
                    </Box>
                  )}
                </Grid>
              );
            })}
      </Grid>

      {showBreakdowns && stats && (
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, md: 6, lg: 4 }}>
            <Card sx={{ height: "100%" }}>
              <CardContent>
                <DepartmentBreakdownPanel rows={stats.by_department} />
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 6, lg: 4 }}>
            <Card sx={{ height: "100%" }}>
              <CardContent>
                <LocationBreakdownPanel rows={stats.by_location} />
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 6, lg: 4 }}>
            <Card sx={{ height: "100%" }}>
              <CardContent>
                <JobStatusOverviewPanel />
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}
    </Box>
  );
}
