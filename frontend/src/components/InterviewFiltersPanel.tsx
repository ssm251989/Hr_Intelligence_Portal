import RestartAltIcon from "@mui/icons-material/RestartAlt";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { INTERVIEW_STATUSES, INTERVIEW_STATUS_LABELS, SCHEDULING_METHOD_LABELS, type JobRoleRead, type UserRead } from "../api/types";

export interface InterviewFilters {
  jobRoleId: string;
  interviewerId: string;
  status: string;
  schedulingMethod: string;
  scheduledAfter: string;
  scheduledBefore: string;
}

export const EMPTY_INTERVIEW_FILTERS: InterviewFilters = {
  jobRoleId: "",
  interviewerId: "",
  status: "",
  schedulingMethod: "",
  scheduledAfter: "",
  scheduledBefore: "",
};

// Same visible-at-a-glance row-of-controls layout as CandidateFiltersPanel, but with the
// Interview List's own dimensions (Interviewer, Scheduling Method) in place of
// Source/Location/Experience/Score, which don't apply to an interview-scoped table.
export default function InterviewFiltersPanel({
  jobs,
  interviewers,
  filters,
  onChange,
}: {
  jobs: JobRoleRead[];
  interviewers: UserRead[];
  filters: InterviewFilters;
  onChange: (filters: InterviewFilters) => void;
}) {
  const activeCount = Object.values(filters).filter(Boolean).length;
  const set = (key: keyof InterviewFilters, value: string) => onChange({ ...filters, [key]: value });

  return (
    <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap alignItems="center">
      <TextField
        select
        label="Job"
        size="small"
        value={filters.jobRoleId}
        onChange={(e) => set("jobRoleId", e.target.value)}
        sx={{ minWidth: 160 }}
      >
        <MenuItem value="">All jobs</MenuItem>
        {jobs.map((job) => (
          <MenuItem key={job.id} value={job.id}>
            {job.title}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        select
        label="Interviewer"
        size="small"
        value={filters.interviewerId}
        onChange={(e) => set("interviewerId", e.target.value)}
        sx={{ minWidth: 160 }}
      >
        <MenuItem value="">All interviewers</MenuItem>
        {interviewers.map((interviewer) => (
          <MenuItem key={interviewer.id} value={interviewer.id}>
            {interviewer.full_name || interviewer.email}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        select
        label="Status"
        size="small"
        value={filters.status}
        onChange={(e) => set("status", e.target.value)}
        sx={{ minWidth: 150 }}
      >
        <MenuItem value="">All statuses</MenuItem>
        {INTERVIEW_STATUSES.map((status) => (
          <MenuItem key={status} value={status}>
            {INTERVIEW_STATUS_LABELS[status]}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        select
        label="Scheduling Method"
        size="small"
        value={filters.schedulingMethod}
        onChange={(e) => set("schedulingMethod", e.target.value)}
        sx={{ minWidth: 170 }}
      >
        <MenuItem value="">All methods</MenuItem>
        <MenuItem value="manual">{SCHEDULING_METHOD_LABELS.manual}</MenuItem>
        <MenuItem value="auto">{SCHEDULING_METHOD_LABELS.auto}</MenuItem>
      </TextField>

      <Stack direction="row" spacing={0.5} alignItems="center">
        <TextField
          label="Scheduled from"
          type="date"
          size="small"
          value={filters.scheduledAfter}
          onChange={(e) => set("scheduledAfter", e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }}
          sx={{ width: 160 }}
        />
        <TextField
          label="Scheduled to"
          type="date"
          size="small"
          value={filters.scheduledBefore}
          onChange={(e) => set("scheduledBefore", e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }}
          sx={{ width: 160 }}
        />
      </Stack>

      <Button
        size="small"
        startIcon={<RestartAltIcon fontSize="small" />}
        onClick={() => onChange(EMPTY_INTERVIEW_FILTERS)}
        disabled={activeCount === 0}
      >
        Reset{activeCount > 0 ? ` (${activeCount})` : ""}
      </Button>
    </Stack>
  );
}
