import { useEffect, useState } from "react";
import CompareArrowsOutlinedIcon from "@mui/icons-material/CompareArrowsOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import DownloadingOutlinedIcon from "@mui/icons-material/DownloadingOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import SearchIcon from "@mui/icons-material/Search";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
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
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useNavigate, useSearchParams } from "react-router-dom";

import { jobsApi, shortlistingApi } from "../api/client";
import {
  SHORTLIST_STATUS_LABELS,
  SHORTLIST_STATUSES,
  shortlistStatusOf,
  type ApplicationRead,
  type CandidateApplicationRow,
  type JobRoleRead,
  type ShortlistBulkDecisionResult,
  type ShortlistStatus,
} from "../api/types";
import CandidateFiltersPanel, { EMPTY_CANDIDATE_FILTERS, type CandidateFilters } from "../components/CandidateFiltersPanel";
import ListToolbar, { type ListColumn, type ListViewState } from "../components/ListToolbar";
import RetryNegotiationMenuItem, { isRetryNegotiationEligible } from "../components/RetryNegotiationMenuItem";
import ShortlistStatusPanel, { REASON_OPTIONS } from "../components/ShortlistStatusPanel";
import SourceIcon from "../components/SourceIcon";
import AutoShortlistNotice from "../components/screening/AutoShortlistNotice";
import CompareDialog, { MAX_COMPARE } from "../components/screening/CompareDialog";
import { useScreeningDetails } from "../components/screening/hooks";
import { CandidateCell, DEFAULT_PAGE_SIZE, loadSortedPage, PaginationFooter, SortSelect, type SortMode } from "../components/screening/listParts";
import RejectReasonDialog from "../components/screening/RejectReasonDialog";
import { ScoreBadge } from "../components/screening/ScoreParts";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { useT } from "../i18n";
import { EmptyState, FriendlyError, PageHeader, StatusChip, type Tone } from "../ui-kit";
import { downloadCsv } from "../utils/csv";
import { downloadResume } from "../utils/resume";
import { screeningScoreDisplay } from "../utils/screeningScore";

const SEARCH_DEBOUNCE_MS = 300;
const COLUMN_KEYS = ["source", "job", "applied", "experience", "location", "score", "shortlist", "resume"] as const;

const SHORTLIST_CHIP: Record<ShortlistStatus, { tone: Tone; emoji: string }> = {
  under_review: { tone: "sky", emoji: "eyes" },
  shortlisted: { tone: "ok", emoji: "star" },
  on_hold: { tone: "muted", emoji: "pause" },
  not_shortlisted: { tone: "coral", emoji: "cross" },
};

function ShortlistStatusChip({ applicationStatus }: { applicationStatus: string }) {
  const t = useT();
  const status = shortlistStatusOf(applicationStatus);
  if (!status) return <>—</>;
  return <StatusChip {...SHORTLIST_CHIP[status]} label={t(`shortlisting.status.${status}`)} />;
}

function ShortlistingActionsMenu({
  row, canDecide, onView, onUpdateStatus, onRetryDone, onRetryError,
}: {
  row: CandidateApplicationRow;
  canDecide: boolean;
  onView: (applicationId: string) => void;
  onUpdateStatus: (row: CandidateApplicationRow) => void;
  onRetryDone: () => void;
  onRetryError: (message: string) => void;
}) {
  const t = useT();
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const showRetry = canDecide && isRetryNegotiationEligible(row);

  return (
    <>
      <IconButton
        size="small"
        onClick={(e) => setAnchorEl(e.currentTarget)}
        aria-label={t("screening.actions_for", { name: row.candidate_name || t("screening.unnamed") })}
        aria-haspopup="menu"
      >
        <MoreVertIcon fontSize="small" />
      </IconButton>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        <MenuItem
          onClick={() => {
            setAnchorEl(null);
            onView(row.application_id);
          }}
        >
          <VisibilityOutlinedIcon fontSize="small" sx={{ mr: 1 }} />
          {t("screening.view")}
        </MenuItem>
        {canDecide && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              onUpdateStatus(row);
            }}
          >
            {t("shortlisting.update_status")}
          </MenuItem>
        )}
        {showRetry && (
          <RetryNegotiationMenuItem row={row} onClose={() => setAnchorEl(null)} onDone={onRetryDone} onError={onRetryError} />
        )}
      </Menu>
    </>
  );
}

type BulkTarget = Extract<ShortlistStatus, "shortlisted" | "not_shortlisted">;

// Part H: the Shortlisting module's own filterable, paginated table, scoped to the
// shortlisting stage only (see backend app/shortlisting/router.py list_shortlisting).
// Part 15.4: one-click shortlist (S6), reject needs a reason from the company list (S7),
// highest score first (S3), compare up to 3 (S5), auto-shortlist undo window (K F1).
export default function ShortlistingListPage() {
  const t = useT();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { can } = useAuth();
  const canDecide = can(ROLE_MATRIX.screeningDecisions);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [rows, setRows] = useState<CandidateApplicationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [downloadingResumeFor, setDownloadingResumeFor] = useState<string | null>(null);
  const [quickBusy, setQuickBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const initialStatus = searchParams.get("shortlist_status");
  const [filters, setFilters] = useState<CandidateFilters>({
    ...EMPTY_CANDIDATE_FILTERS,
    status: initialStatus && (SHORTLIST_STATUSES as readonly string[]).includes(initialStatus) ? initialStatus : "",
  });
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("score");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [refreshKey, setRefreshKey] = useState(0);
  const anyFilterActive = Boolean(search) || Object.values(filters).some(Boolean);
  // A Map (not just a Set of ids) so the confirmation dialogs can always show real candidate
  // names, even for rows selected on a page that's since been paged away from.
  const [selectedRows, setSelectedRows] = useState<Map<string, CandidateApplicationRow>>(new Map());
  const [visibleColumns, setVisibleColumns] = useState<string[]>([...COLUMN_KEYS]);
  const [compareOpen, setCompareOpen] = useState(false);

  const [statusPanelRow, setStatusPanelRow] = useState<CandidateApplicationRow | null>(null);
  const [rejectRows, setRejectRows] = useState<CandidateApplicationRow[] | null>(null);
  const [rejectSubmitting, setRejectSubmitting] = useState(false);

  const [bulkTarget, setBulkTarget] = useState<BulkTarget | null>(null);
  const [bulkReason, setBulkReason] = useState("");
  const [bulkFeedback, setBulkFeedback] = useState("");
  const [bulkSubmitting, setBulkSubmitting] = useState(false);
  const [bulkResult, setBulkResult] = useState<{
    result: ShortlistBulkDecisionResult;
    target: BulkTarget;
    namesById: Map<string, string>;
  } | null>(null);

  const columns: ListColumn[] = COLUMN_KEYS.map((key) => ({ key, label: t(`shortlisting.col.${key}`) }));
  const show = (key: string) => visibleColumns.includes(key);

  useEffect(() => {
    jobsApi.list().then(setJobs).catch(() => setJobs([]));
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
  }, [filters, search, sort]);

  const listParams = () => ({
    search: search || undefined,
    jobRoleId: filters.jobRoleId || undefined,
    shortlistStatus: (filters.status || undefined) as ShortlistStatus | undefined,
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
    loadSortedPage(sort, { scope: "shortlisting", page, pageSize, ...listParams() }, () =>
      shortlistingApi.listShortlisting({ page, pageSize, ...listParams() }),
    )
      .then((result) => {
        setRows(result.items);
        setTotal(result.total);
      })
      .catch(setLoadError)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search, filters, sort, refreshKey]);

  const details = useScreeningDetails(rows.map((r) => r.application_id), refreshKey);

  const handleRefresh = () => {
    setFilters(EMPTY_CANDIDATE_FILTERS);
    setSearchInput("");
    setSearch("");
    setPage(1);
    setPageSize(DEFAULT_PAGE_SIZE);
    setRefreshKey((k) => k + 1);
  };

  const reload = () => setRefreshKey((k) => k + 1);

  const handleExportCsv = async () => {
    try {
      const result =
        selectedRows.size > 0
          ? await shortlistingApi.exportShortlisting({ applicationIds: Array.from(selectedRows.keys()) })
          : await shortlistingApi.exportShortlisting(listParams());
      downloadCsv(
        "shortlisting.csv",
        [
          "Candidate", "Email", "Source", "Job Title", "Applied On", "Experience (yrs)", "Location",
          "Screening Score", "Shortlist Status",
        ],
        result.map((row) => [
          row.candidate_name,
          row.candidate_email,
          row.source,
          row.job_title,
          row.applied_on,
          row.experience_years,
          row.location,
          row.composite_score ?? row.match_score,
          shortlistStatusOf(row.status) ? SHORTLIST_STATUS_LABELS[shortlistStatusOf(row.status)!] : "",
        ]),
      );
    } catch (err) {
      setActionError(err);
    }
  };

  const handleDownloadResume = async (row: CandidateApplicationRow) => {
    setDownloadingResumeFor(row.application_id);
    setActionError(null);
    try {
      await downloadResume(row.candidate_id, row.resume_path, row.candidate_name);
    } catch (err) {
      setActionError(err);
    } finally {
      setDownloadingResumeFor(null);
    }
  };

  const allOnPageSelected = rows.length > 0 && rows.every((row) => selectedRows.has(row.application_id));
  const someOnPageSelected = rows.some((row) => selectedRows.has(row.application_id));

  const toggleSelectAllOnPage = () => {
    setSelectedRows((prev) => {
      const next = new Map(prev);
      if (allOnPageSelected) rows.forEach((row) => next.delete(row.application_id));
      else rows.forEach((row) => next.set(row.application_id, row));
      return next;
    });
  };

  const toggleSelectOne = (row: CandidateApplicationRow) => {
    setSelectedRows((prev) => {
      const next = new Map(prev);
      if (next.has(row.application_id)) next.delete(row.application_id);
      else next.set(row.application_id, row);
      return next;
    });
  };

  const handleStatusSaved = (_updated: ApplicationRead) => {
    setStatusPanelRow(null);
    loadPage();
  };

  // S6: one click, reason optional (it can still be added later via Update status).
  const quickShortlist = async (row: CandidateApplicationRow) => {
    setQuickBusy(row.application_id);
    setActionError(null);
    try {
      await shortlistingApi.updateStatus(row.application_id, { target_status: "shortlisted", reason: null, feedback: null });
      setToast(t("shortlisting.quick.done", { name: row.candidate_name || t("screening.unnamed") }));
      loadPage();
    } catch (err) {
      setActionError(err);
    } finally {
      setQuickBusy(null);
    }
  };

  // S7: one candidate or a batch -- always with a reason from the company list.
  const confirmReject = async (reason: string, feedback: string) => {
    if (!rejectRows) return;
    setRejectSubmitting(true);
    setActionError(null);
    try {
      if (rejectRows.length === 1) {
        await shortlistingApi.updateStatus(rejectRows[0].application_id, { target_status: "not_shortlisted", reason, feedback: feedback || null });
        setToast(t("shortlisting.reject.done", { name: rejectRows[0].candidate_name || t("screening.unnamed") }));
      } else {
        const namesById = new Map(rejectRows.map((row) => [row.application_id, row.candidate_name || t("screening.unnamed")]));
        const result = await shortlistingApi.bulkDecision({
          application_ids: rejectRows.map((r) => r.application_id),
          target_status: "not_shortlisted",
          reason,
          feedback: feedback || null,
        });
        setBulkResult({ result, target: "not_shortlisted", namesById });
        setSelectedRows(new Map());
      }
      setRejectRows(null);
      loadPage();
    } catch (err) {
      setActionError(err);
    } finally {
      setRejectSubmitting(false);
    }
  };

  const openBulkShortlist = () => {
    setBulkTarget("shortlisted");
    setBulkReason("");
    setBulkFeedback("");
  };

  const handleBulkConfirm = async () => {
    if (!bulkTarget) return;
    setBulkSubmitting(true);
    setActionError(null);
    const namesById = new Map(Array.from(selectedRows.values()).map((row) => [row.application_id, row.candidate_name || t("screening.unnamed")]));
    try {
      const result = await shortlistingApi.bulkDecision({
        application_ids: Array.from(selectedRows.keys()),
        target_status: bulkTarget,
        reason: bulkReason || null,
        feedback: bulkFeedback || null,
      });
      setBulkResult({ result, target: bulkTarget, namesById });
      setBulkTarget(null);
      setSelectedRows(new Map());
      loadPage();
    } catch (err) {
      setActionError(err);
    } finally {
      setBulkSubmitting(false);
    }
  };

  const viewState: ListViewState = { columns: visibleColumns, filters: { ...filters, search: searchInput, sort } };
  const applyViewState = (next: ListViewState) => {
    if (Array.isArray(next.columns) && next.columns.length > 0) setVisibleColumns(next.columns);
    const raw = (next.filters ?? {}) as Record<string, string>;
    const { search: s = "", sort: so, ...rest } = raw;
    const nextFilters = { ...EMPTY_CANDIDATE_FILTERS, ...rest } as CandidateFilters;
    if (JSON.stringify(nextFilters) !== JSON.stringify(filters)) setFilters(nextFilters);
    if (s !== searchInput) setSearchInput(s);
    if ((so === "score" || so === "newest") && so !== sort) setSort(so);
  };

  const csvRows = rows.map((row) => {
    const st = shortlistStatusOf(row.status);
    return {
      source: row.source, job: row.job_title, applied: row.applied_on, experience: row.experience_years, location: row.location,
      score: screeningScoreDisplay(row).value, shortlist: st ? t(`shortlisting.status.${st}`) : "", resume: row.resume_path ? "yes" : "",
    };
  });

  const selectedList = Array.from(selectedRows.values());
  const canCompare = selectedRows.size >= 2 && selectedRows.size <= MAX_COMPARE;
  const statusOptions = SHORTLIST_STATUSES.map((status) => ({ value: status, label: t(`shortlisting.status.${status}`) }));

  const headCells = (
    <>
      <TableCell>{t("screening.col.candidate")}</TableCell>
      {show("source") && <TableCell>{t("shortlisting.col.source")}</TableCell>}
      {show("job") && <TableCell>{t("shortlisting.col.job")}</TableCell>}
      {show("applied") && <TableCell>{t("shortlisting.col.applied")}</TableCell>}
      {show("experience") && <TableCell>{t("shortlisting.col.experience")}</TableCell>}
      {show("location") && <TableCell>{t("shortlisting.col.location")}</TableCell>}
      {show("score") && <TableCell>{t("shortlisting.col.score")}</TableCell>}
      {show("shortlist") && <TableCell>{t("shortlisting.col.shortlist")}</TableCell>}
      {show("resume") && <TableCell>{t("shortlisting.col.resume")}</TableCell>}
      <TableCell align="right">{t("screening.col.actions")}</TableCell>
    </>
  );
  const columnCount = 3 + COLUMN_KEYS.filter(show).length;

  return (
    <Box>
      <PageHeader
        emoji="star"
        title={t("shortlisting.list.title")}
        purpose={t("shortlisting.list.purpose")}
        tourKey="shortlisting"
        primary={
          <Button variant="contained" startIcon={<DownloadOutlinedIcon />} onClick={handleExportCsv} disabled={total === 0}>
            {selectedRows.size > 0 ? t("screening.export_selected", { count: selectedRows.size }) : t("screening.export_all", { count: total })}
          </Button>
        }
      />

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ xs: "stretch", md: "center" }} mb={2}>
        <TextField
          size="small"
          placeholder={t("screening.search")}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          slotProps={{
            input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> },
            htmlInput: { "aria-label": t("screening.search") },
          }}
          sx={{ minWidth: 260 }}
        />
        <SortSelect id="shortlisting" value={sort} onChange={setSort} />
      </Stack>

      <Box mb={2}>
        <CandidateFiltersPanel
          jobs={jobs}
          filters={filters}
          onChange={setFilters}
          scoreLabel="Screening"
          statusLabel={t("shortlisting.col.shortlist")}
          statusOptions={statusOptions}
        />
      </Box>

      {actionError != null && <Box mb={2}><FriendlyError error={actionError} compact /></Box>}
      {actionMessage && <Box mb={2}><FriendlyError what={actionMessage} fix={t("screening.retry_fix")} compact /></Box>}

      {bulkResult && (
        <Alert severity={bulkResult.result.skipped.length > 0 ? "warning" : "success"} sx={{ mb: 2 }} onClose={() => setBulkResult(null)}>
          <Typography variant="body2" fontWeight={600}>
            {t(bulkResult.target === "shortlisted" ? "shortlisting.bulk.result_shortlisted" : "shortlisting.bulk.result_rejected", {
              done: bulkResult.result.succeeded.length,
              count: bulkResult.result.succeeded.length + bulkResult.result.skipped.length,
            })}
            {bulkResult.result.skipped.length > 0 ? ` ${t("shortlisting.bulk.skipped", { count: bulkResult.result.skipped.length })}` : ""}
          </Typography>
          {bulkResult.result.skipped.length > 0 && (
            <Stack spacing={0.25} mt={0.5}>
              {bulkResult.result.skipped.map((skip) => (
                <Typography key={skip.application_id} variant="body2">
                  • {bulkResult.namesById.get(skip.application_id) || t("shortlisting.unknown_candidate")} — {skip.reason}
                </Typography>
              ))}
            </Stack>
          )}
        </Alert>
      )}

      <ListToolbar
        listKey="shortlisting_list"
        columns={columns}
        state={viewState}
        onStateChange={applyViewState}
        rows={csvRows}
        loading={loading}
        onRefresh={handleRefresh}
        selectedCount={selectedRows.size}
        bulkActions={
          <>
            {canDecide && (
              <>
                <Button size="small" variant="contained" color="success" onClick={openBulkShortlist}>
                  {t("shortlisting.bulk.shortlist")}
                </Button>
                <Button size="small" variant="outlined" color="error" onClick={() => setRejectRows(selectedList)}>
                  {t("shortlisting.bulk.reject")}
                </Button>
              </>
            )}
            <Tooltip title={selectedRows.size > MAX_COMPARE ? t("screening.compare.too_many", { max: MAX_COMPARE }) : ""}>
              <span>
                <Button size="small" startIcon={<CompareArrowsOutlinedIcon />} disabled={!canCompare} onClick={() => setCompareOpen(true)}>
                  {t("screening.compare.button", { count: Math.min(selectedRows.size, MAX_COMPARE) })}
                </Button>
              </span>
            </Tooltip>
          </>
        }
      />

      {loadError != null ? (
        <FriendlyError error={loadError} onRetry={loadPage} />
      ) : loading ? (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox" />
                {headCells}
              </TableRow>
            </TableHead>
            <TableBody>
              {Array.from({ length: 6 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: columnCount }).map((__, j) => (
                    <TableCell key={j}><Skeleton variant="text" /></TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : rows.length === 0 ? (
        <Card>
          {total === 0 && !anyFilterActive ? (
            <EmptyState
              illustration="people-search"
              title={t("shortlisting.empty.none")}
              hint={t("shortlisting.empty.none_hint")}
              action={<Button variant="contained" onClick={() => navigate("/screening/list")}>{t("shortlisting.empty.go_screening")}</Button>}
            />
          ) : (
            <EmptyState
              illustration="search"
              title={t("screening.empty.filtered")}
              action={<Button variant="outlined" onClick={handleRefresh}>{t("screening.empty.clear")}</Button>}
            />
          )}
        </Card>
      ) : (
        <>
          <TableContainer component={Paper} data-tour="shortlisting-table">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox">
                    <Checkbox
                      indeterminate={someOnPageSelected && !allOnPageSelected}
                      checked={allOnPageSelected}
                      onChange={toggleSelectAllOnPage}
                      slotProps={{ input: { "aria-label": t("screening.select_page") } }}
                    />
                  </TableCell>
                  {headCells}
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => {
                  const { value, tooltip } = screeningScoreDisplay(row);
                  const detail = details.get(row.application_id);
                  const st = shortlistStatusOf(row.status);
                  const open = st === "under_review" || st === "on_hold";
                  const name = row.candidate_name || t("screening.unnamed");
                  return (
                    <TableRow key={row.application_id} hover selected={selectedRows.has(row.application_id)}>
                      <TableCell padding="checkbox">
                        <Checkbox
                          checked={selectedRows.has(row.application_id)}
                          onChange={() => toggleSelectOne(row)}
                          slotProps={{ input: { "aria-label": t("screening.select_one", { name }) } }}
                        />
                      </TableCell>
                      <TableCell><CandidateCell row={row} /></TableCell>
                      {show("source") && <TableCell><SourceIcon source={row.source} /></TableCell>}
                      {show("job") && <TableCell>{row.job_title}</TableCell>}
                      {show("applied") && <TableCell>{new Date(row.applied_on).toLocaleDateString()}</TableCell>}
                      {show("experience") && (
                        <TableCell>{row.experience_years != null ? t("screening.years", { count: row.experience_years }) : "—"}</TableCell>
                      )}
                      {show("location") && <TableCell>{row.location || "—"}</TableCell>}
                      {show("score") && <TableCell><ScoreBadge value={value} detail={detail} fallbackHint={tooltip} /></TableCell>}
                      {show("shortlist") && (
                        <TableCell>
                          <Stack spacing={0.75} alignItems="flex-start">
                            <ShortlistStatusChip applicationStatus={row.status} />
                            {detail?.auto_shortlist && (
                              <AutoShortlistNotice
                                info={detail.auto_shortlist}
                                applicationId={row.application_id}
                                canDecide={canDecide}
                                onUndone={() => {
                                  setToast(t("shortlisting.auto.undone_toast", { name }));
                                  reload();
                                }}
                                onError={setActionError}
                              />
                            )}
                          </Stack>
                        </TableCell>
                      )}
                      {show("resume") && (
                        <TableCell>
                          {row.resume_path ? (
                            <Tooltip title={t("shortlisting.download_resume")}>
                              <span>
                                <IconButton
                                  size="small"
                                  onClick={() => handleDownloadResume(row)}
                                  disabled={downloadingResumeFor === row.application_id}
                                  aria-label={t("shortlisting.download_resume_for", { name })}
                                >
                                  {downloadingResumeFor === row.application_id ? (
                                    <DownloadingOutlinedIcon fontSize="small" />
                                  ) : (
                                    <DownloadOutlinedIcon fontSize="small" />
                                  )}
                                </IconButton>
                              </span>
                            </Tooltip>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                      )}
                      <TableCell align="right">
                        <Stack direction="row" spacing={0.5} justifyContent="flex-end" alignItems="center">
                          {canDecide && open && (
                            <>
                              <Button
                                size="small"
                                variant="contained"
                                color="success"
                                onClick={() => quickShortlist(row)}
                                disabled={quickBusy != null}
                                aria-label={t("shortlisting.quick.aria", { name })}
                                sx={{ whiteSpace: "nowrap" }}
                              >
                                {quickBusy === row.application_id ? <CircularProgress size={14} color="inherit" /> : t("shortlisting.quick.button")}
                              </Button>
                              <Button
                                size="small"
                                color="error"
                                onClick={() => setRejectRows([row])}
                                disabled={quickBusy != null}
                                aria-label={t("shortlisting.reject.aria", { name })}
                              >
                                {t("shortlisting.reject.button")}
                              </Button>
                            </>
                          )}
                          <ShortlistingActionsMenu
                            row={row}
                            canDecide={canDecide}
                            onView={(applicationId) => navigate(`/candidates/${applicationId}`)}
                            onUpdateStatus={setStatusPanelRow}
                            onRetryDone={loadPage}
                            onRetryError={setActionMessage}
                          />
                        </Stack>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>

          <PaginationFooter
            id="shortlisting"
            page={page}
            pageSize={pageSize}
            total={total}
            selected={selectedRows.size}
            onPage={setPage}
            onPageSize={(n) => {
              setPageSize(n);
              setPage(1);
            }}
          />
        </>
      )}

      <Dialog open={statusPanelRow != null} onClose={() => setStatusPanelRow(null)} fullWidth maxWidth="sm">
        <DialogTitle>
          {t("shortlisting.update_status_for", { name: statusPanelRow?.candidate_name || t("shortlisting.panel.this_candidate") })}
        </DialogTitle>
        <DialogContent>
          {statusPanelRow && (
            <Box mt={1}>
              <ShortlistStatusPanel
                applicationId={statusPanelRow.application_id}
                candidateName={statusPanelRow.candidate_name}
                currentApplicationStatus={statusPanelRow.status}
                onSaved={handleStatusSaved}
              />
            </Box>
          )}
        </DialogContent>
      </Dialog>

      <RejectReasonDialog
        open={rejectRows != null}
        people={(rejectRows ?? []).map((r) => ({ id: r.application_id, name: r.candidate_name || t("screening.unnamed"), job: r.job_title }))}
        submitting={rejectSubmitting}
        onCancel={() => setRejectRows(null)}
        onConfirm={confirmReject}
      />

      <Dialog open={bulkTarget != null} onClose={() => (bulkSubmitting ? null : setBulkTarget(null))} fullWidth maxWidth="sm">
        <DialogTitle>{t("shortlisting.bulk.title", { count: selectedRows.size })}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            <Typography variant="body2" color="text.secondary">{t("shortlisting.bulk.applies_to")}</Typography>
            <Box sx={{ maxHeight: 200, overflowY: "auto" }}>
              <Stack spacing={0.75} divider={<Divider />}>
                {selectedList.map((row) => (
                  <Stack key={row.application_id} direction="row" justifyContent="space-between" gap={2}>
                    <Typography variant="body2">{row.candidate_name || t("screening.unnamed")}</Typography>
                    <Typography variant="body2" color="text.secondary">{row.job_title}</Typography>
                  </Stack>
                ))}
              </Stack>
            </Box>

            <TextField select label={t("shortlisting.panel.reason_optional")} size="small" value={bulkReason} onChange={(e) => setBulkReason(e.target.value)} fullWidth>
              <MenuItem value="">{t("shortlisting.panel.no_reason")}</MenuItem>
              {REASON_OPTIONS.map((option) => (
                <MenuItem key={option} value={option}>{option}</MenuItem>
              ))}
            </TextField>

            <TextField
              label={t("shortlisting.bulk.feedback")}
              value={bulkFeedback}
              onChange={(e) => setBulkFeedback(e.target.value)}
              fullWidth
              multiline
              minRows={3}
              placeholder={t("shortlisting.feedback_placeholder")}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBulkTarget(null)} disabled={bulkSubmitting}>{t("action.cancel")}</Button>
          <Button
            variant="contained"
            color="success"
            onClick={handleBulkConfirm}
            disabled={bulkSubmitting}
            startIcon={bulkSubmitting ? <CircularProgress size={14} color="inherit" /> : undefined}
          >
            {bulkSubmitting ? t("screening.saving") : t("shortlisting.bulk.confirm", { count: selectedRows.size })}
          </Button>
        </DialogActions>
      </Dialog>

      <CompareDialog
        open={compareOpen}
        rows={selectedList}
        onClose={() => setCompareOpen(false)}
        onOpenCandidate={(id) => navigate(`/candidates/${id}`)}
      />

      <Snackbar open={toast != null} autoHideDuration={5000} onClose={() => setToast(null)} message={toast ?? ""} />
    </Box>
  );
}
