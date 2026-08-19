import { useEffect, useState } from "react";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import DownloadingOutlinedIcon from "@mui/icons-material/DownloadingOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import SearchIcon from "@mui/icons-material/Search";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import FormControl from "@mui/material/FormControl";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import InputLabel from "@mui/material/InputLabel";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Pagination from "@mui/material/Pagination";
import Paper from "@mui/material/Paper";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Skeleton from "@mui/material/Skeleton";
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
import { useNavigate } from "react-router-dom";

import { extractErrorMessage, jobsApi, shortlistingApi } from "../api/client";
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
import CandidateAvatar from "../components/CandidateAvatar";
import CandidateFiltersPanel, { EMPTY_CANDIDATE_FILTERS, type CandidateFilters } from "../components/CandidateFiltersPanel";
import ShortlistStatusPanel, { REASON_OPTIONS } from "../components/ShortlistStatusPanel";
import SourceIcon from "../components/SourceIcon";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { downloadCsv } from "../utils/csv";
import { downloadResume } from "../utils/resume";
import { screeningScoreDisplay } from "../utils/screeningScore";

const ROWS_PER_PAGE_OPTIONS = [10, 20, 30, 40, 50];
const DEFAULT_PAGE_SIZE = 10;
const SEARCH_DEBOUNCE_MS = 300;
const COLUMN_COUNT = 10;

const SHORTLIST_STATUS_FILTER_OPTIONS = SHORTLIST_STATUSES.map((status) => ({
  value: status,
  label: SHORTLIST_STATUS_LABELS[status],
}));

const SHORTLIST_STATUS_COLOR: Record<ShortlistStatus, "default" | "success" | "warning" | "error"> = {
  under_review: "default",
  shortlisted: "success",
  on_hold: "warning",
  not_shortlisted: "error",
};

function ShortlistStatusChip({ applicationStatus }: { applicationStatus: string }) {
  const status = shortlistStatusOf(applicationStatus);
  if (!status) return <>—</>;
  return <Chip label={SHORTLIST_STATUS_LABELS[status]} size="small" color={SHORTLIST_STATUS_COLOR[status]} variant="outlined" />;
}

function ShortlistingActionsMenu({
  row,
  canDecide,
  onView,
  onUpdateStatus,
}: {
  row: CandidateApplicationRow;
  canDecide: boolean;
  onView: (applicationId: string) => void;
  onUpdateStatus: (row: CandidateApplicationRow) => void;
}) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);

  return (
    <>
      <IconButton size="small" onClick={(e) => setAnchorEl(e.currentTarget)}>
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
          View
        </MenuItem>
        {canDecide && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              onUpdateStatus(row);
            }}
          >
            Update Status
          </MenuItem>
        )}
      </Menu>
    </>
  );
}

// Part H: the Shortlisting module's own filterable, paginated table -- same architecture as
// the Candidates/Screening Lists (same filters panel, same list/export endpoints, same
// table/pagination shell), scoped to the shortlisting stage only (see backend
// app/shortlisting/router.py list_shortlisting) and with a Shortlist Status column/filter/
// action in place of the raw pipeline Status.
export default function ShortlistingListPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const canDecide = can(ROLE_MATRIX.screeningDecisions);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [rows, setRows] = useState<CandidateApplicationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingResumeFor, setDownloadingResumeFor] = useState<string | null>(null);

  const [filters, setFilters] = useState<CandidateFilters>(EMPTY_CANDIDATE_FILTERS);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const anyFilterActive = Boolean(search) || Object.values(filters).some(Boolean);
  // A Map (not just a Set of ids) -- a row can only ever be checked while it's actually
  // rendered on the page the recruiter is looking at, so keeping the full row alongside its
  // id means the bulk-decision confirmation dialog can always show real candidate names,
  // even for rows selected on a page that's since been paged away from.
  const [selectedRows, setSelectedRows] = useState<Map<string, CandidateApplicationRow>>(new Map());

  const [statusPanelRow, setStatusPanelRow] = useState<CandidateApplicationRow | null>(null);

  const [bulkTarget, setBulkTarget] = useState<Extract<ShortlistStatus, "shortlisted" | "not_shortlisted"> | null>(null);
  const [bulkReason, setBulkReason] = useState("");
  const [bulkFeedback, setBulkFeedback] = useState("");
  const [bulkSubmitting, setBulkSubmitting] = useState(false);
  const [bulkResult, setBulkResult] = useState<{
    result: ShortlistBulkDecisionResult;
    target: Extract<ShortlistStatus, "shortlisted" | "not_shortlisted">;
    namesById: Map<string, string>;
  } | null>(null);

  useEffect(() => {
    jobsApi.list().then(setJobs).catch(() => setJobs([]));
  }, []);

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
    setError(null);
    shortlistingApi
      .listShortlisting({ page, pageSize, ...listParams() })
      .then((result) => {
        setRows(result.items);
        setTotal(result.total);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load shortlisting")))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search, filters]);

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pageStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = Math.min(page * pageSize, total);

  const handlePageSizeChange = (event: SelectChangeEvent<number>) => {
    setPageSize(Number(event.target.value));
    setPage(1);
  };

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
      setError(extractErrorMessage(err, "Failed to export shortlisting data"));
    }
  };

  const handleDownloadResume = async (row: CandidateApplicationRow) => {
    setDownloadingResumeFor(row.application_id);
    setError(null);
    try {
      await downloadResume(row.candidate_id, row.resume_path, row.candidate_name);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to download resume"));
    } finally {
      setDownloadingResumeFor(null);
    }
  };

  const allOnPageSelected = rows.length > 0 && rows.every((row) => selectedRows.has(row.application_id));
  const someOnPageSelected = rows.some((row) => selectedRows.has(row.application_id));

  const toggleSelectAllOnPage = () => {
    setSelectedRows((prev) => {
      const next = new Map(prev);
      if (allOnPageSelected) {
        rows.forEach((row) => next.delete(row.application_id));
      } else {
        rows.forEach((row) => next.set(row.application_id, row));
      }
      return next;
    });
  };

  const toggleSelectOne = (row: CandidateApplicationRow) => {
    setSelectedRows((prev) => {
      const next = new Map(prev);
      if (next.has(row.application_id)) {
        next.delete(row.application_id);
      } else {
        next.set(row.application_id, row);
      }
      return next;
    });
  };

  const handleStatusSaved = (_updated: ApplicationRead) => {
    setStatusPanelRow(null);
    loadPage();
  };

  const openBulkDialog = (target: Extract<ShortlistStatus, "shortlisted" | "not_shortlisted">) => {
    setBulkTarget(target);
    setBulkReason("");
    setBulkFeedback("");
  };

  const handleBulkConfirm = async () => {
    if (!bulkTarget) return;
    setBulkSubmitting(true);
    setError(null);
    const namesById = new Map(Array.from(selectedRows.values()).map((row) => [row.application_id, row.candidate_name || "Unnamed candidate"]));
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
      setError(extractErrorMessage(err, "Failed to process the batch decision"));
    } finally {
      setBulkSubmitting(false);
    }
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">Shortlisting List</Typography>
          <Typography variant="body2" color="text.secondary">
            {total} application{total === 1 ? "" : "s"}
          </Typography>
        </Box>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
          <TextField
            size="small"
            placeholder="Search by name or email"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
            sx={{ minWidth: 220 }}
          />
          <Button variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={handleExportCsv} disabled={total === 0}>
            {selectedRows.size > 0 ? `Export (${selectedRows.size} selected)` : "Export"}
          </Button>
        </Stack>
      </Stack>

      <Box mb={3}>
        <CandidateFiltersPanel
          jobs={jobs}
          filters={filters}
          onChange={setFilters}
          scoreLabel="Screening"
          statusLabel="Shortlist Status"
          statusOptions={SHORTLIST_STATUS_FILTER_OPTIONS}
        />
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {bulkResult && (
        <Alert severity={bulkResult.result.skipped.length > 0 ? "warning" : "success"} sx={{ mb: 2 }} onClose={() => setBulkResult(null)}>
          <Typography variant="body2" fontWeight={600}>
            {bulkResult.result.succeeded.length} of {bulkResult.result.succeeded.length + bulkResult.result.skipped.length}{" "}
            {bulkResult.target === "shortlisted" ? "shortlisted" : "rejected"} successfully.
            {bulkResult.result.skipped.length > 0 ? ` ${bulkResult.result.skipped.length} skipped:` : ""}
          </Typography>
          {bulkResult.result.skipped.length > 0 && (
            <Stack spacing={0.25} mt={0.5}>
              {bulkResult.result.skipped.map((skip) => (
                <Typography key={skip.application_id} variant="body2">
                  • {bulkResult.namesById.get(skip.application_id) || "Unknown candidate"} — {skip.reason}
                </Typography>
              ))}
            </Stack>
          )}
        </Alert>
      )}

      {canDecide && selectedRows.size > 0 && (
        <Stack
          direction="row"
          spacing={2}
          alignItems="center"
          sx={{ mb: 2, p: 1.5, borderRadius: 1, bgcolor: "action.selected" }}
        >
          <Typography variant="body2" fontWeight={600}>
            {selectedRows.size} selected
          </Typography>
          <Button size="small" variant="contained" color="success" onClick={() => openBulkDialog("shortlisted")}>
            Shortlist Selected
          </Button>
          <Button size="small" variant="outlined" color="error" onClick={() => openBulkDialog("not_shortlisted")}>
            Reject Selected
          </Button>
        </Stack>
      )}

      {loading ? (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox" />
                <TableCell>Candidate</TableCell>
                <TableCell>Source</TableCell>
                <TableCell>Job Title</TableCell>
                <TableCell>Applied On</TableCell>
                <TableCell>Exp</TableCell>
                <TableCell>Location</TableCell>
                <TableCell>Screening Score</TableCell>
                <TableCell>Shortlist Status</TableCell>
                <TableCell>Resume</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: COLUMN_COUNT }).map((__, j) => (
                    <TableCell key={j}>
                      <Skeleton variant="text" />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : rows.length === 0 ? (
        <Typography color="text.secondary">
          {total === 0 && !anyFilterActive
            ? "No applications in the shortlisting stage yet."
            : "No applications match the current filters."}
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
                  <TableCell>Candidate</TableCell>
                  <TableCell>Source</TableCell>
                  <TableCell>Job Title</TableCell>
                  <TableCell>Applied On</TableCell>
                  <TableCell>Exp</TableCell>
                  <TableCell>Location</TableCell>
                  <TableCell>Screening Score</TableCell>
                  <TableCell>Shortlist Status</TableCell>
                  <TableCell>Resume</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.application_id} hover selected={selectedRows.has(row.application_id)}>
                    <TableCell padding="checkbox">
                      <Checkbox
                        checked={selectedRows.has(row.application_id)}
                        onChange={() => toggleSelectOne(row)}
                      />
                    </TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={1.25} alignItems="center">
                        <CandidateAvatar
                          candidateId={row.candidate_id}
                          photoPath={row.photo_path}
                          name={row.candidate_name}
                          email={row.candidate_email}
                          sx={{ width: 28, height: 28, fontSize: 12 }}
                        />
                        <Box sx={{ minWidth: 0 }}>
                          <Typography variant="body2" fontWeight={600} noWrap>
                            {row.candidate_name || "Unnamed candidate"}
                          </Typography>
                          {row.candidate_email && (
                            <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
                              {row.candidate_email}
                            </Typography>
                          )}
                        </Box>
                      </Stack>
                    </TableCell>
                    <TableCell>
                      <SourceIcon source={row.source} />
                    </TableCell>
                    <TableCell>{row.job_title}</TableCell>
                    <TableCell>{new Date(row.applied_on).toLocaleDateString()}</TableCell>
                    <TableCell>{row.experience_years != null ? `${row.experience_years}y` : "—"}</TableCell>
                    <TableCell>{row.location || "—"}</TableCell>
                    <TableCell>
                      {(() => {
                        const { value, tooltip } = screeningScoreDisplay(row);
                        if (value == null) return "—";
                        return (
                          <Tooltip title={tooltip}>
                            <span>{Math.round(value)}%</span>
                          </Tooltip>
                        );
                      })()}
                    </TableCell>
                    <TableCell>
                      <ShortlistStatusChip applicationStatus={row.status} />
                    </TableCell>
                    <TableCell>
                      {row.resume_path ? (
                        <Tooltip title="Download resume">
                          <span>
                            <IconButton
                              size="small"
                              onClick={() => handleDownloadResume(row)}
                              disabled={downloadingResumeFor === row.application_id}
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
                    <TableCell align="right">
                      <ShortlistingActionsMenu
                        row={row}
                        canDecide={canDecide}
                        onView={(applicationId) => navigate(`/candidates/${applicationId}`)}
                        onUpdateStatus={setStatusPanelRow}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
            <Typography variant="body2" color="text.secondary">
              {selectedRows.size > 0 ? `${selectedRows.size} selected · ` : ""}
              Showing {pageStart} to {pageEnd} of {total} applications
            </Typography>
            <Stack direction="row" spacing={2} alignItems="center">
              <FormControl size="small" sx={{ minWidth: 130 }}>
                <InputLabel id="shortlisting-rows-per-page-label">Rows per page</InputLabel>
                <Select
                  labelId="shortlisting-rows-per-page-label"
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
              <Pagination count={pageCount} page={page} onChange={(_e, value) => setPage(value)} size="small" color="primary" />
            </Stack>
          </Stack>
        </>
      )}

      <Dialog open={statusPanelRow != null} onClose={() => setStatusPanelRow(null)} fullWidth maxWidth="sm">
        <DialogTitle>Update Shortlist Status{statusPanelRow ? ` — ${statusPanelRow.candidate_name || "Candidate"}` : ""}</DialogTitle>
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

      <Dialog open={bulkTarget != null} onClose={() => (bulkSubmitting ? null : setBulkTarget(null))} fullWidth maxWidth="sm">
        <DialogTitle>
          {bulkTarget === "shortlisted" ? "Shortlist" : "Reject"} {selectedRows.size} candidate
          {selectedRows.size === 1 ? "" : "s"}?
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            <Typography variant="body2" color="text.secondary">
              This decision will be applied to every candidate listed below:
            </Typography>
            <Box sx={{ maxHeight: 200, overflowY: "auto" }}>
              <Stack spacing={0.75} divider={<Divider />}>
                {Array.from(selectedRows.values()).map((row) => (
                  <Stack key={row.application_id} direction="row" justifyContent="space-between">
                    <Typography variant="body2">{row.candidate_name || "Unnamed candidate"}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {row.job_title}
                    </Typography>
                  </Stack>
                ))}
              </Stack>
            </Box>

            <TextField
              select
              label="Reason / Recommendation"
              size="small"
              value={bulkReason}
              onChange={(e) => setBulkReason(e.target.value)}
              fullWidth
            >
              <MenuItem value="">No reason selected</MenuItem>
              {REASON_OPTIONS.map((option) => (
                <MenuItem key={option} value={option}>
                  {option}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              label="Feedback (optional, applied to every candidate in this batch)"
              value={bulkFeedback}
              onChange={(e) => setBulkFeedback(e.target.value)}
              fullWidth
              multiline
              minRows={3}
              placeholder="Individual feedback can still be edited later on each candidate's own detail page."
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBulkTarget(null)} disabled={bulkSubmitting}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color={bulkTarget === "shortlisted" ? "success" : "error"}
            onClick={handleBulkConfirm}
            disabled={bulkSubmitting}
            startIcon={bulkSubmitting ? <CircularProgress size={14} color="inherit" /> : undefined}
          >
            {bulkSubmitting
              ? "Processing..."
              : `Confirm ${bulkTarget === "shortlisted" ? "Shortlist" : "Reject"} (${selectedRows.size})`}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
