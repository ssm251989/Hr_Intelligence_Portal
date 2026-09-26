import { useEffect, useMemo, useState } from "react";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import DownloadingOutlinedIcon from "@mui/icons-material/DownloadingOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import PersonAddAltOutlinedIcon from "@mui/icons-material/PersonAddAltOutlined";
import SearchIcon from "@mui/icons-material/Search";
import TableRowsOutlinedIcon from "@mui/icons-material/TableRowsOutlined";
import ViewKanbanOutlinedIcon from "@mui/icons-material/ViewKanbanOutlined";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import FormControl from "@mui/material/FormControl";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Pagination from "@mui/material/Pagination";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Skeleton from "@mui/material/Skeleton";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useNavigate, useSearchParams } from "react-router-dom";

import { applicationsApi, candidatesApi, extractErrorMessage, jobsApi, shortlistingApi } from "../api/client";
import { type CandidateApplicationRow, type JobRoleRead } from "../api/types";
import CandidateActionsMenu from "../components/CandidateActionsMenu";
import CandidateAvatar from "../components/CandidateAvatar";
import CandidateFiltersPanel, { EMPTY_CANDIDATE_FILTERS, type CandidateFilters } from "../components/CandidateFiltersPanel";
import ConfirmDialog from "../components/ConfirmDialog";
import EditCandidateContactDialog from "../components/EditCandidateContactDialog";
import ListToolbar, { type ListColumn, type ListViewState } from "../components/ListToolbar";
import SourceIcon from "../components/SourceIcon";
import UploadCandidateDialog from "../components/UploadCandidateDialog";
import CandidatesKanban from "../components/candidates/CandidatesKanban";
import { columnOf, planMove, useFresh, type BoardColumnKey, type MovePlan } from "../components/candidates/stages";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { useT } from "../i18n";
import { EmptyState, FriendlyError, PageHeader, StatusChip, statusStyle } from "../ui-kit";
import { downloadCsv } from "../utils/csv";
import { downloadResume } from "../utils/resume";
import { resumeMatchScoreDisplay } from "../utils/screeningScore";

// Part 15.4 Candidates list: table AND Kanban board (switch remembered per browser, table by
// default -- N4), 25 rows a page (N5), the standard ListToolbar (refresh, saved views, column
// chooser, bulk actions, export). Same API calls, filters, permissions and row actions as
// before.

const ROWS_PER_PAGE_OPTIONS = [10, 25, 50, 100];
const DEFAULT_PAGE_SIZE = 25;
// The list endpoint caps page_size at 200 -- the board shows up to that many at once.
const BOARD_PAGE_SIZE = 200;
const SEARCH_DEBOUNCE_MS = 300;
const VIEW_KEY = "hrms.candidates.view";
const LIST_KEY = "candidates";

type ViewMode = "table" | "board";

function readViewMode(): ViewMode {
  try {
    return localStorage.getItem(VIEW_KEY) === "board" ? "board" : "table";
  } catch {
    return "table";
  }
}

const HIDEABLE_COLUMNS = ["source", "job", "applied", "experience", "location", "match", "resume", "status", "remarks"] as const;

interface PendingMove {
  row: CandidateApplicationRow;
  plan: Exclude<MovePlan, { kind: "blocked" }>;
  to: BoardColumnKey;
}

export default function CandidatesListPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.candidatesWrite);
  const t = useT();
  const f = useFresh();
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [rows, setRows] = useState<CandidateApplicationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadingResumeFor, setDownloadingResumeFor] = useState<string | null>(null);

  const [viewMode, setViewModeState] = useState<ViewMode>(readViewMode);
  // Part 17.2: links from the Home funnel / other pages pre-set filters (?status=a,b&job=&applied_after=).
  const [urlParams] = useSearchParams();
  const [filters, setFilters] = useState<CandidateFilters>(() => ({
    ...EMPTY_CANDIDATE_FILTERS,
    status: urlParams.get("status") ?? EMPTY_CANDIDATE_FILTERS.status,
    jobRoleId: urlParams.get("job") ?? EMPTY_CANDIDATE_FILTERS.jobRoleId,
    appliedAfter: urlParams.get("applied_after") ?? EMPTY_CANDIDATE_FILTERS.appliedAfter,
  }));
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [visibleColumns, setVisibleColumns] = useState<string[]>([...HIDEABLE_COLUMNS]);
  // Forces loadPage to re-run on Refresh even when every filter/search/page value is already
  // at its default.
  const [refreshKey, setRefreshKey] = useState(0);
  const anyFilterActive = Boolean(search) || Object.values(filters).some(Boolean);

  // Manual single-candidate upload + link-to-job (shared dialog with the Dashboard).
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [editingCandidate, setEditingCandidate] = useState<CandidateApplicationRow | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const [pendingMove, setPendingMove] = useState<PendingMove | null>(null);
  const [moving, setMoving] = useState(false);
  const [notice, setNotice] = useState<{ text: string; severity: "success" | "info" | "error" } | null>(null);

  const setViewMode = (mode: ViewMode) => {
    setViewModeState(mode);
    try {
      localStorage.setItem(VIEW_KEY, mode);
    } catch {
      /* per-visit only */
    }
  };

  useEffect(() => {
    jobsApi.list().then(setJobs).catch(() => setJobs([]));
  }, []);

  // Debounced: this is a server round-trip per keystroke otherwise.
  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
  }, [filters, search]);

  const listParams = () => ({
    search: search || undefined,
    jobRoleId: filters.jobRoleId || undefined,
    status: filters.status || undefined,
    source: filters.source || undefined,
    location: filters.location || undefined,
    experienceMin: filters.experienceMin ? Number(filters.experienceMin) : undefined,
    experienceMax: filters.experienceMax ? Number(filters.experienceMax) : undefined,
    appliedAfter: filters.appliedAfter || undefined,
    appliedBefore: filters.appliedBefore || undefined,
    matchScoreMin: filters.matchScoreMin ? Number(filters.matchScoreMin) : undefined,
    matchScoreMax: filters.matchScoreMax ? Number(filters.matchScoreMax) : undefined,
  });

  const loadPage = () => {
    setLoading(true);
    setLoadError(null);
    const params = viewMode === "board" ? { page: 1, pageSize: BOARD_PAGE_SIZE } : { page, pageSize };
    candidatesApi
      .listApplications({ ...params, ...listParams() })
      .then((result) => {
        setRows(result.items);
        setTotal(result.total);
      })
      .catch((err) => setLoadError(err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search, filters, refreshKey, viewMode]);

  const handleRefresh = () => {
    setFilters(EMPTY_CANDIDATE_FILTERS);
    setSearchInput("");
    setSearch("");
    setPage(1);
    setPageSize(DEFAULT_PAGE_SIZE);
    setRefreshKey((k) => k + 1);
  };

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pageStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = Math.min(page * pageSize, total);

  const handlePageSizeChange = (event: SelectChangeEvent<number>) => {
    setPageSize(Number(event.target.value));
    setPage(1);
  };

  // Selected rows export exactly themselves, ignoring every filter -- otherwise (nothing
  // checked) export the full filtered result set, via the dedicated unpaginated export
  // endpoint (never the paginated list endpoint the table itself uses).
  const handleExportCsv = async () => {
    try {
      const result =
        selectedIds.size > 0
          ? await candidatesApi.exportApplications({ applicationIds: Array.from(selectedIds) })
          : await candidatesApi.exportApplications(listParams());
      downloadCsv(
        "candidates.csv",
        [
          "Candidate", "Email", "Job Applied", "Status", "Source", "Applied On", "Experience (yrs)",
          "Screening Score", "Resume Match", "Location", "Remarks",
        ],
        result.map((row) => [
          row.candidate_name,
          row.candidate_email,
          row.job_title,
          row.status,
          row.source,
          row.applied_on,
          row.experience_years,
          // Composite screening score when there is one, else the raw match score -- kept
          // as its own column beside "Resume Match" so the two never collapse into one.
          row.composite_score ?? row.match_score,
          row.match_score,
          row.location,
          row.remarks,
        ]),
      );
    } catch (err) {
      setError(extractErrorMessage(err, t("candidates.list.export_failed")));
    }
  };

  const handleDownloadResume = async (row: CandidateApplicationRow) => {
    setDownloadingResumeFor(row.application_id);
    setError(null);
    try {
      await downloadResume(row.candidate_id, row.resume_path, row.candidate_name);
    } catch (err) {
      setError(extractErrorMessage(err, t("candidates.resume.download_failed")));
    } finally {
      setDownloadingResumeFor(null);
    }
  };

  const jobById = useMemo(() => new Map(jobs.map((job) => [job.id, job])), [jobs]);

  const allOnPageSelected = rows.length > 0 && rows.every((row) => selectedIds.has(row.application_id));
  const someOnPageSelected = rows.some((row) => selectedIds.has(row.application_id));

  const toggleSelectAllOnPage = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) rows.forEach((row) => next.delete(row.application_id));
      else rows.forEach((row) => next.add(row.application_id));
      return next;
    });
  };

  const toggleSelectOne = (applicationId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(applicationId)) next.delete(applicationId);
      else next.add(applicationId);
      return next;
    });
  };

  const handleRowDeleted = (applicationId: string) => {
    setSelectedIds((prev) => {
      if (!prev.has(applicationId)) return prev;
      const next = new Set(prev);
      next.delete(applicationId);
      return next;
    });
    loadPage();
  };

  // ---- Kanban moves: only what an existing endpoint already does ----
  const requestMove = (row: CandidateApplicationRow, to: BoardColumnKey) => {
    const plan = planMove(row.status, to);
    if (!plan) return;
    if (plan.kind === "blocked") {
      setNotice({ text: t(plan.reasonKey), severity: "info" });
      return;
    }
    setPendingMove({ row, plan, to });
  };

  const runMove = async () => {
    if (!pendingMove) return;
    const { row, plan } = pendingMove;
    setMoving(true);
    try {
      let newStatus = row.status;
      if (plan.kind === "hold") newStatus = (await applicationsApi.hold(row.application_id)).status;
      if (plan.kind === "resume") newStatus = (await applicationsApi.resume(row.application_id)).status;
      if (plan.kind === "shortlist" || plan.kind === "not_shortlist") {
        newStatus = (
          await shortlistingApi.updateStatus(row.application_id, {
            target_status: plan.kind === "shortlist" ? "shortlisted" : "not_shortlisted",
            reason: null,
            feedback: null,
          })
        ).status;
      }
      setNotice({
        text: t("candidates.move.done", { name: row.candidate_name || t("candidates.unnamed"), stage: t(`candidates.stage.${columnOf(newStatus)}`) }),
        severity: "success",
      });
      loadPage();
    } catch (err) {
      setNotice({ text: extractErrorMessage(err, t("candidates.move.failed")), severity: "error" });
    } finally {
      setMoving(false);
      setPendingMove(null);
    }
  };

  const moveName = pendingMove?.row.candidate_name || t("candidates.unnamed");
  const moveText = pendingMove
    ? {
        hold: t("candidates.move.confirm_hold", { name: moveName, job: pendingMove.row.job_title }),
        resume: t("candidates.move.confirm_resume", { name: moveName }),
        shortlist: t("candidates.move.confirm_shortlist", { name: moveName }),
        not_shortlist: t("candidates.move.confirm_not_shortlist", { name: moveName }),
      }[pendingMove.plan.kind]
    : "";

  // ---- ListToolbar wiring ----
  const toolbarColumns: ListColumn[] = [
    { key: "candidate", label: t("candidates.col.candidate") },
    { key: "email", label: t("candidates.fact.email") },
    ...HIDEABLE_COLUMNS.filter((k) => k !== "resume").map((k) => ({ key: k, label: t(`candidates.col.${k}`) })),
  ];
  const toolbarState: ListViewState = {
    columns: ["candidate", "email", ...visibleColumns],
    filters: { ...filters, search: searchInput } as unknown as Record<string, unknown>,
  };
  const onToolbarState = (next: ListViewState) => {
    // "resume" is an icon column with nothing to export, so the chooser leaves it alone.
    const chosen = next.columns.filter((c) => c !== "resume" && (HIDEABLE_COLUMNS as readonly string[]).includes(c));
    setVisibleColumns(visibleColumns.includes("resume") ? [...chosen, "resume"] : chosen);
    const nf = (next.filters ?? {}) as Record<string, unknown>;
    const restored: CandidateFilters = { ...EMPTY_CANDIDATE_FILTERS };
    (Object.keys(EMPTY_CANDIDATE_FILTERS) as (keyof CandidateFilters)[]).forEach((k) => {
      if (typeof nf[k] === "string") restored[k] = nf[k] as string;
    });
    if (JSON.stringify(restored) !== JSON.stringify(filters)) setFilters(restored);
    if (typeof nf.search === "string" && nf.search !== searchInput) setSearchInput(nf.search);
  };
  const exportRows = rows.map((row) => ({
    candidate: row.candidate_name ?? "",
    email: row.candidate_email ?? "",
    source: row.source,
    job: jobById.get(row.job_role_id)?.title ?? row.job_title,
    applied: row.applied_on,
    experience: row.experience_years,
    location: row.location,
    match: resumeMatchScoreDisplay(row).value,
    status: statusStyle(row.status).label,
    remarks: row.remarks,
  }));

  const show = (key: string) => visibleColumns.includes(key);
  const columnCount = 3 + HIDEABLE_COLUMNS.filter(show).length;

  const rowActions = (row: CandidateApplicationRow) =>
    canWrite ? <CandidateActionsMenu row={row} onChanged={loadPage} onDeleted={handleRowDeleted} onError={setError} /> : null;

  const headerCells = (
    <TableRow>
      <TableCell padding="checkbox">
        <Checkbox
          indeterminate={someOnPageSelected && !allOnPageSelected}
          checked={allOnPageSelected}
          onChange={toggleSelectAllOnPage}
          inputProps={{ "aria-label": t("candidates.list.select_page") }}
        />
      </TableCell>
      <TableCell>{t("candidates.col.candidate")}</TableCell>
      {show("source") && <TableCell>{t("candidates.col.source")}</TableCell>}
      {show("job") && <TableCell>{t("candidates.col.job")}</TableCell>}
      {show("applied") && <TableCell>{t("candidates.col.applied")}</TableCell>}
      {show("experience") && <TableCell>{t("candidates.col.experience")}</TableCell>}
      {show("location") && <TableCell>{t("candidates.col.location")}</TableCell>}
      {show("match") && <TableCell>{t("candidates.col.match")}</TableCell>}
      {show("resume") && <TableCell>{t("candidates.col.resume")}</TableCell>}
      {show("status") && <TableCell>{t("candidates.col.status")}</TableCell>}
      {show("remarks") && <TableCell>{t("candidates.col.remarks")}</TableCell>}
      <TableCell align="right">{t("candidates.col.actions")}</TableCell>
    </TableRow>
  );

  return (
    <Box>
      <PageHeader
        emoji="technologist"
        title={t("candidates.list.title")}
        purpose={t("candidates.list.purpose")}
        tourKey="candidates"
        primary={
          canWrite ? (
            <Button variant="contained" startIcon={<PersonAddAltOutlinedIcon />} onClick={() => setUploadDialogOpen(true)}>
              {t("candidates.upload_resume")}
            </Button>
          ) : undefined
        }
        extra={
          <ToggleButtonGroup
            exclusive
            size="small"
            value={viewMode}
            onChange={(_e, v: ViewMode | null) => v && setViewMode(v)}
            aria-label={t("candidates.list.view_switch")}
          >
            <ToggleButton value="table" aria-label={t("candidates.list.view_table")}>
              <TableRowsOutlinedIcon fontSize="small" sx={{ mr: 0.75 }} />
              {t("candidates.list.view_table")}
            </ToggleButton>
            <ToggleButton value="board" aria-label={t("candidates.list.view_board")}>
              <ViewKanbanOutlinedIcon fontSize="small" sx={{ mr: 0.75 }} />
              {t("candidates.list.view_board")}
            </ToggleButton>
          </ToggleButtonGroup>
        }
      />

      <Card sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ xs: "stretch", md: "center" }} sx={{ mb: 1.5 }}>
          <TextField
            size="small"
            placeholder={t("candidates.list.search")}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }, htmlInput: { "aria-label": t("candidates.list.search") } }}
            sx={{ minWidth: 260, flex: { md: "0 1 360px" } }}
          />
          <Typography sx={{ color: f.muted, fontSize: 13 }} aria-live="polite">
            {t("candidates.list.count", { count: total })}
          </Typography>
          <Box sx={{ flex: 1 }} />
          <Button variant="outlined" size="small" startIcon={<DownloadOutlinedIcon />} onClick={handleExportCsv} disabled={total === 0}>
            {selectedIds.size > 0 ? t("candidates.list.export_selected", { count: selectedIds.size }) : t("candidates.list.export_all")}
          </Button>
        </Stack>
        <CandidateFiltersPanel jobs={jobs} filters={filters} onChange={setFilters} />
      </Card>

      <ListToolbar
        listKey={LIST_KEY}
        columns={toolbarColumns}
        state={toolbarState}
        onStateChange={onToolbarState}
        rows={exportRows}
        loading={loading}
        onRefresh={handleRefresh}
        selectedCount={viewMode === "table" ? selectedIds.size : 0}
        bulkActions={
          <>
            <Button size="small" variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={handleExportCsv}>
              {t("candidates.list.export_selected", { count: selectedIds.size })}
            </Button>
            <Button size="small" onClick={() => setSelectedIds(new Set())}>{t("candidates.list.clear_selection")}</Button>
          </>
        }
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {loadError ? (
        <FriendlyError error={loadError} onRetry={loadPage} />
      ) : loading ? (
        viewMode === "board" ? (
          <Stack direction="row" spacing={1.5} sx={{ overflow: "hidden" }}>
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} variant="rounded" width={272} height={320} sx={{ borderRadius: "18px", flexShrink: 0 }} />)}
          </Stack>
        ) : (
          <Card>
            <TableContainer>
              <Table size="small">
                <TableHead>{headerCells}</TableHead>
                <TableBody>
                  {Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: columnCount }).map((__, j) => (
                        <TableCell key={j}><Skeleton variant="text" /></TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Card>
        )
      ) : rows.length === 0 ? (
        <Card>
          {total === 0 && !anyFilterActive ? (
            <EmptyState
              illustration="people-search"
              title={t("candidates.list.empty")}
              hint={t("candidates.list.empty_hint")}
              action={
                <Button variant="contained" onClick={() => navigate("/candidates/import")}>
                  {t("candidates.import_button")}
                </Button>
              }
            />
          ) : (
            <EmptyState
              illustration="search"
              title={t("candidates.list.no_match")}
              action={<Button variant="outlined" onClick={handleRefresh}>{t("candidates.list.clear_filters")}</Button>}
            />
          )}
        </Card>
      ) : viewMode === "board" ? (
        <>
          <Typography sx={{ color: f.muted, fontSize: 13, mb: 1 }}>
            {canWrite ? t("candidates.kanban.hint") : t("candidates.kanban.hint_readonly")}
            {total > rows.length ? ` ${t("candidates.kanban.partial", { shown: rows.length, count: total })}` : ""}
          </Typography>
          <CandidatesKanban rows={rows} canWrite={canWrite} onMove={requestMove} onOpen={(row) => navigate(`/candidates/${row.application_id}`)} renderActions={rowActions} />
        </>
      ) : (
        <>
          <Card>
            <TableContainer>
              <Table size="small">
                <TableHead>{headerCells}</TableHead>
                <TableBody>
                  {rows.map((row) => {
                    const name = row.candidate_name || t("candidates.unnamed");
                    return (
                      <TableRow key={row.application_id} hover selected={selectedIds.has(row.application_id)}>
                        <TableCell padding="checkbox">
                          <Checkbox
                            checked={selectedIds.has(row.application_id)}
                            onChange={() => toggleSelectOne(row.application_id)}
                            inputProps={{ "aria-label": t("candidates.list.select_one", { name }) }}
                          />
                        </TableCell>
                        <TableCell>
                          <Stack direction="row" spacing={1.25} alignItems="center">
                            <CandidateAvatar candidateId={row.candidate_id} photoPath={row.photo_path} name={row.candidate_name} email={row.candidate_email} sx={{ width: 32, height: 32, fontSize: 12 }} />
                            <Box sx={{ minWidth: 0 }}>
                              <Typography variant="body2" fontWeight={700} noWrap>{name}</Typography>
                              {row.candidate_email && (
                                <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
                                  {row.candidate_email}
                                </Typography>
                              )}
                            </Box>
                          </Stack>
                        </TableCell>
                        {show("source") && <TableCell><SourceIcon source={row.source} /></TableCell>}
                        {show("job") && <TableCell>{jobById.get(row.job_role_id)?.title ?? row.job_title}</TableCell>}
                        {show("applied") && <TableCell>{new Date(row.applied_on).toLocaleDateString()}</TableCell>}
                        {show("experience") && <TableCell>{row.experience_years != null ? t("candidates.years", { count: row.experience_years }) : "—"}</TableCell>}
                        {show("location") && <TableCell>{row.location || "—"}</TableCell>}
                        {show("match") && (
                          <TableCell>
                            {(() => {
                              const { value, tooltip } = resumeMatchScoreDisplay(row);
                              if (value == null) return "—";
                              return (
                                <Tooltip title={tooltip}>
                                  <Box component="span" sx={{ fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{Math.round(value)}%</Box>
                                </Tooltip>
                              );
                            })()}
                          </TableCell>
                        )}
                        {show("resume") && (
                          <TableCell>
                            {row.resume_path ? (
                              <Tooltip title={t("candidates.resume.download")}>
                                <span>
                                  <IconButton size="small" aria-label={t("candidates.resume.download_named", { name })} onClick={() => handleDownloadResume(row)} disabled={downloadingResumeFor === row.application_id}>
                                    {downloadingResumeFor === row.application_id ? <DownloadingOutlinedIcon fontSize="small" /> : <DownloadOutlinedIcon fontSize="small" />}
                                  </IconButton>
                                </span>
                              </Tooltip>
                            ) : (
                              "—"
                            )}
                          </TableCell>
                        )}
                        {show("status") && <TableCell><StatusChip status={row.status} /></TableCell>}
                        {show("remarks") && (
                          <TableCell sx={{ maxWidth: 220 }}>
                            {row.remarks ? (
                              <Tooltip title={row.remarks}>
                                <Typography variant="body2" noWrap>{row.remarks}</Typography>
                              </Tooltip>
                            ) : (
                              "—"
                            )}
                          </TableCell>
                        )}
                        <TableCell align="right">
                          <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                            <Tooltip title={t("candidates.list.view")}>
                              <IconButton size="small" aria-label={t("candidates.list.view_named", { name })} onClick={() => navigate(`/candidates/${row.application_id}`)}>
                                <VisibilityOutlinedIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            {canWrite && (
                              <Tooltip title={t("candidates.list.edit_contact")}>
                                <IconButton size="small" aria-label={t("candidates.list.edit_contact_named", { name })} onClick={() => setEditingCandidate(row)}>
                                  <EditOutlinedIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            )}
                            {rowActions(row)}
                          </Stack>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          </Card>

          <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
            <Typography variant="body2" color="text.secondary">
              {selectedIds.size > 0 ? `${t("candidates.list.selected", { count: selectedIds.size })} · ` : ""}
              {t("candidates.list.showing", { start: pageStart, end: pageEnd, count: total })}
            </Typography>
            <Stack direction="row" spacing={2} alignItems="center">
              <FormControl size="small" sx={{ minWidth: 130 }}>
                <InputLabel id="candidates-rows-per-page-label">{t("candidates.list.rows_per_page")}</InputLabel>
                <Select labelId="candidates-rows-per-page-label" label={t("candidates.list.rows_per_page")} value={pageSize} onChange={handlePageSizeChange}>
                  {ROWS_PER_PAGE_OPTIONS.map((size) => (
                    <MenuItem key={size} value={size}>{size}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Pagination count={pageCount} page={page} onChange={(_e, value) => setPage(value)} size="small" color="primary" />
            </Stack>
          </Stack>
        </>
      )}

      <UploadCandidateDialog open={uploadDialogOpen} onClose={() => setUploadDialogOpen(false)} onLinked={loadPage} />
      <EditCandidateContactDialog
        candidateId={editingCandidate?.candidate_id ?? null}
        open={Boolean(editingCandidate)}
        onClose={() => setEditingCandidate(null)}
        onSaved={loadPage}
      />
      <ConfirmDialog
        open={Boolean(pendingMove)}
        title={pendingMove ? t("candidates.move.confirm_title", { stage: t(`candidates.stage.${pendingMove.to}`) }) : ""}
        message={moveText}
        confirmLabel={t("candidates.move.confirm_button")}
        confirming={moving}
        destructive={pendingMove?.plan.kind === "not_shortlist"}
        onConfirm={runMove}
        onCancel={() => setPendingMove(null)}
      />
      <Snackbar open={Boolean(notice)} autoHideDuration={6000} onClose={() => setNotice(null)} anchorOrigin={{ vertical: "bottom", horizontal: "center" }}>
        {notice ? (
          <Alert severity={notice.severity} onClose={() => setNotice(null)} variant="filled" sx={{ maxWidth: 520 }}>
            {notice.text}
          </Alert>
        ) : undefined}
      </Snackbar>
    </Box>
  );
}
