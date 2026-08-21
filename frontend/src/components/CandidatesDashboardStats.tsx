import { useEffect, useState } from "react";
import GroupsOutlinedIcon from "@mui/icons-material/GroupsOutlined";
import LanguageOutlinedIcon from "@mui/icons-material/LanguageOutlined";
import PercentOutlinedIcon from "@mui/icons-material/PercentOutlined";
import PersonAddAltOutlinedIcon from "@mui/icons-material/PersonAddAltOutlined";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import FormControl from "@mui/material/FormControl";
import Grid from "@mui/material/Grid";
import InputLabel from "@mui/material/InputLabel";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, reportsApi } from "../api/client";
import { candidateSourceLabel, type CandidatesDashboardStatsResponse } from "../api/types";
import { formatMonthKey, pastMonthKeys } from "../utils/datetime";
import AllSkillsDialog from "./AllSkillsDialog";
import DataSourcesPanel from "./DataSourcesPanel";
import LabeledDonutChart from "./LabeledDonutChart";
import MatchScoreDistributionChart from "./MatchScoreDistributionChart";
import RecentCandidatesTable from "./RecentCandidatesTable";
import StatCard, { StatCardSkeleton } from "./StatCard";
import TopSkillsBarChart from "./TopSkillsBarChart";

const LAST_MONTH_SENTINEL = "last_month";
const COMPARE_OPTIONS = [
  { value: LAST_MONTH_SENTINEL, label: "vs last month" },
  ...pastMonthKeys(12).map((key) => ({ value: key, label: `vs ${formatMonthKey(key)}` })),
];

const BLUE = "#2a78d6";
const ORANGE = "#eb6834";
const AQUA = "#1baf7a";
const YELLOW = "#eda100";
const MAGENTA = "#e87ba4";

// refreshSignal is optional -- the Dashboard now lives on its own route (/candidates/dashboard),
// so navigating to it after an import on the separate Import page already remounts this
// component and refetches; nothing external needs to force a re-fetch anymore.
// onLoadingChange is likewise optional -- purely so the page's own RefreshButton can show
// an accurate in-flight spinner for this fetch; nothing here changes because of it.
export default function CandidatesDashboardStats({
  refreshSignal = 0,
  onLoadingChange,
}: {
  refreshSignal?: number;
  onLoadingChange?: (loading: boolean) => void;
}) {
  const [stats, setStats] = useState<CandidatesDashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [compareMonth, setCompareMonth] = useState(LAST_MONTH_SENTINEL);
  const [allSkillsOpen, setAllSkillsOpen] = useState(false);

  useEffect(() => {
    setLoading(true);
    onLoadingChange?.(true);
    setError(null);
    reportsApi
      .candidatesDashboardStats(compareMonth === LAST_MONTH_SENTINEL ? undefined : compareMonth)
      .then(setStats)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load candidates dashboard")))
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
        <Grid container spacing={3} mb={3}>
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
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, md: 8.5 }}>
            <Card variant="outlined" sx={{ height: "100%" }}>
              <CardContent>
                <Skeleton variant="text" width="30%" height={32} sx={{ mb: 2 }} />
                <Skeleton variant="rounded" height={220} />
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 3.5 }}>
            <Card variant="outlined" sx={{ height: "100%" }}>
              <CardContent>
                <Skeleton variant="text" width="50%" height={32} sx={{ mb: 2 }} />
                <Skeleton variant="rounded" height={220} />
              </CardContent>
            </Card>
          </Grid>
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

  const sourceRows = stats.by_source.map((row) => ({ label: candidateSourceLabel(row.label), count: row.count }));

  return (
    <Box mb={3}>
      <Stack direction="row" justifyContent="flex-end" mb={1.5}>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="candidates-dashboard-compare-month-label">Compare</InputLabel>
          <Select
            labelId="candidates-dashboard-compare-month-label"
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
            label="Total Candidates"
            value={stats.total_candidates}
            icon={GroupsOutlinedIcon}
            color={BLUE}
            trend={stats.total_candidates_trend}
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
            label="From Career Portals"
            value={stats.from_career_portal}
            icon={LanguageOutlinedIcon}
            color={AQUA}
            trend={stats.from_career_portal_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Manually Added"
            value={stats.manually_added}
            icon={UploadFileOutlinedIcon}
            color={YELLOW}
            trend={stats.manually_added_trend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
          <StatCard
            variant="compact"
            label="Avg Match Score"
            value={stats.avg_match_score != null ? `${Math.round(stats.avg_match_score)}%` : "—"}
            icon={PercentOutlinedIcon}
            color={MAGENTA}
            trend={stats.avg_match_score_trend}
          />
        </Grid>
      </Grid>

      <Grid container spacing={3} mb={3}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <LabeledDonutChart title="Candidates by Source" rows={sourceRows} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Top Skills
              </Typography>
              <TopSkillsBarChart rows={stats.top_skills} />
              {stats.top_skills.length > 0 && (
                <Link component="button" variant="body2" onClick={() => setAllSkillsOpen(true)} sx={{ mt: 1.5, display: "inline-block" }}>
                  View all skills
                </Link>
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Match Score Distribution
              </Typography>
              <MatchScoreDistributionChart rows={stats.match_score_distribution} />
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <AllSkillsDialog open={allSkillsOpen} onClose={() => setAllSkillsOpen(false)} />

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 8.5 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={1}>
                Recent Candidates
              </Typography>
              <RecentCandidatesTable rows={stats.recent_candidates} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 3.5 }}>
          <Card variant="outlined" sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Data Sources
              </Typography>
              <DataSourcesPanel rows={stats.data_sources} />
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
