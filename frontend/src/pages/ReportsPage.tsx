import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import GlobalStyles from "@mui/material/GlobalStyles";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { jobsApi, reportsApi } from "../api/client";
import type { AuditLogPage, ApplicationTimelineResponse, JobRoleRead, JobSummaryResponse, PipelineResponse } from "../api/types";
import AnalyticsPanel from "../components/AnalyticsPanel";
import RefreshButton from "../components/RefreshButton";
import ExportBar from "../components/reports/ExportBar";
import SavedReportsCard from "../components/reports/SavedReportsCard";
import StatusBreakdown from "../components/reports/StatusBreakdown";
import { downloadCsv, fileSlug } from "../components/reports/reportExport";
import { useT } from "../i18n";
import { EmptyState, Emoji, FriendlyError, InfoTip, PageHeader, StatTile, Timeline, humanise } from "../ui-kit";

const AUDIT_PAGE_SIZE = 20;

const words = (s?: string | null) => (s ? humanise(s) : "—");

function Loading() {
  return (
    <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
      <CircularProgress aria-label="Loading" />
    </Box>
  );
}

function PipelineView({ jobs }: { jobs: JobRoleRead[] }) {
  const t = useT();
  const [jobId, setJobId] = useState("");
  const [data, setData] = useState<PipelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const load = async (selectedJobId: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await reportsApi.pipeline(selectedJobId || undefined);
      setData(result);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(jobId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleJobChange = (value: string) => {
    setJobId(value);
    load(value);
  };

  const jobTitle = jobs.find((j) => j.id === jobId)?.title;
  const stagesInUse = data ? data.by_status.filter((r) => r.count > 0).length : 0;

  return (
    <Stack spacing={2.5}>
      <TextField select label={t("reports.pipeline.filter")} value={jobId} onChange={(e) => handleJobChange(e.target.value)} sx={{ minWidth: 260, maxWidth: 420 }} data-print-hide>
        <MenuItem value="">{t("reports.pipeline.all_jobs")}</MenuItem>
        {jobs.map((job) => (
          <MenuItem key={job.id} value={job.id}>
            {job.title}
          </MenuItem>
        ))}
      </TextField>

      {error !== null && <FriendlyError error={error} onRetry={() => load(jobId)} compact />}

      {loading ? (
        <Loading />
      ) : data ? (
        <>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 6 }}>
              <StatTile emoji="inbox" tone="brand" value={data.total} label={t("reports.stat.applications", { count: data.total })} />
            </Grid>
            <Grid size={{ xs: 12, sm: 6 }}>
              <StatTile emoji="compass" tone="sky" value={stagesInUse} label={t("reports.stat.stages", { count: stagesInUse })} />
            </Grid>
          </Grid>
          {data.by_status.length === 0 ? (
            <EmptyState compact illustration="no-data" title={t("reports.pipeline.empty")} hint={t("reports.pipeline.empty_hint")} />
          ) : (
            <StatusBreakdown total={data.total} byStatus={data.by_status} exportName={`${t("reports.tab.pipeline")} ${jobTitle ?? t("reports.pipeline.all_jobs")}`} />
          )}
        </>
      ) : null}
    </Stack>
  );
}

// Also shown on the Overview page -- keep the `jobs` prop and default export shape.
export function JobSummaryView({ jobs }: { jobs: JobRoleRead[] }) {
  const t = useT();
  const [jobId, setJobId] = useState("");
  const [data, setData] = useState<JobSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const handleJobChange = async (value: string) => {
    setJobId(value);
    setData(null);
    if (!value) return;
    setLoading(true);
    setError(null);
    try {
      const result = await reportsApi.jobSummary(value);
      setData(result);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const score = (v: number | null | undefined) => (v != null ? v.toFixed(1) : "—");
  const jobTitle = jobs.find((j) => j.id === jobId)?.title ?? "";

  return (
    <Stack spacing={2.5}>
      <TextField select label={t("reports.summary.pick")} value={jobId} onChange={(e) => handleJobChange(e.target.value)} sx={{ minWidth: 260, maxWidth: 420 }} data-print-hide>
        {jobs.length === 0 && <MenuItem disabled value="">{t("reports.summary.no_jobs")}</MenuItem>}
        {jobs.map((job) => (
          <MenuItem key={job.id} value={job.id}>
            {job.title}
          </MenuItem>
        ))}
      </TextField>

      {error !== null && <FriendlyError error={error} onRetry={() => handleJobChange(jobId)} compact />}

      {!jobId ? (
        <EmptyState compact illustration="report" title={t("reports.summary.pick_first")} />
      ) : loading ? (
        <Loading />
      ) : data ? (
        <>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, sm: 4 }}>
              <StatTile emoji="inbox" tone="brand" value={data.total_applications} label={t("reports.stat.applications", { count: data.total_applications })} />
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <StatTile emoji="target" tone="sky" value={score(data.average_match_score)} label={t("reports.stat.avg_match")} />
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <StatTile emoji="trophy" tone="sun" value={score(data.average_ranking_score)} label={t("reports.stat.avg_rank")} />
            </Grid>
          </Grid>
          {data.by_status.length === 0 ? (
            <EmptyState compact illustration="no-data" title={t("reports.summary.empty")} />
          ) : (
            <StatusBreakdown total={data.total_applications} byStatus={data.by_status} exportName={`${t("reports.tab.summary")} ${jobTitle}`} />
          )}
        </>
      ) : null}
    </Stack>
  );
}

function AuditTrailView() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [entityType, setEntityType] = useState("");
  const [entityId, setEntityId] = useState("");
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<AuditLogPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const load = async (nextOffset: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await reportsApi.auditLog({
        entityType: entityType || undefined,
        entityId: entityId || undefined,
        action: action || undefined,
        limit: AUDIT_PAGE_SIZE,
        offset: nextOffset,
      });
      setData(result);
      setOffset(nextOffset);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFilter = () => load(0);

  const exportCsv = () =>
    data &&
    downloadCsv(
      fileSlug(t("reports.tab.audit")),
      [t("reports.audit.col_when"), t("reports.audit.col_type"), t("reports.audit.col_id"), t("reports.audit.col_action"), t("reports.audit.col_who")],
      data.items.map((i) => [new Date(i.created_at).toLocaleString(), words(i.entity_type), i.entity_id, words(i.action), i.actor]),
    );

  return (
    <Stack spacing={2.5}>
      <Box
        component="form"
        onSubmit={(e) => {
          e.preventDefault();
          handleFilter();
        }}
        data-print-hide
        sx={{ display: "flex", flexWrap: "wrap", gap: 1.5, alignItems: "center" }}
      >
        <TextField label={t("reports.audit.type")} value={entityType} onChange={(e) => setEntityType(e.target.value)} size="small" placeholder="application" />
        <TextField label={t("reports.audit.id")} value={entityId} onChange={(e) => setEntityId(e.target.value)} size="small" sx={{ minWidth: 240 }} />
        <TextField label={t("reports.audit.action")} value={action} onChange={(e) => setAction(e.target.value)} size="small" placeholder="salary_validated" />
        <InfoTip text={t("reports.audit.filter_help")} label={t("reports.info_label")} />
        <Button type="submit" variant="outlined" size="small" disabled={loading}>
          {t("reports.audit.filter")}
        </Button>
      </Box>

      {error !== null && <FriendlyError error={error} onRetry={() => load(offset)} compact />}

      {loading ? (
        <Loading />
      ) : data ? (
        <>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t("reports.audit.col_when")}</TableCell>
                  <TableCell>{t("reports.audit.col_type")}</TableCell>
                  <TableCell>{t("reports.audit.col_id")}</TableCell>
                  <TableCell>{t("reports.audit.col_action")}</TableCell>
                  <TableCell>{t("reports.audit.col_who")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{new Date(item.created_at).toLocaleString()}</TableCell>
                    <TableCell>{words(item.entity_type)}</TableCell>
                    <TableCell sx={{ fontFamily: "monospace", fontSize: 12, color: f.muted }}>{item.entity_id}</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>{words(item.action)}</TableCell>
                    <TableCell>{item.actor}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          {data.items.length === 0 && <EmptyState compact illustration="search" title={t("reports.audit.empty")} hint={t("reports.audit.empty_hint")} />}
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ flexWrap: "wrap", rowGap: 1 }} data-print-hide>
            <Button size="small" variant="outlined" disabled={offset === 0 || loading} onClick={() => load(Math.max(0, offset - AUDIT_PAGE_SIZE))}>
              {t("reports.audit.prev")}
            </Button>
            <Button size="small" variant="outlined" disabled={loading || offset + AUDIT_PAGE_SIZE >= data.total} onClick={() => load(offset + AUDIT_PAGE_SIZE)}>
              {t("reports.audit.next")}
            </Button>
            <Typography variant="body2" sx={{ color: f.muted }}>
              {data.total === 0
                ? t("reports.audit.range_none")
                : t("reports.audit.range", { from: offset + 1, to: Math.min(offset + AUDIT_PAGE_SIZE, data.total), count: data.total })}
            </Typography>
            <Box sx={{ flex: 1 }} />
            <ExportBar onCsv={exportCsv} disabled={data.items.length === 0} />
          </Stack>
        </>
      ) : null}
    </Stack>
  );
}

function eventEmoji(action?: string | null): string {
  const a = (action ?? "").toLowerCase();
  if (a.includes("interview")) return "calendar";
  if (a.includes("offer")) return "envelope";
  if (a.includes("salary")) return "money";
  if (a.includes("bgv") || a.includes("background")) return "shield";
  if (a.includes("reject") || a.includes("disqualif")) return "cross";
  if (a.includes("select") || a.includes("shortlist") || a.includes("approv")) return "check";
  if (a.includes("screen") || a.includes("score")) return "magnifier";
  if (a.includes("created") || a.includes("upload")) return "inbox";
  if (a.includes("email") || a.includes("mail")) return "mail";
  return "memo";
}

function TimelineView() {
  const t = useT();
  const [applicationId, setApplicationId] = useState("");
  const [data, setData] = useState<ApplicationTimelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [missingId, setMissingId] = useState(false);

  const handleLoad = async () => {
    if (!applicationId) {
      setMissingId(true);
      return;
    }
    setMissingId(false);
    setLoading(true);
    setError(null);
    try {
      const result = await reportsApi.applicationTimeline(applicationId);
      setData(result);
    } catch (err) {
      setError(err);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const exportCsv = () =>
    data &&
    downloadCsv(
      fileSlug(`${t("reports.tab.timeline")} ${applicationId}`),
      [t("reports.audit.col_when"), t("reports.audit.col_action"), t("reports.audit.col_who")],
      data.events.map((e) => [new Date(e.created_at).toLocaleString(), words(e.action), e.actor]),
    );

  return (
    <Stack spacing={2.5}>
      <Box
        component="form"
        onSubmit={(e) => {
          e.preventDefault();
          handleLoad();
        }}
        data-print-hide
        sx={{ display: "flex", flexWrap: "wrap", gap: 1.5, alignItems: "flex-start" }}
      >
        <TextField
          label={t("reports.timeline.id")}
          value={applicationId}
          onChange={(e) => setApplicationId(e.target.value)}
          size="small"
          sx={{ minWidth: 320 }}
          error={missingId}
          helperText={missingId ? t("reports.timeline.id_missing") : t("reports.timeline.id_help")}
        />
        <Button type="submit" variant="contained" disabled={loading}>
          {loading ? t("reports.loading") : t("reports.timeline.load")}
        </Button>
      </Box>

      {error !== null && <FriendlyError error={error} onRetry={handleLoad} compact />}

      {data &&
        (data.events.length === 0 ? (
          <EmptyState compact illustration="empty" title={t("reports.timeline.empty")} />
        ) : (
          <>
            <Timeline
              items={data.events.map((event) => ({
                id: event.id,
                emoji: eventEmoji(event.action),
                title: words(event.action),
                meta: t("reports.timeline.meta", { when: new Date(event.created_at).toLocaleString(), who: event.actor ?? "—" }),
              }))}
            />
            <ExportBar onCsv={exportCsv} />
          </>
        ))}
      {!data && !error && <EmptyState compact illustration="to-do-list" title={t("reports.timeline.start")} />}
    </Stack>
  );
}

export default function ReportsPage() {
  const t = useT();
  const [tab, setTab] = useState(0);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [error, setError] = useState<unknown>(null);
  // `refreshing` tracks only this page's own jobs fetch (always runs, always resolves) --
  // not any of the 4 tab views' own fetches below, two of which (Job Summary before a job
  // is picked, Timeline before an ID is entered) never auto-fetch at all, so gating the
  // button on them could leave it disabled forever. Each tab already shows its own
  // spinner while its own fetch is in flight, unaffected by this.
  const [refreshing, setRefreshing] = useState(false);
  // Bumped on Refresh and used as each tab view's `key` -- remounting resets that view's
  // own internal filter state (job selection, audit filters, timeline application id) back
  // to its defaults and re-runs whatever fetch it does on mount, without needing to lift
  // any of those 4 views' state up into this page.
  const [resetKey, setResetKey] = useState(0);
  const [savedTick, setSavedTick] = useState(0);

  const loadJobs = () =>
    jobsApi
      .list()
      .then((rows) => {
        setJobs(rows);
        setError(null);
      })
      .catch((err) => setError(err));

  useEffect(() => {
    loadJobs();
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    setTab(0);
    setResetKey((k) => k + 1);
    try {
      await loadJobs();
    } finally {
      setRefreshing(false);
    }
  };

  const tabs = [
    { emoji: "compass", label: t("reports.tab.pipeline") },
    { emoji: "briefcase", label: t("reports.tab.summary") },
    { emoji: "clipboard", label: t("reports.tab.audit") },
    { emoji: "hourglass", label: t("reports.tab.timeline") },
  ];

  return (
    <Box>
      {/* "Save as PDF" prints just the report: hide the menu and page controls. */}
      <GlobalStyles styles={{ "@media print": { "aside, nav, [data-print-hide]": { display: "none !important" } } }} />
      <PageHeader
        emoji="bar_chart"
        title={t("reports.title")}
        purpose={t("reports.purpose")}
        tourKey="reports"
        extra={
          <Box data-print-hide>
            <RefreshButton loading={refreshing} onRefresh={handleRefresh} label={t("reports.refresh")} />
          </Box>
        }
      />

      {error !== null && (
        <Box sx={{ mb: 2 }}>
          <FriendlyError error={error} onRetry={loadJobs} compact />
        </Box>
      )}

      <Stack spacing={3}>
        <Card>
          <Tabs
            value={tab}
            onChange={(_e, value) => setTab(value)}
            variant="scrollable"
            allowScrollButtonsMobile
            aria-label={t("reports.tabs_label")}
            sx={{ px: 1.5, pt: 1, borderBottom: 1, borderColor: "divider" }}
            data-print-hide
          >
            {tabs.map((x) => (
              <Tab key={x.label} label={x.label} icon={<Emoji name={x.emoji} size={18} />} iconPosition="start" sx={{ minHeight: 48 }} />
            ))}
          </Tabs>
          <Box sx={{ p: { xs: 2, sm: 3 } }}>
            {tab === 0 && <PipelineView key={resetKey} jobs={jobs} />}
            {tab === 1 && <JobSummaryView key={resetKey} jobs={jobs} />}
            {tab === 2 && <AuditTrailView key={resetKey} />}
            {tab === 3 && <TimelineView key={resetKey} />}
          </Box>
        </Card>
        <SavedReportsCard reloadKey={resetKey + savedTick} />
        <Box data-print-hide>
          <AnalyticsPanel onSaved={() => setSavedTick((n) => n + 1)} />
        </Box>
      </Stack>
    </Box>
  );
}
