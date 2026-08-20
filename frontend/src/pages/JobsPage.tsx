import { useEffect, useMemo, useState, type ReactNode } from "react";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import SearchIcon from "@mui/icons-material/Search";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import Skeleton from "@mui/material/Skeleton";
import FormControl from "@mui/material/FormControl";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import InputLabel from "@mui/material/InputLabel";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Pagination from "@mui/material/Pagination";
import Paper from "@mui/material/Paper";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
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

import { extractErrorMessage, jobsApi } from "../api/client";
import type { JobRoleRead, LabeledCount, TopJobItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { OTHER_COLOR, toBreakdownSlices } from "../components/BreakdownLegend";
import ConfirmDialog from "../components/ConfirmDialog";
import CreateJobWizard from "../components/CreateJobWizard";
import JobDetailsDialog from "../components/JobDetailsDialog";
import JobFiltersPanel, { applyJobFilters, EMPTY_JOB_FILTERS } from "../components/JobFiltersPanel";
import type { JobFilters } from "../components/JobFiltersPanel";
import JobsDashboardStats from "../components/JobsDashboardStats";
import JobTypeChip from "../components/JobTypeChip";
import QuickActionsPanel from "../components/QuickActionsPanel";
import RecentActivityFeed from "../components/RecentActivityFeed";
import StatusChip from "../components/StatusChip";
import TopPerformingJobs from "../components/TopPerformingJobs";
import { downloadCsv } from "../utils/csv";
import { getDepartmentIcon } from "../utils/departmentIcons";
import { formatExperienceRange } from "../utils/experience";
import { ROLE_MATRIX } from "../auth/roles";

const ROWS_PER_PAGE_OPTIONS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
const DEFAULT_PAGE_SIZE = 10;

// Condensed card shell for the sidebar -- smaller padding than the main content's cards
// (which use CardContent's default) so three stacked panels read as a compact rail, not
// three full-size cards squeezed into a narrow column.
function SidebarCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card variant="outlined">
      <CardContent sx={{ p: 1.5, "&:last-child": { pb: 1.5 } }}>
        <Typography variant="subtitle2" fontWeight="bold" mb={1}>
          {title}
        </Typography>
        {children}
      </CardContent>
    </Card>
  );
}

// A job can only ever be deleted while it's draft/ready_for_publishing (never
// published/on_hold/closed -- see backend/app/jobs/router.py delete_job), so this is the
// one action available on those statuses; published/on_hold keep their existing
// hold/resume actions. Anything outside those cases has no action at all, so the menu
// button doesn't render rather than opening to an empty menu.
function JobActionsMenu({
  job,
  onChanged,
  onDeleted,
  onError,
}: {
  job: JobRoleRead;
  onChanged: (updated: JobRoleRead) => void;
  onDeleted: (jobId: string) => void;
  onError: (message: string) => void;
}) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const [pending, setPending] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const canDelete = job.status === "draft" || job.status === "ready_for_publishing";
  if (job.status !== "published" && job.status !== "on_hold" && !canDelete) {
    return null;
  }

  const runAction = async (action: () => Promise<JobRoleRead>) => {
    setAnchorEl(null);
    setPending(true);
    try {
      onChanged(await action());
    } catch (err) {
      onError(extractErrorMessage(err, "Failed to update job status"));
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
      onError(extractErrorMessage(err, "Failed to delete job"));
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <IconButton size="small" onClick={(event) => setAnchorEl(event.currentTarget)} disabled={pending}>
        <MoreVertIcon fontSize="small" />
      </IconButton>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        {job.status === "published" && (
          <MenuItem onClick={() => runAction(() => jobsApi.hold(job.id))}>Put on hold</MenuItem>
        )}
        {job.status === "on_hold" && (
          <MenuItem onClick={() => runAction(() => jobsApi.resume(job.id))}>Resume</MenuItem>
        )}
        {canDelete && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              setConfirmDeleteOpen(true);
            }}
            sx={{ color: "error.main" }}
          >
            <DeleteOutlineIcon fontSize="small" sx={{ mr: 1 }} />
            Delete
          </MenuItem>
        )}
      </Menu>
      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete this job?"
        message={`This will permanently delete "${job.title}". This can't be undone.`}
        confirmLabel="Delete"
        confirming={pending}
        destructive
        onConfirm={runDelete}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </>
  );
}

// Same math as the dashboard stat cards' trend arrows (StatCard.tsx's TrendIndicator),
// scoped to one job's application_count/applications_pct_change instead of the
// dashboard-wide total. In particular the same zero-baseline-growth rule applies:
// app/reports/stats.py::pct_change returns None only when last month-end's count was 0
// and this job now has some applications (job_application_count_and_trend never passes
// pct_change a None input here, since application_count is always a concrete int) --
// so a null pct here always means "grew from nothing," shown the same "+100%" way
// StatCard shows it, not as a flat/neutral dash.
function ApplicationsTrendCell({ job }: { job: JobRoleRead }) {
  const pct = job.applications_pct_change;
  const isZeroBaselineGrowth = pct == null && job.application_count > 0;
  const displayPct = isZeroBaselineGrowth ? 100 : pct;

  if (displayPct == null) {
    return (
      <Stack direction="row" spacing={0.5} alignItems="center">
        <Typography variant="body2">{job.application_count}</Typography>
        <Typography variant="caption" color="text.secondary">
          (—)
        </Typography>
      </Stack>
    );
  }
  const direction = displayPct > 0 ? "up" : displayPct < 0 ? "down" : "flat";
  const tone = direction === "flat" ? "text.secondary" : direction === "up" ? "success.main" : "error.main";
  const ArrowIcon = direction === "down" ? ArrowDownwardIcon : ArrowUpwardIcon;
  return (
    <Stack direction="row" spacing={0.5} alignItems="center">
      <Typography variant="body2">{job.application_count}</Typography>
      {direction !== "flat" && <ArrowIcon sx={{ fontSize: 14, color: tone }} />}
      <Typography variant="caption" sx={{ color: tone }}>
        {isZeroBaselineGrowth ? "+100%" : `${Math.abs(displayPct)}%`}
      </Typography>
    </Stack>
  );
}

type StatusTab = "all" | "active" | "draft" | "on_hold" | "closed";

// "Draft" folds in "ready_for_publishing" -- both are pre-live states, and the requested
// tab set (All Jobs/Active/Draft/On Hold/Closed) has no separate tab for it.
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

export default function JobsPage() {
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.jobsWrite);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [wizardOpen, setWizardOpen] = useState(false);
  const [dashboardRefreshSignal, setDashboardRefreshSignal] = useState(0);
  const [filters, setFilters] = useState<JobFilters>(EMPTY_JOB_FILTERS);
  const [topJobs, setTopJobs] = useState<TopJobItem[]>([]);
  const [departmentBreakdown, setDepartmentBreakdown] = useState<LabeledCount[]>([]);

  const [statusTab, setStatusTab] = useState<StatusTab>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [editingJob, setEditingJob] = useState<JobRoleRead | null>(null);
  const [viewingJob, setViewingJob] = useState<JobRoleRead | null>(null);

  // Same color-by-rank function and dataset the Jobs by Department donut chart uses
  // (see JobsDashboardStats' onDepartmentBreakdownChange) -- not a client-side recount
  // from `jobs`, so a department's icon color always matches its donut slice color even
  // though the table itself may be filtered/paginated to a different subset.
  const departmentColorMap = useMemo(() => {
    const map: Record<string, string> = {};
    toBreakdownSlices(departmentBreakdown).forEach((slice) => {
      map[slice.label] = slice.color;
    });
    return map;
  }, [departmentBreakdown]);

  const filteredJobs = useMemo(() => applyJobFilters(jobs, filters), [jobs, filters]);
  // Tab counts are deliberately against the full, unfiltered `jobs` list -- a stable
  // overall breakdown, not one that shifts as JobFiltersPanel's separate filters change.
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
  // What's actually shown/exported/counted combines all three: the tab is a quick
  // top-level category, JobFiltersPanel is the detailed filter, search narrows by title --
  // they all narrow together, not either/or.
  const visibleJobs = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return filteredJobs
      .filter((job) => matchesStatusTab(job, statusTab))
      .filter((job) => !query || job.title.toLowerCase().includes(query));
  }, [filteredJobs, statusTab, searchQuery]);

  const pageCount = Math.max(1, Math.ceil(visibleJobs.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pagedJobs = visibleJobs.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const pageStart = visibleJobs.length === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const pageEnd = Math.min(currentPage * pageSize, visibleJobs.length);

  // Resets to page 1 whenever the visible set's composition changes -- otherwise a filter
  // narrowing the list could leave the user stranded on a now-nonexistent page 4 of 2.
  useEffect(() => {
    setPage(1);
  }, [filteredJobs, statusTab, searchQuery]);

  const handlePageSizeChange = (event: SelectChangeEvent<number>) => {
    setPageSize(Number(event.target.value));
    setPage(1);
  };

  const allOnPageSelected = pagedJobs.length > 0 && pagedJobs.every((job) => selectedIds.has(job.id));
  const someOnPageSelected = pagedJobs.some((job) => selectedIds.has(job.id));

  const toggleSelectAllOnPage = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        pagedJobs.forEach((job) => next.delete(job.id));
      } else {
        pagedJobs.forEach((job) => next.add(job.id));
      }
      return next;
    });
  };

  const toggleSelectOne = (jobId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) {
        next.delete(jobId);
      } else {
        next.add(jobId);
      }
      return next;
    });
  };

  const loadJobs = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await jobsApi.list();
      setJobs(data);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load jobs"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadJobs();
  }, []);

  const handleJobPublished = () => {
    loadJobs();
    setDashboardRefreshSignal((s) => s + 1);
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

  const handleExportCsv = () => {
    downloadCsv(
      "jobs.csv",
      [
        "Title", "Department", "Location", "Experience Level",
        "Education Degree Level", "Education Field",
        "Technical Skills (Must Have)", "Technical Skills (Good to Have)",
        "Soft Skills (Must Have)", "Soft Skills (Good to Have)", "Preferred Certifications",
        "Key Responsibilities", "Status", "Positions", "Salary Min", "Salary Max", "Created At",
      ],
      visibleJobs.map((job) => [
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

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3} flexWrap="wrap" gap={2}>
        <Typography variant="h4">Jobs</Typography>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
          <JobFiltersPanel jobs={jobs} filters={filters} onChange={setFilters} />
          <Button variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={handleExportCsv} disabled={visibleJobs.length === 0}>
            Export CSV
          </Button>
          {canWrite && (
            <Button
              variant="contained"
              onClick={() => {
                setEditingJob(null);
                setWizardOpen(true);
              }}
            >
              Create Job
            </Button>
          )}
        </Stack>
      </Stack>

      {/* Flex, not a 12-column Grid fraction, for the main/sidebar split: a fixed
          right-panel width frees the exact amount of space possible for the main
          content (which needs it for the chart panels' legends), rather than being
          capped at a coarse twelfth-of-the-row regardless of what the sidebar actually
          needs. */}
      <Stack direction={{ xs: "column", md: "row" }} spacing={3} alignItems="flex-start">
        <Box sx={{ flex: "1 1 auto", minWidth: 0, width: "100%" }}>
          <JobsDashboardStats
            refreshSignal={dashboardRefreshSignal}
            onTopJobsChange={setTopJobs}
            onDepartmentBreakdownChange={setDepartmentBreakdown}
          />

          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          <Stack
            direction="row"
            justifyContent="space-between"
            alignItems="center"
            flexWrap="wrap"
            gap={1}
            mb={2}
            sx={{ borderBottom: 1, borderColor: "divider" }}
          >
            <Tabs value={statusTab} onChange={(_event, value: StatusTab) => setStatusTab(value)}>
              <Tab value="all" label={`All Jobs (${statusTabCounts.all})`} />
              <Tab value="active" label={`Active (${statusTabCounts.active})`} />
              <Tab value="draft" label={`Draft (${statusTabCounts.draft})`} />
              <Tab value="on_hold" label={`On Hold (${statusTabCounts.on_hold})`} />
              <Tab value="closed" label={`Closed (${statusTabCounts.closed})`} />
            </Tabs>
            <TextField
              size="small"
              placeholder="Search by job title"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
              sx={{ minWidth: 220, mb: 1 }}
            />
          </Stack>

          {loading ? (
            <TableContainer component={Paper} variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell padding="checkbox" />
                    <TableCell>Job Title</TableCell>
                    <TableCell>Department</TableCell>
                    <TableCell>Location</TableCell>
                    <TableCell>Job Type</TableCell>
                    <TableCell>Applications</TableCell>
                    <TableCell>Openings</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Time to Hire</TableCell>
                    <TableCell align="right">Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={i}>
                      <TableCell padding="checkbox">
                        <Skeleton variant="rounded" width={18} height={18} />
                      </TableCell>
                      <TableCell>
                        <Skeleton variant="text" width="70%" />
                      </TableCell>
                      <TableCell>
                        <Skeleton variant="text" width="60%" />
                      </TableCell>
                      <TableCell>
                        <Skeleton variant="text" width="60%" />
                      </TableCell>
                      <TableCell>
                        <Skeleton variant="text" width="50%" />
                      </TableCell>
                      <TableCell>
                        <Skeleton variant="text" width={50} />
                      </TableCell>
                      <TableCell>
                        <Skeleton variant="text" width={30} />
                      </TableCell>
                      <TableCell>
                        <Skeleton variant="rounded" width={70} height={22} />
                      </TableCell>
                      <TableCell>
                        <Skeleton variant="text" width={40} />
                      </TableCell>
                      <TableCell align="right">
                        <Skeleton variant="text" width={60} sx={{ ml: "auto" }} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          ) : visibleJobs.length === 0 ? (
            <Typography color="text.secondary">
              {jobs.length === 0 ? "No jobs yet. Create one to get started." : "No jobs match the current filters."}
            </Typography>
          ) : (
            <>
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell padding="checkbox">
                        <Checkbox
                          indeterminate={someOnPageSelected && !allOnPageSelected}
                          checked={allOnPageSelected}
                          onChange={toggleSelectAllOnPage}
                        />
                      </TableCell>
                      <TableCell>Job Title</TableCell>
                      <TableCell>Department</TableCell>
                      <TableCell>Location</TableCell>
                      <TableCell>Job Type</TableCell>
                      <TableCell>Applications</TableCell>
                      <TableCell>Openings</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Time to Hire</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {pagedJobs.map((job) => {
                      const DepartmentIcon = getDepartmentIcon(job.department);
                      const departmentColor = job.department ? departmentColorMap[job.department] ?? OTHER_COLOR : OTHER_COLOR;
                      return (
                      <TableRow key={job.id} hover selected={selectedIds.has(job.id)}>
                        <TableCell padding="checkbox">
                          <Checkbox checked={selectedIds.has(job.id)} onChange={() => toggleSelectOne(job.id)} />
                        </TableCell>
                        <TableCell>
                          <Stack direction="row" spacing={1} alignItems="center">
                            <DepartmentIcon sx={{ fontSize: 18, color: departmentColor, flexShrink: 0 }} />
                            <Typography variant="body2">{job.title}</Typography>
                          </Stack>
                        </TableCell>
                        <TableCell>{job.department || "—"}</TableCell>
                        <TableCell>{job.location || "—"}</TableCell>
                        <TableCell>
                          <JobTypeChip jobType={job.job_type} />
                        </TableCell>
                        <TableCell>
                          <ApplicationsTrendCell job={job} />
                        </TableCell>
                        <TableCell>{job.positions_count}</TableCell>
                        <TableCell>
                          <StatusChip status={job.status} />
                        </TableCell>
                        <TableCell>
                          {job.avg_time_to_hire_days != null ? `${job.avg_time_to_hire_days}d` : "—"}
                        </TableCell>
                        <TableCell align="right">
                          <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                            <Tooltip title="View">
                              <IconButton size="small" onClick={() => setViewingJob(job)}>
                                <VisibilityOutlinedIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            {canWrite && (
                              <Tooltip title="Edit">
                                <IconButton
                                  size="small"
                                  onClick={() => {
                                    setEditingJob(job);
                                    setWizardOpen(true);
                                  }}
                                >
                                  <EditOutlinedIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            )}
                            {canWrite && (
                              <JobActionsMenu
                                job={job}
                                onChanged={(updated) =>
                                  setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)))
                                }
                                onDeleted={handleJobDeleted}
                                onError={setError}
                              />
                            )}
                          </Stack>
                        </TableCell>
                      </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>

              <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
                <Typography variant="body2" color="text.secondary">
                  {selectedIds.size > 0
                    ? `${selectedIds.size} selected · `
                    : ""}
                  Showing {pageStart} to {pageEnd} of {visibleJobs.length} jobs
                </Typography>
                <Stack direction="row" spacing={2} alignItems="center">
                  <FormControl size="small" sx={{ minWidth: 130 }}>
                    <InputLabel id="jobs-rows-per-page-label">Rows per page</InputLabel>
                    <Select
                      labelId="jobs-rows-per-page-label"
                      label="Rows per page"
                      value={pageSize}
                      onChange={handlePageSizeChange}
                    >
                      {ROWS_PER_PAGE_OPTIONS.map((size) => (
                        <MenuItem key={size} value={size}>
                          {size}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <Pagination
                    count={pageCount}
                    page={currentPage}
                    onChange={(_event, value) => setPage(value)}
                    size="small"
                    color="primary"
                  />
                </Stack>
              </Stack>
            </>
          )}
        </Box>

        {/* Sidebar: Quick Actions, Recent Activity, Top Performing Jobs -- stacked, in
            that order, condensed. Collapses below the main content on narrow screens
            rather than squeezing into a sliver next to it. */}
        <Box sx={{ width: { xs: "100%", md: 180 }, flexShrink: 0 }}>
          <Stack spacing={2}>
            <SidebarCard title="Quick Actions">
              <QuickActionsPanel
                onCreateJob={() => {
                  setEditingJob(null);
                  setWizardOpen(true);
                }}
              />
            </SidebarCard>
            <SidebarCard title="Recent Activity">
              <RecentActivityFeed limit={5} refreshSignal={dashboardRefreshSignal} dense />
            </SidebarCard>
            <SidebarCard title="Top Performing Jobs">
              <TopPerformingJobs jobs={topJobs} />
            </SidebarCard>
          </Stack>
        </Box>
      </Stack>

      <CreateJobWizard
        open={wizardOpen}
        onClose={() => {
          setWizardOpen(false);
          setEditingJob(null);
        }}
        onPublished={handleJobPublished}
        initialJob={editingJob}
      />
      <JobDetailsDialog
        job={viewingJob}
        canWrite={canWrite}
        onClose={() => setViewingJob(null)}
        onUpdated={(updated) => {
          setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
          setViewingJob(updated);
        }}
      />
    </Box>
  );
}
