import { useEffect, useState, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { reportsApi } from "../api/client";
import { candidateSourceLabel, type CandidatesDashboardStatsResponse, type StatTrend } from "../api/types";
import { useT, type TFunction } from "../i18n";
import { FriendlyError, InfoTip, StatTile } from "../ui-kit";
import { formatMonthKey, pastMonthKeys } from "../utils/datetime";
import AllSkillsDialog from "./AllSkillsDialog";
import DataSourcesPanel from "./DataSourcesPanel";
import MatchScoreDistributionChart from "./MatchScoreDistributionChart";
import RecentCandidatesTable from "./RecentCandidatesTable";
import TopSkillsBarChart from "./TopSkillsBarChart";
import SourceDonut from "./candidates/SourceDonut";
import { useFresh } from "./candidates/stages";

// Part 15.4 Candidates dashboard: StatTiles (every number with its word + a trend line),
// charts coloured from theme.palette.chart, same data (reportsApi.candidatesDashboardStats)
// and the same "compare with" month picker as before.

const LAST_MONTH_SENTINEL = "last_month";

// refreshSignal/onLoadingChange are optional -- the page's Refresh button bumps the first
// and reads the second for its spinner.
export default function CandidatesDashboardStats({
  refreshSignal = 0,
  onLoadingChange,
}: {
  refreshSignal?: number;
  onLoadingChange?: (loading: boolean) => void;
}) {
  const t = useT();
  const f = useFresh();
  const [stats, setStats] = useState<CandidatesDashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [compareMonth, setCompareMonth] = useState(LAST_MONTH_SENTINEL);
  const [allSkillsOpen, setAllSkillsOpen] = useState(false);
  const [retryKey, setRetryKey] = useState(0);

  const compareOptions = [
    { value: LAST_MONTH_SENTINEL, label: t("candidates.dash.vs_last_month") },
    ...pastMonthKeys(12).map((key) => ({ value: key, label: t("candidates.dash.vs_month", { month: formatMonthKey(key) }) })),
  ];

  useEffect(() => {
    setLoading(true);
    onLoadingChange?.(true);
    setError(null);
    reportsApi
      .candidatesDashboardStats(compareMonth === LAST_MONTH_SENTINEL ? undefined : compareMonth)
      .then(setStats)
      .catch((err) => setError(err))
      .finally(() => {
        setLoading(false);
        onLoadingChange?.(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal, compareMonth, retryKey]);

  const handleCompareMonthChange = (event: SelectChangeEvent) => setCompareMonth(event.target.value);

  const panel = (title: string, children: ReactNode, info?: string, footer?: ReactNode) => (
    <Card sx={{ p: 2.25, height: "100%", display: "flex", flexDirection: "column" }}>
      <Typography variant="h6" component="h2" sx={{ fontWeight: 700, fontSize: 16, mb: 1.5 }}>
        {title}
        {info && <InfoTip text={info} />}
      </Typography>
      <Box sx={{ flex: 1, minWidth: 0 }}>{children}</Box>
      {footer}
    </Card>
  );

  const tileGrid = { display: "grid", gap: 1.75, gridTemplateColumns: { xs: "repeat(2, minmax(0, 1fr))", md: "repeat(3, minmax(0, 1fr))", lg: "repeat(5, minmax(0, 1fr))" }, mb: 2.25 };

  if (loading) {
    return (
      <Box mb={4}>
        <Stack direction="row" justifyContent="flex-end" mb={1.5}>
          <Skeleton variant="rounded" width={200} height={40} />
        </Stack>
        <Box sx={tileGrid}>
          {Array.from({ length: 5 }).map((_, i) => <StatTile key={i} emoji="technologist" value="" label="" loading />)}
        </Box>
        <Box sx={{ display: "grid", gap: 2.25, gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" } }}>
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} variant="rounded" height={240} sx={{ borderRadius: "18px" }} />)}
        </Box>
      </Box>
    );
  }

  if (error) {
    return <Box mb={3}><FriendlyError error={error} onRetry={() => setRetryKey((k) => k + 1)} /></Box>;
  }

  if (!stats) {
    return null;
  }

  const sourceRows = stats.by_source.map((row) => ({ label: candidateSourceLabel(row.label), count: row.count }));

  return (
    <Box mb={3}>
      <Stack direction="row" justifyContent="flex-end" mb={1.5}>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="candidates-dashboard-compare-month-label">{t("candidates.dash.compare")}</InputLabel>
          <Select labelId="candidates-dashboard-compare-month-label" label={t("candidates.dash.compare")} value={compareMonth} onChange={handleCompareMonthChange}>
            {compareOptions.map((option) => (
              <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      <Box sx={tileGrid}>
        <StatTile emoji="people" tone="sky" value={stats.total_candidates} label={t("candidates.dash.total")} {...trendProps(t, stats.total_candidates_trend)} to="/candidates/list" />
        <StatTile emoji="new" tone="coral" value={stats.new_this_month} label={t("candidates.dash.new_month")} {...trendProps(t, stats.new_this_month_trend)} />
        <StatTile emoji="globe" tone="brand" value={stats.from_career_portal} label={t("candidates.dash.career_portal")} {...trendProps(t, stats.from_career_portal_trend)} />
        <StatTile emoji="inbox" tone="sun" value={stats.manually_added} label={t("candidates.dash.manual")} {...trendProps(t, stats.manually_added_trend)} />
        <StatTile
          emoji="star"
          tone="ok"
          value={stats.avg_match_score != null ? `${Math.round(stats.avg_match_score)}%` : "—"}
          label={t("candidates.dash.avg_match")}
          {...trendProps(t, stats.avg_match_score_trend)}
        />
      </Box>

      <Box sx={{ display: "grid", gap: 2.25, gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" }, mb: 2.25 }}>
        {panel(t("candidates.dash.by_source"), <SourceDonut rows={sourceRows} />)}
        {panel(
          t("candidates.dash.top_skills"),
          <TopSkillsBarChart rows={stats.top_skills} emptyMessage={t("candidates.dash.no_skills")} />,
          undefined,
          stats.top_skills.length > 0 ? (
            <Link component="button" variant="body2" onClick={() => setAllSkillsOpen(true)} sx={{ mt: 1.5, alignSelf: "flex-start", fontWeight: 700 }}>
              {t("candidates.dash.all_skills")}
            </Link>
          ) : undefined,
        )}
        {panel(t("candidates.dash.match_distribution"), <MatchScoreDistributionChart rows={stats.match_score_distribution} />, t("candidates.dash.match_info"))}
      </Box>

      <AllSkillsDialog open={allSkillsOpen} onClose={() => setAllSkillsOpen(false)} />

      <Box sx={{ display: "grid", gap: 2.25, gridTemplateColumns: { xs: "1fr", md: "minmax(0, 2.4fr) minmax(0, 1fr)" } }}>
        {panel(t("candidates.dash.recent"), <RecentCandidatesTable rows={stats.recent_candidates} />)}
        {panel(t("candidates.dash.data_sources"), <DataSourcesPanel rows={stats.data_sources} />, t("candidates.dash.data_sources_info"))}
      </Box>
      <Typography sx={{ color: f.muted, fontSize: 12, mt: 1.5 }}>{t("candidates.dash.active", { count: stats.active_candidates })}</Typography>
    </Box>
  );
}

function trendProps(t: TFunction, trend: StatTrend | undefined): { trend?: string; trendDirection?: "up" | "down" | "flat" } {
  if (!trend || trend.pct_change == null) return {};
  const pct = Math.round(trend.pct_change);
  const month = formatMonthKey(trend.compare_month);
  return {
    trend: t(trend.is_approximate ? "candidates.dash.trend_approx" : "candidates.dash.trend", { pct: Math.abs(pct), month }),
    trendDirection: pct > 0 ? "up" : pct < 0 ? "down" : "flat",
  };
}
