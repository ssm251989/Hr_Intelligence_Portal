import { useEffect, useState, type ReactNode } from "react";
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

import { reportsApi } from "../api/client";
import type { InterviewsDashboardStatsResponse, StatTrend } from "../api/types";
import { useT, type TFunction } from "../i18n";
import Emoji from "../ui-kit/Emoji";
import FriendlyError from "../ui-kit/FriendlyError";
import StatTile from "../ui-kit/StatTile";
import type { Tone } from "../ui-kit/StatusChip";
import { formatMonthKey, pastMonthKeys } from "../utils/datetime";
import LabeledDonutChart from "./LabeledDonutChart";
import RecentInterviewsTable from "./RecentInterviewsTable";
import TopSkillsBarChart from "./TopSkillsBarChart";

const LAST_MONTH_SENTINEL = "last_month";

function trendText(t: TFunction, trend: StatTrend | undefined, higherIsBetter = true): { trend?: string; trendDirection?: "up" | "down" | "flat" } {
  if (!trend || trend.pct_change == null) return {};
  const pct = Math.round(trend.pct_change);
  const label = t("interviews.dash.trend", { pct: Math.abs(pct), month: formatMonthKey(trend.compare_month) });
  if (pct === 0) return { trend: label, trendDirection: "flat" };
  const good = pct > 0 === higherIsBetter;
  return { trend: `${pct > 0 ? "+" : "−"}${label}`, trendDirection: good ? "up" : "down" };
}

function ChartCard({ emoji, title, children }: { emoji: string; title: string; children: ReactNode }) {
  return (
    <Card sx={{ height: "100%" }}>
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
          <Emoji name={emoji} size={20} />
          <Typography component="h2" sx={{ fontWeight: 700, fontSize: 16 }}>
            {title}
          </Typography>
        </Stack>
        {children}
      </CardContent>
    </Card>
  );
}

// onLoadingChange is optional -- purely so the page's own RefreshButton can show an
// accurate in-flight spinner for this fetch; nothing here changes because of it.
export default function InterviewsDashboardStats({
  refreshSignal = 0,
  onLoadingChange,
}: {
  refreshSignal?: number;
  onLoadingChange?: (loading: boolean) => void;
}) {
  const t = useT();
  const [stats, setStats] = useState<InterviewsDashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [compareMonth, setCompareMonth] = useState(LAST_MONTH_SENTINEL);
  const [retry, setRetry] = useState(0);

  const compareOptions = [
    { value: LAST_MONTH_SENTINEL, label: t("interviews.dash.vs_last_month") },
    ...pastMonthKeys(12).map((key) => ({ value: key, label: t("interviews.dash.vs_month", { month: formatMonthKey(key) }) })),
  ];

  useEffect(() => {
    setLoading(true);
    onLoadingChange?.(true);
    setError(null);
    reportsApi
      .interviewsDashboardStats(compareMonth === LAST_MONTH_SENTINEL ? undefined : compareMonth)
      .then(setStats)
      .catch(setError)
      .finally(() => {
        setLoading(false);
        onLoadingChange?.(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal, compareMonth, retry]);

  const handleCompareMonthChange = (event: SelectChangeEvent) => setCompareMonth(event.target.value);

  if (loading) {
    return (
      <Box mb={4} role="status" aria-label={t("interviews.dash.loading")}>
        <Grid container spacing={2} mb={3}>
          {Array.from({ length: 5 }).map((_, i) => (
            <Grid key={i} size={{ xs: 12, sm: 6, md: 2.4 }}>
              <Skeleton variant="rounded" height={150} sx={{ borderRadius: "18px" }} />
            </Grid>
          ))}
        </Grid>
        <Grid container spacing={3}>
          {Array.from({ length: 3 }).map((_, i) => (
            <Grid key={i} size={{ xs: 12, md: 4 }}>
              <Skeleton variant="rounded" height={220} sx={{ borderRadius: "18px" }} />
            </Grid>
          ))}
        </Grid>
      </Box>
    );
  }

  if (error) {
    return (
      <Box mb={3}>
        <FriendlyError error={error} onRetry={() => setRetry((n) => n + 1)} />
      </Box>
    );
  }

  if (!stats) {
    return null;
  }

  const tiles: { emoji: string; value: number; label: string; tone: Tone; trend?: StatTrend; higherIsBetter?: boolean; to: string }[] = [
    { emoji: "calendar", value: stats.total_interviews_scheduled_this_month, label: t("interviews.dash.this_month"), tone: "sky", trend: stats.total_interviews_scheduled_this_month_trend, to: "/interviews/list?view=week" },
    { emoji: "alarm_clock", value: stats.upcoming, label: t("interviews.dash.upcoming"), tone: "sun", to: "/interviews/list?status=upcoming" },
    { emoji: "check", value: stats.completed, label: t("interviews.dash.completed"), tone: "brand", trend: stats.completed_trend, to: "/interviews/list" },
    { emoji: "thumbs_up", value: stats.selected, label: t("interviews.dash.selected"), tone: "ok", trend: stats.selected_trend, to: "/interviews/list?status=selected" },
    { emoji: "cross", value: stats.rejected, label: t("interviews.dash.rejected"), tone: "coral", trend: stats.rejected_trend, higherIsBetter: false, to: "/interviews/list?status=rejected" },
  ];

  return (
    <Box mb={3}>
      <Stack direction="row" justifyContent="flex-end" mb={1.5}>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="interviews-dashboard-compare-month-label">{t("interviews.dash.compare")}</InputLabel>
          <Select labelId="interviews-dashboard-compare-month-label" label={t("interviews.dash.compare")} value={compareMonth} onChange={handleCompareMonthChange}>
            {compareOptions.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      <Grid container spacing={2} mb={3}>
        {tiles.map((tile) => (
          <Grid key={tile.label} size={{ xs: 12, sm: 6, md: 2.4 }}>
            <StatTile emoji={tile.emoji} value={tile.value} label={tile.label} tone={tile.tone} to={tile.to} {...trendText(t, tile.trend, tile.higherIsBetter)} />
          </Grid>
        ))}
      </Grid>

      <Grid container spacing={3} mb={3}>
        <Grid size={{ xs: 12, md: 4 }}>
          <ChartCard emoji="target" title={t("interviews.dash.outcomes")}>
            <LabeledDonutChart title="" rows={stats.outcome_breakdown} />
          </ChartCard>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <ChartCard emoji="people" title={t("interviews.dash.workload")}>
            <TopSkillsBarChart rows={stats.interviewer_workload} emptyMessage={t("interviews.empty.none")} />
          </ChartCard>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <ChartCard emoji="link" title={t("interviews.dash.how_booked")}>
            <LabeledDonutChart title="" rows={stats.scheduling_method_breakdown} />
          </ChartCard>
        </Grid>
      </Grid>

      <ChartCard emoji="clipboard" title={t("interviews.dash.recent")}>
        <RecentInterviewsTable rows={stats.recent_interviews} />
      </ChartCard>
    </Box>
  );
}
