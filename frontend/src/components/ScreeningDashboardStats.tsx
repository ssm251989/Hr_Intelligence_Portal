import { useEffect, useState } from "react";
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
import type { ScreeningDashboardStatsResponse } from "../api/types";
import { useT } from "../i18n";
import { EmptyState, FriendlyError, StatTile } from "../ui-kit";
import { formatMonthKey, pastMonthKeys } from "../utils/datetime";
import LabeledDonutChart from "./LabeledDonutChart";
import MatchScoreDistributionChart from "./MatchScoreDistributionChart";
import TopSkillsBarChart from "./TopSkillsBarChart";
import { trendProps } from "./screening/trend";

const LAST_MONTH_SENTINEL = "last_month";

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card sx={{ height: "100%" }}>
      <CardContent>
        <Typography variant="h6" mb={2}>{title}</Typography>
        {children}
      </CardContent>
    </Card>
  );
}

// onLoadingChange is optional -- purely so the page's own RefreshButton can show an
// accurate in-flight spinner for this fetch; nothing here changes because of it.
export default function ScreeningDashboardStats({
  refreshSignal = 0,
  onLoadingChange,
}: {
  refreshSignal?: number;
  onLoadingChange?: (loading: boolean) => void;
}) {
  const t = useT();
  const [stats, setStats] = useState<ScreeningDashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [compareMonth, setCompareMonth] = useState(LAST_MONTH_SENTINEL);
  const [retryKey, setRetryKey] = useState(0);

  const compareOptions = [
    { value: LAST_MONTH_SENTINEL, label: t("screening.compare.last_month") },
    ...pastMonthKeys(12).map((key) => ({ value: key, label: t("screening.compare.vs", { month: formatMonthKey(key) }) })),
  ];

  useEffect(() => {
    setLoading(true);
    onLoadingChange?.(true);
    setError(null);
    reportsApi
      .screeningDashboardStats(compareMonth === LAST_MONTH_SENTINEL ? undefined : compareMonth)
      .then(setStats)
      .catch(setError)
      .finally(() => {
        setLoading(false);
        onLoadingChange?.(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal, compareMonth, retryKey]);

  const handleCompareMonthChange = (event: SelectChangeEvent) => setCompareMonth(event.target.value);

  if (loading) {
    return (
      <Box mb={4}>
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
              <Skeleton variant="rounded" height={240} sx={{ borderRadius: "18px" }} />
            </Grid>
          ))}
        </Grid>
      </Box>
    );
  }

  if (error != null) {
    return <Box mb={3}><FriendlyError error={error} onRetry={() => setRetryKey((k) => k + 1)} /></Box>;
  }

  if (!stats) {
    return null;
  }

  const avg = stats.avg_composite_score != null ? t("screening.points", { n: Math.round(stats.avg_composite_score) }) : "—";

  return (
    <Box mb={3}>
      <Stack direction="row" justifyContent="flex-end" mb={1.5}>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="screening-dashboard-compare-month-label">{t("screening.compare.label")}</InputLabel>
          <Select
            labelId="screening-dashboard-compare-month-label"
            label={t("screening.compare.label")}
            value={compareMonth}
            onChange={handleCompareMonthChange}
          >
            {compareOptions.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      <Grid container spacing={2} mb={3}>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatTile emoji="hourglass" tone="sky" value={stats.awaiting_screening} label={t("screening.stat.awaiting_screening")} to="/screening/list" />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatTile emoji="bar_chart" tone="sun" value={stats.awaiting_ranking} label={t("screening.stat.awaiting_ranking")} to="/screening/list" />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatTile emoji="rocket" tone="ok" value={stats.auto_advanced_this_month} label={t("screening.stat.auto_advanced")} {...trendProps(stats.auto_advanced_this_month_trend, t)} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatTile emoji="warning" tone="coral" value={stats.failed_this_month} label={t("screening.stat.failed")} {...trendProps(stats.failed_this_month_trend, t, false)} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatTile emoji="target" tone="brand" value={avg} label={t("screening.stat.avg_score")} {...trendProps(stats.avg_composite_score_trend, t)} />
        </Grid>
      </Grid>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 4 }}>
          <ChartCard title={t("screening.chart.recommendation")}>
            {stats.recommendation_breakdown.length === 0 ? (
              <EmptyState compact illustration="no-data" title={t("screening.chart.empty")} />
            ) : (
              <LabeledDonutChart title="" rows={stats.recommendation_breakdown} />
            )}
          </ChartCard>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <ChartCard title={t("screening.chart.distribution")}>
            <MatchScoreDistributionChart rows={stats.composite_score_distribution} />
          </ChartCard>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <ChartCard title={t("screening.chart.missing_skills")}>
            {stats.top_missing_skills.length === 0 ? (
              <EmptyState compact illustration="done" title={t("screening.chart.no_missing")} />
            ) : (
              <TopSkillsBarChart rows={stats.top_missing_skills} />
            )}
          </ChartCard>
        </Grid>
      </Grid>
    </Box>
  );
}
