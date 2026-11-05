import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import SearchIcon from "@mui/icons-material/Search";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import Grid from "@mui/material/Grid";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import ListItemIcon from "@mui/material/ListItemIcon";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Pagination from "@mui/material/Pagination";
import Skeleton from "@mui/material/Skeleton";
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
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { jobsApi } from "../api/client";
import { jobsExtraApi, PIPELINE_STAGES, type JobPipelineRow, type JobStage } from "../api/jobsExtra";
import type { JobRoleRead, JobsDashboardStatsResponse, LabeledCount, TopJobItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { OTHER_COLOR, toBreakdownSlices } from "../components/BreakdownLegend";
import ConfirmDialog from "../components/ConfirmDialog";
import CreateJobWizard from "../components/CreateJobWizard";
import DepartmentBreakdownPanel from "../components/DepartmentBreakdownPanel";
import JobDetailsDialog from "../components/JobDetailsDialog";
import JobFiltersPanel, { applyJobFilters, EMPTY_JOB_FILTERS } from "../components/JobFiltersPanel";
import type { JobFilters } from "../components/JobFiltersPanel";
import JobsDashboardStats from "../components/JobsDashboardStats";
import JobStatusOverviewPanel from "../components/JobStatusOverviewPanel";
import JobTypeChip from "../components/JobTypeChip";
import ListToolbar, { type ListColumn, type ListViewState } from "../components/ListToolbar";
import LocationBreakdownPanel from "../components/LocationBreakdownPanel";
import RecentActivityFeed from "../components/RecentActivityFeed";
import TopPerformingJobs from "../components/TopPerformingJobs";
import AutoCloseNote from "../components/jobs/AutoCloseNote";
import JobsHealthCard from "../components/jobs/JobsHealthCard";
import JobHealthChip from "../components/jobs/JobHealthChip";
import CloseJobDialog from "../components/jobs/CloseJobDialog";
import { automationApi, type JobsHealth } from "../api/automationApi";
import JobTemplateLibrary from "../components/jobs/JobTemplateLibrary";
import { STAGE_STYLE } from "../components/jobs/jobStages";
import ReopenJobDialog from "../components/jobs/ReopenJobDialog";
import { useT, type TFunction } from "../i18n";
import { EmptyState, Emoji, FriendlyError, InfoTip, PageHeader, StatusChip, statusStyle } from "../ui-kit";
import { downloadCsv } from "../utils/csv";
import { getDepartmentIcon } from "../utils/departmentIcons";
import { formatExperienceRange } from "../utils/experience";

// L-N5: 25 rows per page by default.
const ROWS_PER_PAGE_OPTIONS = [10, 25, 50, 100];
const DEFAULT_PAGE_SIZE = 25;
const LIST_KEY = "jobs.list";

type StatusTab = "all" | "active" | "draft" | "on_hold" | "closed";

// "Draft" folds in "ready_for_publishing" -- both are pre-live states.
function matchesStatusTab(job: JobRoleRead, tab: StatusTab): boolean {
  switch (tab) {
    case "all":
      return true;
    case "active":
      return job.status === "published";
    case "draft":
      return job.status === "draft" || job.status === "ready_for_publishing";
    case "on_hold":
      return job.status === "on_hold";
    case "closed":
      return job.status === "closed";
  }
}

const stageKey = (stage: JobStage) => `stage_${stage}`;

function buildColumns(t: TFunction): ListColumn[] {
  return [
    { key: "title", label: t("jobs.col.title") },
    { key: "department", label: t("jobs.col.department") },
    { key: "location", label: t("jobs.col.location") },
    { key: "type", label: t("jobs.col.type") },
    ...PIPELINE_STAGES.map((s) => ({ key: stageKey(s), label: t(`jobs.stage.${s}`) })),
    { key: "applications", label: t("jobs.col.applications") },
    { key: "openings", label: t("jobs.col.openings") },
    { key: "status", label: t("jobs.col.status") },
    { key: "health", label: t("jobhealth.col.health") }, // Part 18.7
    { key: "time_to_hire", label: t("jobs.col.time_to_hire") },
  ];
}
const DEFAULT_COLUMNS = ["title", "type", ...PIPELINE_STAGES.map(stageKey), "applications", "openings", "status", "health", "time_to_hire"];

interface ViewFilters extends JobFilters {
  tab: StatusTab;
  search: string;
}
const EMPTY_VIEW_FILTERS: ViewFilters = { ...EMPTY_JOB_FILTERS, tab: "all", search: "" };
const readFilters = (view: ListViewState): ViewFilters => ({ ...EMPTY_VIEW_FILTERS, ...(view.filters as Partial<ViewFilters>) });

// Same maths as the stat tiles' trend arrows, scoped to one job. A null pct with some
// applications always means "grew from nothing" (app/reports/stats.py::pct_change), shown
// as +100%, not as a flat dash.
function ApplicationsTrendCell({ job }: { job: JobRoleRead }) {
  const f = useTheme().palette.fresh;
  const pct = job.applications_pct_change;
  const isZeroBaselineGrowth = pct == null && job.application_count > 0;
  const displayPct = isZeroBaselineGrowth ? 100 : pct;
  const count = <Typography variant="body2" sx={{ fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{job.application_count}</Typography>;
  if (displayPct == null) return count;
  const direction = displayPct > 0 ? "up" : displayPct < 0 ? "down" : "flat";
  const tone = direction === "flat" ? f.muted : direction === "up" ? f.ok : f.coral;
  const ArrowIcon = direction === "down" ? ArrowDownwardIcon : ArrowUpwardIcon;
  return (
    <Stack direction="row" spacing={0.5} alignItems="center">
      {count}
      {direction !== "flat" && <ArrowIcon sx={{ fontSize: 14, color: tone }} />}
      <Typography variant="caption" sx={{ color: tone, fontWeight: 700 }}>
        {isZeroBaselineGrowth ? "+100%" : `${Math.abs(displayPct)}%`}
      </Typography>
    </Stack>
  );
}

function StageCell({ stage, count }: { stage: JobStage; count: number | undefined }) {
  const f = useTheme().palette.fresh;
  const t = useT();
  if (count === undefined) return <Typography variant="body2" sx={{ color: f.muted }}>—</Typography>;
  return (
    <Box component="span" aria-label={t("jobs.stage.tip", { count, stage: t(`jobs.stage.${stage}`) })}
      sx={{
        display: "inline-grid", placeItems: "center", minWidth: 32, height: 26, px: 0.75, borderRadius: "8px", fontWeight: 700, fontSize: 13,
        fontVariantNumeric: "tabular-nums", bgcolor: count > 0 ? f.surface2 : "transparent", border: count > 0 ? `1px solid ${f.line}` : "1px solid transparent",
        color: count > 0 ? f.ink : f.muted,
      }}>
      {count}
    </Box>
  );
}

function PanelCard({ emoji, title, children }: { emoji: string; title: string; children: ReactNode }) {
  return (
    <Card sx={{ height: "100%" }}>
      <CardContent>
        <Typography variant="h6" component="h3" sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1.5 }}>
          <Emoji name={emoji} size={20} />
          {title}
        </Typography>
        {children}
      </CardContent>
    </Card>
  );
}

// Delete only while draft/ready_for_publishing (backend delete_job rule); hold/resume on
// published/on_hold; reopen on closed (J5); "use as template" on any job (J2).
function JobActionsMenu({
  job, onChanged, onDeleted, onError, onReopen, onUseTemplate, onCloseJob,
}: {
  job: JobRoleRead;
  onChanged: (updated: JobRoleRead) => void;
  onDeleted: (jobId: string) => void;
  onError: (what: string, error: unknown) => void;
  onReopen: (job: JobRoleRead) => void;
  onUseTemplate: (job: JobRoleRead) => void;
  onCloseJob: (job: JobRoleRead) => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const [pending, setPending] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const canDelete = job.status === "draft" || job.status === "ready_for_publishing";

  const runAction = async (action: () => Promise<JobRoleRead>) => {
    setAnchorEl(null);
    setPending(true);
    try {
      onChanged(await action());
    } catch (err) {
      onError(t("jobs.error.update"), err);
    } finally {
      setPending(false);
    }
  };

  const runDelete = async () => {
    setConfirmDeleteOpen(false);
    setPending(true);
    try {
      await jobsApi.delete(job.id);
      onDeleted(job.id);
    } catch (err) {
      onError(t("jobs.error.delete"), err);
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <IconButton size="small" onClick={(event) => setAnchorEl(event.currentTarget)} disabled={pending} aria-label={t("jobs.action.more", { title: job.title })} aria-haspopup="menu">
        <MoreVertIcon fontSize="small" />
      </IconButton>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        {job.status === "published" && (
          <MenuItem onClick={() => runAction(() => jobsApi.hold(job.id))}>
            <ListItemIcon><Emoji name="pause" size={18} /></ListItemIcon>
            {t("jobs.action.hold")}
          </MenuItem>
        )}
        {job.status === "on_hold" && (
          <MenuItem onClick={() => runAction(() => jobsApi.resume(job.id))}>
            <ListItemIcon><Emoji name="rocket" size={18} /></ListItemIcon>
            {t("jobs.action.resume")}
          </MenuItem>
        )}
        {(job.status === "published" || job.status === "on_hold") && (
          <MenuItem onClick={() => { setAnchorEl(null); onCloseJob(job); }}>
            <ListItemIcon><Emoji name="door" size={18} /></ListItemIcon>
            {t("closejob.action")}
          </MenuItem>
        )}
        {job.status === "closed" && (
          <MenuItem onClick={() => { setAnchorEl(null); onReopen(job); }}>
            <ListItemIcon><Emoji name="key" size={18} /></ListItemIcon>
            {t("jobs.action.reopen")}
          </MenuItem>
        )}
        <MenuItem onClick={() => { setAnchorEl(null); onUseTemplate(job); }}>
          <ListItemIcon><Emoji name="clipboard" size={18} /></ListItemIcon>
          {t("jobs.action.use_template")}
        </MenuItem>
        {canDelete && (
          <MenuItem onClick={() => { setAnchorEl(null); setConfirmDeleteOpen(true); }} sx={{ color: f.coral }}>
            <ListItemIcon><DeleteOutlineIcon fontSize="small" sx={{ color: f.coral }} /></ListItemIcon>
            {t("jobs.action.delete")}
          </MenuItem>
        )}
      </Menu>
      <ConfirmDialog
        open={confirmDeleteOpen}
        title={t("jobs.delete.title")}
        message={t("jobs.delete.message", { title: job.title })}
        confirmLabel={t("jobs.action.delete")}
        cancelLabel={t("action.cancel")}
        confirming={pending}
        destructive
        onConfirm={runDelete}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </>
  );
}

export default function JobsPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.jobsWrite);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [pipeline, setPipeline] = useState<Record<string, JobPipelineRow>>({});
  // Part 18.7: job health for the "needs attention" panel and the Job health column
  const [health, setHealth] = useState<JobsHealth | null>(null);
  const [closingJob, setClosingJob] = useState<JobRoleRead | null>(null); // Part 18.8
  const healthById = useMemo(() => new Map((health?.jobs ?? []).map((j) => [j.job_id, j])), [health]);
  const [justClosed, setJustClosed] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<{ what: string; error: unknown } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [wizardOpen, setWizardOpen] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templateJob, setTemplateJob] = useState<JobRoleRead | null>(null);
  const [dashboardRefreshSignal, setDashboardRefreshSignal] = useState(0);
  useEffect(() => {
    automationApi.jobsHealth().then(setHealth).catch(() => setHealth(null));
  }, [dashboardRefreshSignal]);
  const [stats, setStats] = useState<JobsDashboardStatsResponse | null>(null);
  const [topJobs, setTopJobs] = useState<TopJobItem[]>([]);
  const [departmentBreakdown, setDepartmentBreakdown] = useState<LabeledCount[]>([]);

  const columns = useMemo(() => buildColumns(t), [t]);
  const [view, setView] = useState<ListViewState>({ columns: DEFAULT_COLUMNS, filters: { ...EMPTY_VIEW_FILTERS } });
  const viewFilters = readFilters(view);
  const statusTab = viewFilters.tab;
  const searchQuery = viewFilters.search;
  const filters: JobFilters = {
    status: viewFilters.status, department: viewFilters.department, location: viewFilters.location, dateFrom: viewFilters.dateFrom, dateTo: viewFilters.dateTo,
  };
  const patchFilters = (patch: Partial<ViewFilters>) => setView((v) => ({ ...v, filters: { ...readFilters(v), ...patch } }));
  const setFilters = (next: JobFilters) => patchFilters(next);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [editingJob, setEditingJob] = useState<JobRoleRead | null>(null);
  const [viewingJob, setViewingJob] = useState<JobRoleRead | null>(null);
  // fix 2026-10-05: /jobs?view=<id> opens a job's details (incl. its talent pool) -- the "Position open again" to-do links here
  const [viewParams, setViewParams] = useSearchParams();
  useEffect(() => {
    const id = viewParams.get("view");
    const job = id ? jobs.find((j) => j.id === id) : undefined;
    if (job) { setViewingJob(job); setViewParams((p) => { p.delete("view"); return p; }, { replace: true }); }
  }, [jobs, viewParams, setViewParams]);
  const [reopeningJob, setReopeningJob] = useState<JobRoleRead | null>(null);

  // Same colour-by-rank the "Jobs by department" donut uses, so a department's icon colour
  // always matches its slice even when the table is filtered.
  const departmentColorMap = useMemo(() => {
    const map: Record<string, string> = {};
    toBreakdownSlices(departmentBreakdown).forEach((slice) => {
      map[slice.label] = slice.color;
    });
    return map;
  }, [departmentBreakdown]);

  const filtersKey = JSON.stringify(filters);
  const filteredJobs = useMemo(() => applyJobFilters(jobs, filters), [jobs, filtersKey]); // eslint-disable-line react-hooks/exhaustive-deps
  // Tab counts are against the full list -- a stable overall breakdown.
  const statusTabCounts = useMemo(
    () => ({
      all: jobs.length,
      active: jobs.filter((job) => matchesStatusTab(job, "active")).length,
      draft: jobs.filter((job) => matchesStatusTab(job, "draft")).length,
      on_hold: jobs.filter((job) => matchesStatusTab(job, "on_hold")).length,
      closed: jobs.filter((job) => matchesStatusTab(job, "closed")).length,
    }),
    [jobs],
  );
  // Tab + filters + title search all narrow together.
  const visibleJobs = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return filteredJobs.filter((job) => matchesStatusTab(job, statusTab)).filter((job) => !query || job.title.toLowerCase().includes(query));
  }, [filteredJobs, statusTab, searchQuery]);

  const pageCount = Math.max(1, Math.ceil(visibleJobs.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pagedJobs = visibleJobs.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const pageStart = visibleJobs.length === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const pageEnd = Math.min(currentPage * pageSize, visibleJobs.length);

  useEffect(() => {
    setPage(1);
  }, [filteredJobs, statusTab, searchQuery]);

  const allOnPageSelected = pagedJobs.length > 0 && pagedJobs.every((job) => selectedIds.has(job.id));
  const someOnPageSelected = pagedJobs.some((job) => selectedIds.has(job.id));
  const selectedJobs = jobs.filter((j) => selectedIds.has(j.id));

  const toggleSelectAllOnPage = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) pagedJobs.forEach((job) => next.delete(job.id));
      else pagedJobs.forEach((job) => next.add(job.id));
      return next;
    });
  };

  const toggleSelectOne = (jobId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  };

  // Pipeline summary first: it also applies J5 auto-close, so the list read after it
  // already shows those jobs as closed. A failed summary never blocks the list.
  const loadJobs = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const summary = await jobsExtraApi.pipelineSummary().catch(() => null);
      if (summary) {
        setPipeline(Object.fromEntries(summary.items.map((row) => [row.job_id, row])));
        if (summary.just_closed.length > 0) setJustClosed(summary.just_closed.length);
      }
      setJobs(await jobsApi.list());
    } catch (err) {
      setLoadError(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadJobs();
  }, []);

  const refreshAll = () => {
    loadJobs();
    setDashboardRefreshSignal((s) => s + 1);
  };

  // Resets every filter/search/pagination control back to its default, then re-fetches
  // both the table and the dashboard panels.
  const handleRefresh = () => {
    setView((v) => ({ ...v, filters: { ...EMPTY_VIEW_FILTERS } }));
    setPage(1);
    setPageSize(DEFAULT_PAGE_SIZE);
    refreshAll();
  };

  const handleJobDeleted = (jobId: string) => {
    setJobs((prev) => prev.filter((j) => j.id !== jobId));
    setSelectedIds((prev) => {
      if (!prev.has(jobId)) return prev;
      const next = new Set(prev);
      next.delete(jobId);
      return next;
    });
  };

  const openCreate = () => {
    setEditingJob(null);
    setTemplateJob(null);
    setWizardOpen(true);
  };
  const openFromTemplate = (job: JobRoleRead) => {
    setTemplateOpen(false);
    setEditingJob(null);
    setTemplateJob(job);
    setWizardOpen(true);
  };

  const statusLabel = (status: string) => {
    const key = `status.${status}`;
    const translated = t(key);
    return translated !== key ? translated : statusStyle(status).label;
  };

  const exportDetailedCsv = (rows: JobRoleRead[]) => {
    downloadCsv(
      "jobs.csv",
      [
        "Title", "Department", "Location", "Experience Level",
        "Education Degree Level", "Education Field",
        "Technical Skills (Must Have)", "Technical Skills (Good to Have)",
        "Soft Skills (Must Have)", "Soft Skills (Good to Have)", "Preferred Certifications",
        "Key Responsibilities", "Status", "Positions", "Salary Min", "Salary Max", "Created At",
      ],
      rows.map((job) => [
        job.title,
        job.department,
        job.location,
        formatExperienceRange(job.experience_min_years, job.experience_max_years),
        job.education_degree_level,
        job.education_field,
        (job.technical_skills_must_have || []).join(", "),
        (job.technical_skills_good_to_have || []).join(", "),
        (job.soft_skills_must_have || []).join(", "),
        (job.soft_skills_good_to_have || []).join(", "),
        (job.preferred_certifications || []).join(", "),
        job.key_responsibilities,
        job.status,
        job.positions_count,
        job.salary_band_min,
        job.salary_band_max,
        job.created_at,
      ]),
    );
  };

  // What the toolbar's Export writes: exactly the table's columns, in plain words.
  const exportRows = visibleJobs.map((job) => {
    const p = pipeline[job.id];
    const row: Record<string, unknown> = {
      title: job.title, department: job.department ?? "", location: job.location ?? "", type: job.job_type,
      applications: job.application_count, openings: p ? t("jobs.openings_filled", { filled: p.hired, total: job.positions_count }) : job.positions_count,
      status: statusLabel(job.status), time_to_hire: job.avg_time_to_hire_days ?? "",
    };
    PIPELINE_STAGES.forEach((s) => {
      row[stageKey(s)] = p ? p.stages[s] : "";
    });
    return row;
  });

  const runBulk = async (targets: JobRoleRead[], action: (job: JobRoleRead) => Promise<unknown>) => {
    setBulkBusy(true);
    setActionError(null);
    const results = await Promise.allSettled(targets.map(action));
    const failed = results.find((r) => r.status === "rejected") as PromiseRejectedResult | undefined;
    const ok = results.filter((r) => r.status === "fulfilled").length;
    if (failed) setActionError({ what: t("jobs.error.update"), error: failed.reason });
    if (ok > 0) setNotice(t("jobs.bulk.done", { count: ok }));
    setBulkBusy(false);
    setSelectedIds(new Set());
    refreshAll();
  };
  const selectedPublished = selectedJobs.filter((j) => j.status === "published");
  const selectedOnHold = selectedJobs.filter((j) => j.status === "on_hold");

  const bulkActions = (
    <>
      {canWrite && selectedPublished.length > 0 && (
        <Button size="small" variant="outlined" disabled={bulkBusy} startIcon={<Emoji name="pause" size={16} />} onClick={() => runBulk(selectedPublished, (j) => jobsApi.hold(j.id))}>
          {t("jobs.bulk.hold", { count: selectedPublished.length })}
        </Button>
      )}
      {canWrite && selectedOnHold.length > 0 && (
        <Button size="small" variant="outlined" disabled={bulkBusy} startIcon={<Emoji name="rocket" size={16} />} onClick={() => runBulk(selectedOnHold, (j) => jobsApi.resume(j.id))}>
          {t("jobs.bulk.resume", { count: selectedOnHold.length })}
        </Button>
      )}
      <Button size="small" variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={() => exportDetailedCsv(selectedJobs)}>
        {t("jobs.bulk.export")}
      </Button>
      <Button size="small" onClick={() => setSelectedIds(new Set())}>{t("jobs.bulk.clear")}</Button>
    </>
  );

  const shown = columns.filter((c) => view.columns.includes(c.key));
  const isStage = (key: string) => key.startsWith("stage_");
  const headerCell = (c: ListColumn) => {
    if (isStage(c.key)) {
      const stage = c.key.slice(6) as JobStage;
      return (
        <TableCell key={c.key} align="center" sx={{ whiteSpace: "nowrap" }}>
          <Stack alignItems="center" spacing={0.25}>
            <Emoji name={STAGE_STYLE[stage].emoji} size={16} />
            <span>{c.label}</span>
          </Stack>
        </TableCell>
      );
    }
    if (c.key === "openings") {
      return (
        <TableCell key={c.key} sx={{ whiteSpace: "nowrap" }}>
          {c.label}
          <InfoTip text={t("jobs.autoclose.tip")} />
        </TableCell>
      );
    }
    return <TableCell key={c.key} sx={{ whiteSpace: "nowrap" }}>{c.label}</TableCell>;
  };

  const renderCell = (c: ListColumn, job: JobRoleRead) => {
    const p = pipeline[job.id];
    if (isStage(c.key)) {
      const stage = c.key.slice(6) as JobStage;
      return <TableCell key={c.key} align="center"><StageCell stage={stage} count={p?.stages[stage]} /></TableCell>;
    }
    switch (c.key) {
      case "title": {
        const DepartmentIcon = getDepartmentIcon(job.department);
        const departmentColor = job.department ? departmentColorMap[job.department] ?? OTHER_COLOR : OTHER_COLOR;
        return (
          <TableCell key={c.key} sx={{ minWidth: 200 }}>
            <Stack direction="row" spacing={1.25} alignItems="center">
              <Box sx={{ width: 32, height: 32, borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}`, display: "grid", placeItems: "center", flexShrink: 0 }}>
                <DepartmentIcon sx={{ fontSize: 18, color: departmentColor }} />
              </Box>
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="body2" component="button" onClick={() => setViewingJob(job)}
                  sx={{ fontWeight: 700, border: 0, p: 0, background: "none", color: "inherit", cursor: "pointer", textAlign: "left", font: "inherit", "&:hover": { color: f.brand } }}>
                  {job.title}
                </Typography>
                <Typography variant="caption" sx={{ color: f.muted, display: "block" }}>
                  {[job.department, job.location].filter(Boolean).join(" · ") || "—"}
                </Typography>
              </Box>
            </Stack>
          </TableCell>
        );
      }
      case "department":
        return <TableCell key={c.key}>{job.department || "—"}</TableCell>;
      case "location":
        return <TableCell key={c.key}>{job.location || "—"}</TableCell>;
      case "type":
        return <TableCell key={c.key}><JobTypeChip jobType={job.job_type} /></TableCell>;
      case "applications":
        return <TableCell key={c.key}><ApplicationsTrendCell job={job} /></TableCell>;
      case "openings":
        return (
          <TableCell key={c.key} sx={{ whiteSpace: "nowrap" }}>
            {p ? t("jobs.openings_filled", { filled: p.hired, total: job.positions_count }) : job.positions_count}
          </TableCell>
        );
      case "status":
        return (
          <TableCell key={c.key}>
            <Stack spacing={0.5} alignItems="flex-start">
              <StatusChip status={job.status} />
              <AutoCloseNote row={p} />
            </Stack>
          </TableCell>
        );
      case "health":
        return <TableCell key={c.key}>{job.status === "published" ? <JobHealthChip row={healthById.get(job.id)} /> : "—"}</TableCell>;
      case "time_to_hire":
        return <TableCell key={c.key}>{job.avg_time_to_hire_days != null ? t("jobs.days", { count: job.avg_time_to_hire_days }) : "—"}</TableCell>;
      default:
        return <TableCell key={c.key} />;
    }
  };

  const hasFilters = statusTab !== "all" || Boolean(searchQuery) || Object.values(filters).some(Boolean);

  return (
    <Box>
      <PageHeader
        emoji="briefcase"
        title={t("jobs.title")}
        purpose={t("jobs.purpose")}
        tourKey="jobs"
        primary={canWrite ? <Button variant="contained" onClick={openCreate}>{t("jobs.create")}</Button> : undefined}
        extra={canWrite && jobs.length > 0 ? (
          <Button variant="outlined" startIcon={<Emoji name="clipboard" size={18} />} onClick={() => setTemplateOpen(true)}>{t("jobs.from_template")}</Button>
        ) : undefined}
      />

      <JobsDashboardStats
        refreshSignal={dashboardRefreshSignal}
        onTopJobsChange={setTopJobs}
        onDepartmentBreakdownChange={setDepartmentBreakdown}
        onStatsChange={setStats}
        showBreakdowns={false}
      />

      {justClosed > 0 && (
        <Card role="status" sx={{ p: 2, mb: 2, bgcolor: f.sunSoft, boxShadow: "none" }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
            <Emoji name="bell" size={22} />
            <Box sx={{ flex: 1 }}>
              <Typography sx={{ fontWeight: 700 }}>{t("jobs.autoclose.banner", { count: justClosed })}</Typography>
              <Typography variant="body2" sx={{ color: f.muted }}>{t("jobs.autoclose.banner_fix")}</Typography>
            </Box>
            <Button size="small" variant="contained" onClick={() => { patchFilters({ tab: "closed" }); setJustClosed(0); }}>{t("jobs.autoclose.show_closed")}</Button>
            <Button size="small" onClick={() => setJustClosed(0)}>{t("action.close")}</Button>
          </Stack>
        </Card>
      )}

      {/* Part 17.13: live jobs that need a nudge (hidden when all are fine) */}
      <JobsHealthCard
        data={health}
        onOpenJob={(jobId) => {
          const job = jobs.find((j) => j.id === jobId);
          if (job) setViewingJob(job);
        }}
      />

      {closingJob && (
        <CloseJobDialog open jobId={closingJob.id} title={closingJob.title} onClose={() => setClosingJob(null)}
          onClosed={(r) => {
            setNotice(t("closejob.done", { title: closingJob.title, count: r.on_hold }));
            setClosingJob(null);
            refreshAll();
          }} />
      )}
      {notice && (
        <Card role="status" sx={{ p: 1.5, mb: 2, bgcolor: f.okSoft, boxShadow: "none" }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <Emoji name="check" size={18} />
            <Typography sx={{ flex: 1, fontWeight: 600 }}>{notice}</Typography>
            <Button size="small" onClick={() => setNotice(null)}>{t("action.close")}</Button>
          </Stack>
        </Card>
      )}

      {actionError && (
        <Box sx={{ mb: 2 }}>
          <FriendlyError compact error={actionError.error} what={actionError.what} onRetry={() => { setActionError(null); refreshAll(); }} />
        </Box>
      )}

      <Card sx={{ mb: 3 }}>
        <CardContent sx={{ p: { xs: 1.5, sm: 2.5 } }}>
          <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ md: "center" }} gap={1.5} mb={1.5}>
            <Tabs value={statusTab} onChange={(_event, value: StatusTab) => patchFilters({ tab: value })} variant="scrollable" allowScrollButtonsMobile aria-label={t("jobs.tabs_label")}>
              <Tab value="all" label={t("jobs.tab.all", { count: statusTabCounts.all })} />
              <Tab value="active" label={t("jobs.tab.active", { count: statusTabCounts.active })} />
              <Tab value="draft" label={t("jobs.tab.draft", { count: statusTabCounts.draft })} />
              <Tab value="on_hold" label={t("jobs.tab.on_hold", { count: statusTabCounts.on_hold })} />
              <Tab value="closed" label={t("jobs.tab.closed", { count: statusTabCounts.closed })} />
            </Tabs>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <TextField
                size="small"
                placeholder={t("jobs.search")}
                value={searchQuery}
                onChange={(e) => patchFilters({ search: e.target.value })}
                slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }, htmlInput: { "aria-label": t("jobs.search") } }}
                sx={{ minWidth: 220 }}
              />
              <JobFiltersPanel jobs={jobs} filters={filters} onChange={setFilters} />
              <Button size="small" variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={() => exportDetailedCsv(visibleJobs)} disabled={visibleJobs.length === 0}>
                {t("jobs.download_details")}
              </Button>
            </Stack>
          </Stack>

          <ListToolbar
            listKey={LIST_KEY}
            columns={columns}
            state={view}
            onStateChange={setView}
            rows={exportRows}
            loading={loading}
            onRefresh={handleRefresh}
            selectedCount={selectedIds.size}
            bulkActions={bulkActions}
          />

          {loadError != null ? (
            <FriendlyError error={loadError} what={t("jobs.error.load")} onRetry={loadJobs} />
          ) : loading && jobs.length === 0 ? (
            <Stack spacing={1}>
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} variant="rounded" height={44} />
              ))}
            </Stack>
          ) : visibleJobs.length === 0 ? (
            jobs.length === 0 ? (
              <EmptyState illustration="hiring" title={t("jobs.empty.none")}
                action={canWrite ? <Button variant="contained" onClick={openCreate}>{t("jobs.empty.none_action")}</Button> : undefined} />
            ) : (
              <EmptyState compact illustration="search" title={t("jobs.empty.filtered")}
                action={hasFilters ? <Button variant="outlined" onClick={() => patchFilters({ ...EMPTY_VIEW_FILTERS })}>{t("jobs.empty.clear")}</Button> : undefined} />
            )
          ) : (
            <>
              <TableContainer sx={{ border: `1px solid ${f.line}`, borderRadius: "12px" }}>
                <Table size="small" aria-label={t("jobs.table_label")}>
                  <TableHead>
                    <TableRow>
                      <TableCell padding="checkbox">
                        <Checkbox
                          indeterminate={someOnPageSelected && !allOnPageSelected}
                          checked={allOnPageSelected}
                          onChange={toggleSelectAllOnPage}
                          slotProps={{ input: { "aria-label": t("jobs.select_page") } }}
                        />
                      </TableCell>
                      {shown.map(headerCell)}
                      <TableCell align="right">{t("jobs.col.actions")}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {pagedJobs.map((job) => (
                      <TableRow key={job.id} hover selected={selectedIds.has(job.id)}>
                        <TableCell padding="checkbox">
                          <Checkbox checked={selectedIds.has(job.id)} onChange={() => toggleSelectOne(job.id)} slotProps={{ input: { "aria-label": t("jobs.select_one", { title: job.title }) } }} />
                        </TableCell>
                        {shown.map((c) => renderCell(c, job))}
                        <TableCell align="right">
                          <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                            <Tooltip title={t("jobs.action.view")}>
                              <IconButton size="small" onClick={() => setViewingJob(job)} aria-label={t("jobs.action.view")}>
                                <VisibilityOutlinedIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            {canWrite && (
                              <Tooltip title={t("jobs.action.edit")}>
                                <IconButton size="small" aria-label={t("jobs.action.edit")} onClick={() => { setTemplateJob(null); setEditingJob(job); setWizardOpen(true); }}>
                                  <EditOutlinedIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            )}
                            {canWrite && (
                              <JobActionsMenu
                                job={job}
                                onChanged={(updated) => {
                                  setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
                                  setDashboardRefreshSignal((s) => s + 1);
                                }}
                                onDeleted={handleJobDeleted}
                                onError={(what, error) => setActionError({ what, error })}
                                onReopen={setReopeningJob}
                                onUseTemplate={openFromTemplate}
                                onCloseJob={setClosingJob}
                              />
                            )}
                          </Stack>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>

              <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
                <Typography variant="body2" sx={{ color: f.muted }}>
                  {t("jobs.showing", { from: pageStart, to: pageEnd, count: visibleJobs.length })}
                </Typography>
                <Stack direction="row" spacing={2} alignItems="center">
                  <TextField select size="small" label={t("jobs.rows_per_page")} value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }} sx={{ minWidth: 130 }}>
                    {ROWS_PER_PAGE_OPTIONS.map((size) => (
                      <MenuItem key={size} value={size}>
                        {size}
                      </MenuItem>
                    ))}
                  </TextField>
                  <Pagination count={pageCount} page={currentPage} onChange={(_event, value) => setPage(value)} size="small" color="primary" />
                </Stack>
              </Stack>
            </>
          )}
        </CardContent>
      </Card>

      <Typography variant="h5" component="h2" sx={{ mb: 1.5, display: "flex", alignItems: "center", gap: 1 }}>
        <Emoji name="chart_up" size={22} />
        {t("jobs.insights")}
      </Typography>
      <Grid container spacing={3}>
        {stats && (
          <>
            <Grid size={{ xs: 12, md: 6, lg: 4 }}>
              <Card sx={{ height: "100%" }}><CardContent><DepartmentBreakdownPanel rows={stats.by_department} /></CardContent></Card>
            </Grid>
            <Grid size={{ xs: 12, md: 6, lg: 4 }}>
              <Card sx={{ height: "100%" }}><CardContent><LocationBreakdownPanel rows={stats.by_location} /></CardContent></Card>
            </Grid>
          </>
        )}
        <Grid size={{ xs: 12, md: 6, lg: 4 }}>
          <Card sx={{ height: "100%" }}><CardContent><JobStatusOverviewPanel /></CardContent></Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <PanelCard emoji="trophy" title={t("jobs.panel.top")}>
            <TopPerformingJobs jobs={topJobs} />
          </PanelCard>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <PanelCard emoji="bell" title={t("jobs.panel.recent")}>
            <RecentActivityFeed limit={5} refreshSignal={dashboardRefreshSignal} dense />
          </PanelCard>
        </Grid>
      </Grid>

      <CreateJobWizard
        open={wizardOpen}
        onClose={() => {
          setWizardOpen(false);
          setEditingJob(null);
          setTemplateJob(null);
          refreshAll();
        }}
        onPublished={refreshAll}
        initialJob={editingJob}
        template={templateJob}
        templates={jobs}
      />
      <JobTemplateLibrary open={templateOpen} jobs={jobs} onClose={() => setTemplateOpen(false)} onPick={openFromTemplate} />
      <JobDetailsDialog
        job={viewingJob}
        canWrite={canWrite}
        pipeline={viewingJob ? pipeline[viewingJob.id] : undefined}
        onClose={() => setViewingJob(null)}
        onCloseJob={(job) => { setViewingJob(null); setClosingJob(job); }}
        onUpdated={(updated) => {
          setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
          setViewingJob(updated);
        }}
      />
      <ReopenJobDialog
        job={reopeningJob}
        pipeline={reopeningJob ? pipeline[reopeningJob.id] : undefined}
        onClose={() => setReopeningJob(null)}
        onReopened={(job) => {
          setReopeningJob(null);
          setNotice(t("jobs.reopen.done", { title: job.title }));
          refreshAll();
        }}
      />
    </Box>
  );
}
