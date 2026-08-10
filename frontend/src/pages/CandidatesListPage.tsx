import { useEffect, useMemo, useRef, useState } from "react";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import PersonAddAltOutlinedIcon from "@mui/icons-material/PersonAddAltOutlined";
import SearchIcon from "@mui/icons-material/Search";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import Alert from "@mui/material/Alert";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
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

import { applicationsApi, candidatesApi, extractErrorMessage, jobsApi } from "../api/client";
import { isTerminalApplicationStatus, type CandidateApplicationRow, type CandidateRead, type JobRoleRead } from "../api/types";
import CandidateFiltersPanel, { EMPTY_CANDIDATE_FILTERS, type CandidateFilters } from "../components/CandidateFiltersPanel";
import SourceChip from "../components/SourceChip";
import StatusChip from "../components/StatusChip";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { downloadCsv } from "../utils/csv";
import { initials } from "../utils/avatar";
import { resumeHref } from "../utils/resume";

const ROWS_PER_PAGE_OPTIONS = [10, 20, 30, 40, 50];
const DEFAULT_PAGE_SIZE = 10;
const SEARCH_DEBOUNCE_MS = 300;

export default function CandidatesListPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.candidatesWrite);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [rows, setRows] = useState<CandidateApplicationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [filters, setFilters] = useState<CandidateFilters>(EMPTY_CANDIDATE_FILTERS);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  // Manual single-candidate upload + link-to-job -- the only existing real functionality
  // from the old flat Candidates page, kept as a secondary action since it's still the
  // only way to attach a resume that didn't come through a job's career portal listing or
  // a bulk CSV import (that path lives on its own page now -- see /candidates/import).
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadedCandidate, setUploadedCandidate] = useState<CandidateRead | null>(null);
  const [linkJobId, setLinkJobId] = useState("");
  const [linkExpectedSalary, setLinkExpectedSalary] = useState("");
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const loadPage = () => {
    setLoading(true);
    setError(null);
    candidatesApi
      .listApplications({
        page,
        pageSize,
        search: search || undefined,
        jobRoleId: filters.jobRoleId || undefined,
        status: filters.status || undefined,
        source: filters.source || undefined,
        location: filters.location || undefined,
      })
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

  const handleExportCsv = async () => {
    try {
      const result = await candidatesApi.listApplications({
        page: 1,
        pageSize: 1000,
        search: search || undefined,
        jobRoleId: filters.jobRoleId || undefined,
        status: filters.status || undefined,
        source: filters.source || undefined,
        location: filters.location || undefined,
      });
      downloadCsv(
        "candidates.csv",
        ["Candidate", "Email", "Job Applied", "Stage", "Source", "Applied On", "Experience (yrs)", "Match Score", "Location"],
        result.items.map((row) => [
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

  const jobById = useMemo(() => new Map(jobs.map((job) => [job.id, job])), [jobs]);

  const openUploadDialog = () => {
    setSelectedFile(null);
    setUploadError(null);
    setUploadedCandidate(null);
    setLinkJobId("");
    setLinkExpectedSalary("");
    setLinkError(null);
    setUploadDialogOpen(true);
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      setUploadError("Choose a resume file first");
      return;
    }
    setUploadError(null);
    setUploading(true);
    try {
      const created = await candidatesApi.upload(selectedFile);
      setUploadedCandidate(created);
    } catch (err) {
      setUploadError(extractErrorMessage(err, "Failed to upload resume"));
    } finally {
      setUploading(false);
    }
  };

  const handleLink = async () => {
    if (!uploadedCandidate) return;
    if (!linkJobId) {
      setLinkError("Select a job");
      return;
    }
    setLinking(true);
    setLinkError(null);
    try {
      await applicationsApi.create({
        job_role_id: linkJobId,
        candidate_id: uploadedCandidate.id,
        expected_salary: linkExpectedSalary ? Number(linkExpectedSalary) : null,
      });
      setUploadDialogOpen(false);
      loadPage();
    } catch (err) {
      setLinkError(extractErrorMessage(err, "Failed to link candidate to job"));
    } finally {
      setLinking(false);
    }
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">Candidates List</Typography>
          <Typography variant="body2" color="text.secondary">
            {total} candidate application{total === 1 ? "" : "s"}
          </Typography>
        </Box>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
          {canWrite && (
            <Button variant="outlined" startIcon={<PersonAddAltOutlinedIcon />} onClick={openUploadDialog}>
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
          <CandidateFiltersPanel jobs={jobs} filters={filters} onChange={setFilters} />
          <Button variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={handleExportCsv} disabled={total === 0}>
            Export
          </Button>
        </Stack>
      </Stack>

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
                <TableCell>Candidate</TableCell>
                <TableCell>Job Applied</TableCell>
                <TableCell>Stage</TableCell>
                <TableCell>Source</TableCell>
                <TableCell>Applied On</TableCell>
                <TableCell>Experience</TableCell>
                <TableCell>Match Score</TableCell>
                <TableCell>Resume</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: 10 }).map((__, j) => (
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
          {total === 0 && !search && !filters.jobRoleId && !filters.status && !filters.source && !filters.location
            ? "No candidates yet. Import from a source or wait for career portal applications to come in."
            : "No candidates match the current filters."}
        </Typography>
      ) : (
        <>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Candidate</TableCell>
                  <TableCell>Job Applied</TableCell>
                  <TableCell>Stage</TableCell>
                  <TableCell>Source</TableCell>
                  <TableCell>Applied On</TableCell>
                  <TableCell>Experience</TableCell>
                  <TableCell>Match Score</TableCell>
                  <TableCell>Resume</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => {
                  const href = resumeHref(row.candidate_id, row.resume_path);
                  const active = !isTerminalApplicationStatus(row.status);
                  return (
                    <TableRow key={row.application_id} hover>
                      <TableCell>
                        <Stack direction="row" spacing={1.25} alignItems="center">
                          <Avatar sx={{ width: 28, height: 28, fontSize: 12, bgcolor: "primary.main" }}>
                            {initials(row.candidate_name || row.candidate_email || "?")}
                          </Avatar>
                          <Box>
                            <Typography variant="body2" noWrap>
                              {row.candidate_name || "Unnamed candidate"}
                            </Typography>
                            {row.candidate_email && (
                              <Typography variant="caption" color="text.secondary" noWrap>
                                {row.candidate_email}
                              </Typography>
                            )}
                          </Box>
                        </Stack>
                      </TableCell>
                      <TableCell>{jobById.get(row.job_role_id)?.title ?? row.job_title}</TableCell>
                      <TableCell>
                        <StatusChip status={row.status} />
                      </TableCell>
                      <TableCell>
                        <SourceChip source={row.source} />
                      </TableCell>
                      <TableCell>{new Date(row.applied_on).toLocaleDateString()}</TableCell>
                      <TableCell>{row.experience_years != null ? `${row.experience_years}y` : "—"}</TableCell>
                      <TableCell>{row.match_score != null ? `${Math.round(row.match_score)}%` : "—"}</TableCell>
                      <TableCell>
                        {href ? (
                          <IconButton size="small" component="a" href={href} target="_blank" rel="noreferrer">
                            <DescriptionOutlinedIcon fontSize="small" />
                          </IconButton>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell>
                        <Chip label={active ? "Active" : "Inactive"} size="small" color={active ? "success" : "default"} variant="outlined" />
                      </TableCell>
                      <TableCell align="right">
                        <Tooltip title="View">
                          <IconButton size="small" onClick={() => navigate(`/candidates/${row.application_id}`)}>
                            <VisibilityOutlinedIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>

          <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
            <Typography variant="body2" color="text.secondary">
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

      <Dialog open={uploadDialogOpen} onClose={() => setUploadDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{uploadedCandidate ? "Link to a Job" : "Upload Resume"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            {!uploadedCandidate ? (
              <>
                {uploadError && <Alert severity="error">{uploadError}</Alert>}
                <Stack direction="row" spacing={2} alignItems="center">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.docx"
                    onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
                  />
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  PDF or DOCX only. Creates a candidate with source "Manual" -- link them to a job next.
                </Typography>
              </>
            ) : (
              <>
                {linkError && <Alert severity="error">{linkError}</Alert>}
                <Alert severity="success">Resume uploaded. Link this candidate to a job to add them to the pipeline.</Alert>
                <TextField select label="Job" required value={linkJobId} onChange={(e) => setLinkJobId(e.target.value)} fullWidth>
                  {jobs.length === 0 && <MenuItem disabled value="">No jobs available</MenuItem>}
                  {jobs.map((job) => (
                    <MenuItem key={job.id} value={job.id}>
                      {job.title}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  label="Expected salary (optional)"
                  type="number"
                  value={linkExpectedSalary}
                  onChange={(e) => setLinkExpectedSalary(e.target.value)}
                  fullWidth
                />
              </>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setUploadDialogOpen(false)}>{uploadedCandidate ? "Skip for now" : "Cancel"}</Button>
          {!uploadedCandidate ? (
            <Button variant="contained" onClick={handleUpload} disabled={uploading}>
              {uploading ? "Uploading..." : "Upload"}
            </Button>
          ) : (
            <Button variant="contained" onClick={handleLink} disabled={linking}>
              {linking ? "Linking..." : "Link to Job"}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  );
}
