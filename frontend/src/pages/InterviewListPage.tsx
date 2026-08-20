import { useEffect, useState } from "react";
import AddOutlinedIcon from "@mui/icons-material/AddOutlined";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import EditNoteOutlinedIcon from "@mui/icons-material/EditNoteOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import FormControl from "@mui/material/FormControl";
import IconButton from "@mui/material/IconButton";
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
import Typography from "@mui/material/Typography";
import { useNavigate } from "react-router-dom";

import { extractErrorMessage, jobsApi, schedulingApi, usersApi } from "../api/client";
import type { InterviewListRow, InterviewStatus, JobRoleRead, SchedulingMethod, UserRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import InterviewFeedbackDialog from "../components/InterviewFeedbackDialog";
import InterviewFiltersPanel, { EMPTY_INTERVIEW_FILTERS, type InterviewFilters } from "../components/InterviewFiltersPanel";
import { InterviewStatusChip, SchedulingMethodChip } from "../components/InterviewChips";
import InterviewPrepQuestionsDialog from "../components/InterviewPrepQuestionsDialog";
import ScheduleInterviewDialog from "../components/ScheduleInterviewDialog";

const ROWS_PER_PAGE_OPTIONS = [10, 20, 30, 40, 50];
const DEFAULT_PAGE_SIZE = 10;
const COLUMN_COUNT = 6;

function InterviewActionsMenu({
  row,
  canWrite,
  onView,
  onRecordFeedback,
  onPrepQuestions,
}: {
  row: InterviewListRow;
  canWrite: boolean;
  onView: (applicationId: string) => void;
  onRecordFeedback: (row: InterviewListRow) => void;
  onPrepQuestions: (row: InterviewListRow) => void;
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
        {canWrite && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              onRecordFeedback(row);
            }}
          >
            <EditNoteOutlinedIcon fontSize="small" sx={{ mr: 1 }} />
            Record Feedback
          </MenuItem>
        )}
        {canWrite && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              onPrepQuestions(row);
            }}
          >
            <AutoAwesomeOutlinedIcon fontSize="small" sx={{ mr: 1 }} />
            Generate Prep Questions
          </MenuItem>
        )}
      </Menu>
    </>
  );
}

// The Interviews module redesign's List page -- same filterable/paginated architecture as
// the Candidates/Screening/Shortlisting Lists, scoped to the `interviews` table across
// every job (see backend app/scheduling/router.py list_all_interviews). Reschedule/Cancel
// aren't in the row menu: neither capability exists as a backend endpoint today, and this
// redesign reuses existing endpoints rather than inventing new pipeline-mutating logic.
export default function InterviewListPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.interviewsWrite);

  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [interviewers, setInterviewers] = useState<UserRead[]>([]);
  const [rows, setRows] = useState<InterviewListRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [filters, setFilters] = useState<InterviewFilters>(EMPTY_INTERVIEW_FILTERS);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const anyFilterActive = Object.values(filters).some(Boolean);

  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [feedbackRow, setFeedbackRow] = useState<InterviewListRow | null>(null);
  const [prepQuestionsRow, setPrepQuestionsRow] = useState<InterviewListRow | null>(null);

  useEffect(() => {
    jobsApi.list().then(setJobs).catch(() => setJobs([]));
    usersApi.list("interviewer").then(setInterviewers).catch(() => setInterviewers([]));
  }, []);

  useEffect(() => {
    setPage(1);
  }, [filters]);

  const loadPage = () => {
    setLoading(true);
    setError(null);
    schedulingApi
      .listAll({
        page,
        pageSize,
        jobRoleId: filters.jobRoleId || undefined,
        interviewerId: filters.interviewerId || undefined,
        status: (filters.status || undefined) as InterviewStatus | undefined,
        schedulingMethod: (filters.schedulingMethod || undefined) as SchedulingMethod | undefined,
        scheduledAfter: filters.scheduledAfter || undefined,
        scheduledBefore: filters.scheduledBefore || undefined,
      })
      .then((result) => {
        setRows(result.items);
        setTotal(result.total);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load interviews")))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, filters]);

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pageStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = Math.min(page * pageSize, total);

  const handlePageSizeChange = (event: SelectChangeEvent<number>) => {
    setPageSize(Number(event.target.value));
    setPage(1);
  };

  const rowLabel = (row: InterviewListRow) => row.candidate_name || "Unnamed candidate";

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">Interview List</Typography>
          <Typography variant="body2" color="text.secondary">
            {total} interview{total === 1 ? "" : "s"}
          </Typography>
        </Box>
        {canWrite && (
          <Button variant="contained" startIcon={<AddOutlinedIcon />} onClick={() => setScheduleOpen(true)}>
            Schedule Interview
          </Button>
        )}
      </Stack>

      <Box mb={3}>
        <InterviewFiltersPanel jobs={jobs} interviewers={interviewers} filters={filters} onChange={setFilters} />
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
                <TableCell>Candidate</TableCell>
                <TableCell>Job</TableCell>
                <TableCell>Interviewer</TableCell>
                <TableCell>Scheduled Time</TableCell>
                <TableCell>Method</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: COLUMN_COUNT + 1 }).map((__, j) => (
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
          {total === 0 && !anyFilterActive ? "No interviews scheduled yet." : "No interviews match the current filters."}
        </Typography>
      ) : (
        <>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Candidate</TableCell>
                  <TableCell>Job</TableCell>
                  <TableCell>Interviewer</TableCell>
                  <TableCell>Scheduled Time</TableCell>
                  <TableCell>Method</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.interview_id} hover>
                    <TableCell>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography variant="body2" fontWeight={600} noWrap>
                          {rowLabel(row)}
                        </Typography>
                        {row.candidate_email && (
                          <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
                            {row.candidate_email}
                          </Typography>
                        )}
                      </Box>
                    </TableCell>
                    <TableCell>{row.job_title}</TableCell>
                    <TableCell>{row.interviewer_name || "Unassigned"}</TableCell>
                    <TableCell>{row.scheduled_at ? new Date(row.scheduled_at).toLocaleString() : "—"}</TableCell>
                    <TableCell>
                      <SchedulingMethodChip method={row.scheduling_method} />
                    </TableCell>
                    <TableCell>
                      <InterviewStatusChip status={row.status} />
                    </TableCell>
                    <TableCell align="right">
                      <InterviewActionsMenu
                        row={row}
                        canWrite={canWrite}
                        onView={(applicationId) => navigate(`/candidates/${applicationId}`)}
                        onRecordFeedback={setFeedbackRow}
                        onPrepQuestions={setPrepQuestionsRow}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
            <Typography variant="body2" color="text.secondary">
              Showing {pageStart} to {pageEnd} of {total} interviews
            </Typography>
            <Stack direction="row" spacing={2} alignItems="center">
              <FormControl size="small" sx={{ minWidth: 130 }}>
                <InputLabel id="interviews-rows-per-page-label">Rows per page</InputLabel>
                <Select
                  labelId="interviews-rows-per-page-label"
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

      <ScheduleInterviewDialog
        open={scheduleOpen}
        onClose={() => setScheduleOpen(false)}
        onScheduled={() => {
          setScheduleOpen(false);
          loadPage();
        }}
      />

      <InterviewFeedbackDialog
        interviewId={feedbackRow?.interview_id ?? null}
        candidateLabel={feedbackRow ? rowLabel(feedbackRow) : ""}
        onClose={() => setFeedbackRow(null)}
        onSaved={() => {
          setFeedbackRow(null);
          loadPage();
        }}
      />

      <InterviewPrepQuestionsDialog
        applicationId={prepQuestionsRow?.application_id ?? null}
        candidateLabel={prepQuestionsRow ? rowLabel(prepQuestionsRow) : ""}
        onClose={() => setPrepQuestionsRow(null)}
      />
    </Box>
  );
}
