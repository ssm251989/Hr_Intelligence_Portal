import { useEffect, useState } from "react";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import SearchIcon from "@mui/icons-material/Search";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import FormControl from "@mui/material/FormControl";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import InputLabel from "@mui/material/InputLabel";
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

import { candidatesApi, extractErrorMessage, jobsApi, screeningApi } from "../api/client";
import { isTerminalApplicationStatus, type CandidateApplicationRow, type JobRoleRead } from "../api/types";
import CandidateAvatar from "../components/CandidateAvatar";
import CandidateFiltersPanel, { EMPTY_CANDIDATE_FILTERS, type CandidateFilters } from "../components/CandidateFiltersPanel";
import SourceIcon from "../components/SourceIcon";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { downloadCsv } from "../utils/csv";
import { screeningScoreDisplay } from "../utils/screeningScore";

const ROWS_PER_PAGE_OPTIONS = [10, 20, 30, 40, 50];
const DEFAULT_PAGE_SIZE = 10;
const SEARCH_DEBOUNCE_MS = 300;
const COLUMN_COUNT = 12;

// Same "Active"/"Inactive"/"On Hold" reading as the Candidates List -- one status chip
// language across every table in the app, not a per-page variant.
function ApplicationStatusChip({ status }: { status: string }) {
  if (status === "on_hold") {
    return <Chip label="On Hold" size="small" color="info" variant="outlined" />;
  }
  const active = !isTerminalApplicationStatus(status);
  return <Chip label={active ? "Active" : "Inactive"} size="small" color={active ? "success" : "default"} variant="outlined" />;
}

// Part E: the Screening module's own filterable, paginated table -- same architecture as
// the Candidates List (same filters panel, same list/export endpoints, same table/
// pagination shell) but focused on the screening decisions themselves: Skill Match/
// Screening Score/Ranking Score columns, and Screen/Rank row actions instead of
// edit-contact/delete. Replaces the old single-job-dropdown-plus-cards page.
export default function ScreeningListPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const canDecide = can(ROLE_MATRIX.screeningDecisions);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [rows, setRows] = useState<CandidateApplicationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);

  const [filters, setFilters] = useState<CandidateFilters>(EMPTY_CANDIDATE_FILTERS);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const anyFilterActive = Boolean(search) || Object.values(filters).some(Boolean);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

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
    // This page's score range filter targets composite_score (the Screening Score column),
    // not the raw Resume Match score the Candidates List's identical-looking filter uses.
    scoreField: "composite_score" as const,
  });

  const loadPage = () => {
    setLoading(true);
    setError(null);
    candidatesApi
      .listApplications({ page, pageSize, ...listParams() })
      .then((result) => {
        setRows(result.items);
        setTotal(result.total);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load applications")))
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
        selectedIds.size > 0
          ? await candidatesApi.exportApplications({ applicationIds: Array.from(selectedIds) })
          : await candidatesApi.exportApplications(listParams());
      downloadCsv(
        "screening.csv",
        [
          "Candidate", "Email", "Job Applied", "Status", "Applied On", "Skill Match %",
          "Screening Score", "Resume Match", "Ranking Score", "Remarks",
        ],
        result.map((row) => [
          row.candidate_name,
          row.candidate_email,
          row.job_title,
          row.status,
          row.applied_on,
          row.skill_match_pct,
          row.composite_score ?? row.match_score,
          row.match_score,
          row.ranking_score,
          row.remarks,
        ]),
      );
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to export screening data"));
    }
  };

  const allOnPageSelected = rows.length > 0 && rows.every((row) => selectedIds.has(row.application_id));
  const someOnPageSelected = rows.some((row) => selectedIds.has(row.application_id));

  const toggleSelectAllOnPage = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        rows.forEach((row) => next.delete(row.application_id));
      } else {
        rows.forEach((row) => next.add(row.application_id));
      }
      return next;
    });
  };

  const toggleSelectOne = (applicationId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(applicationId)) {
        next.delete(applicationId);
      } else {
        next.add(applicationId);
      }
      return next;
    });
  };

  const handleScreen = async (applicationId: string) => {
    setActionId(applicationId);
    setError(null);
    try {
      await screeningApi.screen(applicationId);
      loadPage();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to screen application"));
    } finally {
      setActionId(null);
    }
  };

  const handleRank = async (applicationId: string) => {
    setActionId(applicationId);
    setError(null);
    try {
      await screeningApi.rank(applicationId);
      loadPage();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to rank application"));
    } finally {
      setActionId(null);
    }
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">Screening List</Typography>
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
            {selectedIds.size > 0 ? `Export (${selectedIds.size} selected)` : "Export"}
          </Button>
        </Stack>
      </Stack>

      <Box mb={3}>
        <CandidateFiltersPanel jobs={jobs} filters={filters} onChange={setFilters} scoreLabel="Screening" />
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading ? (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox" />
                <TableCell>Candidate</TableCell>
                <TableCell>Source</TableCell>
                <TableCell>Job Applied</TableCell>
                <TableCell>Applied On</TableCell>
                <TableCell>Skill Match</TableCell>
                <TableCell>Screening Score</TableCell>
                <TableCell>Ranking Score</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Remarks</TableCell>
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
            ? "No applications yet."
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
                  <TableCell>Job Applied</TableCell>
                  <TableCell>Applied On</TableCell>
                  <TableCell>Skill Match</TableCell>
                  <TableCell>Screening Score</TableCell>
                  <TableCell>Ranking Score</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Remarks</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.application_id} hover selected={selectedIds.has(row.application_id)}>
                    <TableCell padding="checkbox">
                      <Checkbox
                        checked={selectedIds.has(row.application_id)}
                        onChange={() => toggleSelectOne(row.application_id)}
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
                    <TableCell>{row.skill_match_pct != null ? `${Math.round(row.skill_match_pct)}%` : "—"}</TableCell>
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
                    <TableCell>{row.ranking_score != null ? row.ranking_score : "—"}</TableCell>
                    <TableCell>
                      <ApplicationStatusChip status={row.status} />
                    </TableCell>
                    <TableCell sx={{ maxWidth: 220 }}>
                      {row.remarks ? (
                        <Tooltip title={row.remarks}>
                          <Typography variant="body2" noWrap>
                            {row.remarks}
                          </Typography>
                        </Tooltip>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} justifyContent="flex-end" alignItems="center">
                        <Tooltip title="View">
                          <IconButton size="small" onClick={() => navigate(`/candidates/${row.application_id}`)}>
                            <VisibilityOutlinedIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        {canDecide && row.status === "received" && (
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => handleScreen(row.application_id)}
                            disabled={actionId === row.application_id}
                          >
                            {actionId === row.application_id ? "Screening..." : "Screen"}
                          </Button>
                        )}
                        {canDecide && row.match_score != null && (
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => handleRank(row.application_id)}
                            disabled={actionId === row.application_id}
                          >
                            {actionId === row.application_id
                              ? "Ranking..."
                              : row.ranking_score != null
                                ? "Re-rank"
                                : "Rank"}
                          </Button>
                        )}
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
            <Typography variant="body2" color="text.secondary">
              {selectedIds.size > 0 ? `${selectedIds.size} selected · ` : ""}
              Showing {pageStart} to {pageEnd} of {total} applications
            </Typography>
            <Stack direction="row" spacing={2} alignItems="center">
              <FormControl size="small" sx={{ minWidth: 130 }}>
                <InputLabel id="screening-rows-per-page-label">Rows per page</InputLabel>
                <Select
                  labelId="screening-rows-per-page-label"
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
    </Box>
  );
}
