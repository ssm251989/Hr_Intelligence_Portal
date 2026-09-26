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
import { useTheme } from "@mui/material/styles";

import { reportsApi } from "../api/client";
import type { ShortlistingDashboardStatsResponse } from "../api/types";
import { useT } from "../i18n";
import { Emoji, EmptyState, FriendlyError, StatTile } from "../ui-kit";
import { formatMonthKey, pastMonthKeys } from "../utils/datetime";
import LabeledDonutChart from "./LabeledDonutChart";
import MatchScoreDistributionChart from "./MatchScoreDistributionChart";
import RecentShortlistedTable from "./RecentShortlistedTable";
import { trendProps } from "./screening/trend";

// "From Screening" is every application screening has ever produced a composite_score
// for (see backend app/reports/stats.py shortlisting_funnel_counts) -- a superset of the
// other four, not a mutually-exclusive bucket of its own. A donut's slices must sum to one
// real whole, so it's shown as its own headline number instead of a 5th slice.
const CURRENT_STAGE_LABELS = new Set(["Under Review", "Shortlisted", "On Hold", "Rejected"]);

const LAST_MONTH_SENTINEL = "last_month";

// onLoadingChange is optional -- purely so the page's own RefreshButton can show an
// accurate in-flight spinner for this fetch; nothing here changes because of it.
export default function ShortlistingDashboardStats({
  refreshSignal = 0,
  onLoadingChange,
}: {
  refreshSignal?: number;
  onLoadingChange?: (loading: boolean) => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [stats, setStats] = useState<ShortlistingDashboardStatsResponse | null>(null);
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
      .shortlistingDashboardStats(compareMonth === LAST_MONTH_SENTINEL ? undefined : compareMonth)
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
          {Array.from({ length: 2 }).map((_, i) => (
            <Grid key={i} size={{ xs: 12, md: 6 }}>
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

  const screenedOverall = stats.funnel.find((stage) => stage.label === "From Screening")?.count ?? 0;
  const avg = stats.avg_composite_score_shortlisted != null ? t("screening.points", { n: Math.round(stats.avg_composite_score_shortlisted) }) : "—";

  return (
    <Box mb={3}>
      <Stack direction="row" justifyContent="flex-end" mb={1.5}>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="shortlisting-dashboard-compare-month-label">{t("screening.compare.label")}</InputLabel>
          <Select
            labelId="shortlisting-dashboard-compare-month-label"
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
          <StatTile emoji="clipboard" tone="sky" value={stats.total_in_shortlisting} label={t("shortlisting.stat.total")} to="/shortlisting/list" />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatTile emoji="new" tone="sun" value={stats.new_this_month} label={t("shortlisting.stat.new")} {...trendProps(stats.new_this_month_trend, t)} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatTile emoji="magnifier" tone="brand" value={stats.moved_from_screening_this_month} label={t("shortlisting.stat.moved")} {...trendProps(stats.moved_from_screening_this_month_trend, t)} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatTile emoji="star" tone="ok" value={stats.shortlisted_this_month} label={t("shortlisting.stat.shortlisted")} {...trendProps(stats.shortlisted_this_month_trend, t)} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatTile emoji="target" tone="brand" value={avg} label={t("shortlisting.stat.avg_score")} {...trendProps(stats.avg_composite_score_shortlisted_trend, t)} />
        </Grid>
      </Grid>

      <Grid container spacing={3} mb={3}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card sx={{ height: "100%" }}>
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="baseline" mb={2}>
                <Typography variant="h6">{t("shortlisting.chart.breakdown")}</Typography>
                <Typography variant="caption" sx={{ color: f.muted }}>
                  {t("shortlisting.chart.screened_overall", { count: screenedOverall })}
                </Typography>
              </Stack>
              <LabeledDonutChart title="" rows={stats.funnel.filter((stage) => CURRENT_STAGE_LABELS.has(stage.label))} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>{t("screening.chart.distribution")}</Typography>
              <MatchScoreDistributionChart rows={stats.composite_score_distribution} />
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Stack direction="row" spacing={1} alignItems="center" mb={2}>
            <Emoji name="light_bulb" size={22} />
            <Typography variant="h6">{t("shortlisting.insights.title")}</Typography>
          </Stack>
          {stats.insights.length === 0 ? (
            <Typography variant="body2" sx={{ color: f.muted }}>{t("shortlisting.insights.empty")}</Typography>
          ) : (
            <Box component="ul" sx={{ listStyle: "none", m: 0, p: 0, display: "flex", flexDirection: "column", gap: 1 }}>
              {stats.insights.map((insight, i) => (
                <Box component="li" key={i} sx={{ fontSize: 14, px: 1.25, py: 1, bgcolor: f.surface2, borderLeft: `3px solid ${f.sun}`, borderRadius: "0 8px 8px 0" }}>
                  {insight}
                </Box>
              ))}
            </Box>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack direction="row" spacing={1} alignItems="center" mb={2}>
            <Emoji name="star" size={22} />
            <Typography variant="h6">{t("shortlisting.recent.title")}</Typography>
          </Stack>
          {stats.recent_shortlisted.length === 0 ? (
            <EmptyState compact illustration="people-search" title={t("shortlisting.recent.empty")} />
          ) : (
            <RecentShortlistedTable rows={stats.recent_shortlisted} />
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
