import { useEffect, useMemo, useState } from "react";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import DownloadingOutlinedIcon from "@mui/icons-material/DownloadingOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import PersonAddAltOutlinedIcon from "@mui/icons-material/PersonAddAltOutlined";
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

import { candidatesApi, extractErrorMessage, jobsApi } from "../api/client";
import { isTerminalApplicationStatus, type CandidateApplicationRow, type JobRoleRead } from "../api/types";
import CandidateActionsMenu from "../components/CandidateActionsMenu";
import CandidateAvatar from "../components/CandidateAvatar";
import CandidateFiltersPanel, { EMPTY_CANDIDATE_FILTERS, type CandidateFilters } from "../components/CandidateFiltersPanel";
import EditCandidateContactDialog from "../components/EditCandidateContactDialog";
import SourceIcon from "../components/SourceIcon";
import UploadCandidateDialog from "../components/UploadCandidateDialog";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { downloadCsv } from "../utils/csv";
import { downloadResume } from "../utils/resume";

const ROWS_PER_PAGE_OPTIONS = [10, 20, 30, 40, 50];
const DEFAULT_PAGE_SIZE = 10;
const SEARCH_DEBOUNCE_MS = 300;

// Distinct from the "Active"/"Inactive" reading everywhere else in the app (see
// isTerminalApplicationStatus) -- on_hold is neither: it's a real, resumable pipeline
// state that should read as visibly different from "still actively progressing," not get
// silently folded into "Active" just because it isn't terminal.
function ApplicationStatusChip({ status }: { status: string }) {
  if (status === "on_hold") {
    return <Chip label="On Hold" size="small" color="info" variant="outlined" />;
  }
  const active = !isTerminalApplicationStatus(status);
  return <Chip label={active ? "Active" : "Inactive"} size="small" color={active ? "success" : "default"} variant="outlined" />;
}

const COLUMN_COUNT = 11;

export default function CandidatesListPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.candidatesWrite);
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

  // Manual single-candidate upload + link-to-job -- the only existing real functionality
  // from the old flat Candidates page, kept as a secondary action since it's still the
  // only way to attach a resume that didn't come through a job's career portal listing or
  // a bulk CSV import (that path lives on its own page now -- see /candidates/import).
  // Dialog itself is shared with the Candidates Dashboard's "Add Candidate" button.
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [editingCandidate, setEditingCandidate] = useState<CandidateApplicationRow | null>(null);
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
      .catch((err) => setError(extractErrorMessage(err, "Failed to load candidates")))
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

  // Selected rows export exactly themselves, ignoring every filter -- otherwise (nothing
  // checked) export the full filtered result set. Either way this hits the dedicated
  // unpaginated export endpoint, never the paginated list endpoint the table itself uses
  // (that one caps page_size at 200 and was never meant for "give me everything").
  const handleExportCsv = async () => {
    try {
      const result =
        selectedIds.size > 0
          ? await candidatesApi.exportApplications({ applicationIds: Array.from(selectedIds) })
          : await candidatesApi.exportApplications(listParams());
      downloadCsv(
        "candidates.csv",
        ["Candidate", "Email", "Job Applied", "Status", "Source", "Applied On", "Experience (yrs)", "Match Score", "Location"],
        result.map((row) => [
          row.candidate_name,
          row.candidate_email,
          row.job_title,
          row.status,
          row.source,
          row.applied_on,
          row.experience_years,
          row.match_score,
          row.location,
        ]),
      );
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to export candidates"));
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

  const jobById = useMemo(() => new Map(jobs.map((job) => [job.id, job])), [jobs]);

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

  const handleRowDeleted = (applicationId: string) => {
    setSelectedIds((prev) => {
      if (!prev.has(applicationId)) return prev;
      const next = new Set(prev);
      next.delete(applicationId);
      return next;
    });
    loadPage();
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">Candidates List</Typography>
          <Typography variant="body2" color="text.secondary">
            {total} candidate application{total === 1 ? "" : "s"}
          </Typography>
        </Box>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
          {canWrite && (
            <Button variant="outlined" startIcon={<PersonAddAltOutlinedIcon />} onClick={() => setUploadDialogOpen(true)}>
              Upload Resume
            </Button>
          )}
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
        <CandidateFiltersPanel jobs={jobs} filters={filters} onChange={setFilters} />
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
                <TableCell>Exp</TableCell>
                <TableCell>Location</TableCell>
                <TableCell>Match Score</TableCell>
                <TableCell>Resume</TableCell>
                <TableCell>Status</TableCell>
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
            ? "No candidates yet. Import from a source or wait for career portal applications to come in."
            : "No candidates match the current filters."}
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
                  <TableCell>Exp</TableCell>
                  <TableCell>Location</TableCell>
                  <TableCell>Match Score</TableCell>
                  <TableCell>Resume</TableCell>
                  <TableCell>Status</TableCell>
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
                    <TableCell>{jobById.get(row.job_role_id)?.title ?? row.job_title}</TableCell>
                    <TableCell>{new Date(row.applied_on).toLocaleDateString()}</TableCell>
                    <TableCell>{row.experience_years != null ? `${row.experience_years}y` : "—"}</TableCell>
                    <TableCell>{row.location || "—"}</TableCell>
                    <TableCell>{row.match_score != null ? `${Math.round(row.match_score)}%` : "—"}</TableCell>
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
                    <TableCell>
                      <ApplicationStatusChip status={row.status} />
                    </TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                        <Tooltip title="View">
                          <IconButton size="small" onClick={() => navigate(`/candidates/${row.application_id}`)}>
                            <VisibilityOutlinedIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        {canWrite && (
                          <Tooltip title="Edit contact info">
                            <IconButton size="small" onClick={() => setEditingCandidate(row)}>
                              <EditOutlinedIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        )}
                        {canWrite && (
                          <CandidateActionsMenu
                            row={row}
                            onChanged={loadPage}
                            onDeleted={handleRowDeleted}
                            onError={setError}
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
            <Typography variant="body2" color="text.secondary">
              {selectedIds.size > 0 ? `${selectedIds.size} selected · ` : ""}
              Showing {pageStart} to {pageEnd} of {total} candidates
            </Typography>
            <Stack direction="row" spacing={2} alignItems="center">
              <FormControl size="small" sx={{ minWidth: 130 }}>
                <InputLabel id="candidates-rows-per-page-label">Rows per page</InputLabel>
                <Select
                  labelId="candidates-rows-per-page-label"
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

      <UploadCandidateDialog
        open={uploadDialogOpen}
        onClose={() => setUploadDialogOpen(false)}
        onLinked={loadPage}
      />
      <EditCandidateContactDialog
        candidateId={editingCandidate?.candidate_id ?? null}
        open={Boolean(editingCandidate)}
        onClose={() => setEditingCandidate(null)}
        onSaved={loadPage}
      />
    </Box>
  );
}
