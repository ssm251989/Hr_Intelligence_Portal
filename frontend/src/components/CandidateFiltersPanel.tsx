import RestartAltIcon from "@mui/icons-material/RestartAlt";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { APPLICATION_STATUSES, CANDIDATE_SOURCES, candidateSourceLabel, type JobRoleRead } from "../api/types";
import { statusLabel } from "./StatusChip";

export interface CandidateFilters {
  jobRoleId: string;
  status: string;
  source: string;
  location: string;
  experienceMin: string;
  experienceMax: string;
  appliedAfter: string;
  appliedBefore: string;
  matchScoreMin: string;
  matchScoreMax: string;
}

export const EMPTY_CANDIDATE_FILTERS: CandidateFilters = {
  jobRoleId: "",
  status: "",
  source: "",
  location: "",
  experienceMin: "",
  experienceMax: "",
  appliedAfter: "",
  appliedBefore: "",
  matchScoreMin: "",
  matchScoreMax: "",
};

// Rendered directly above the Candidates List table as a row of separate controls --
// deliberately not a single "Filters" button hiding everything in a popover, since these
// are meant to be visible and adjustable at a glance while scanning the table.
export default function CandidateFiltersPanel({
  jobs,
  filters,
  onChange,
}: {
  jobs: JobRoleRead[];
  filters: CandidateFilters;
  onChange: (filters: CandidateFilters) => void;
}) {
  const activeCount = Object.values(filters).filter(Boolean).length;
  const set = (key: keyof CandidateFilters, value: string) => onChange({ ...filters, [key]: value });

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
        label="Status"
        size="small"
        value={filters.status}
        onChange={(e) => set("status", e.target.value)}
        sx={{ minWidth: 150 }}
      >
        <MenuItem value="">All statuses</MenuItem>
        {APPLICATION_STATUSES.map((status) => (
          <MenuItem key={status} value={status}>
            {statusLabel(status)}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        select
        label="Source"
        size="small"
        value={filters.source}
        onChange={(e) => set("source", e.target.value)}
        sx={{ minWidth: 140 }}
      >
        <MenuItem value="">All sources</MenuItem>
        {CANDIDATE_SOURCES.map((source) => (
          <MenuItem key={source} value={source}>
            {candidateSourceLabel(source)}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        label="Location"
        size="small"
        value={filters.location}
        onChange={(e) => set("location", e.target.value)}
        placeholder="e.g. Chennai"
        sx={{ minWidth: 130 }}
      />

      <Stack direction="row" spacing={0.5} alignItems="center">
        <TextField
          label="Exp min"
          type="number"
          size="small"
          value={filters.experienceMin}
          onChange={(e) => set("experienceMin", e.target.value)}
          slotProps={{ htmlInput: { min: 0, step: 0.5 } }}
          sx={{ width: 90 }}
        />
        <TextField
          label="Exp max"
          type="number"
          size="small"
          value={filters.experienceMax}
          onChange={(e) => set("experienceMax", e.target.value)}
          slotProps={{ htmlInput: { min: 0, step: 0.5 } }}
          sx={{ width: 90 }}
        />
      </Stack>

      <Stack direction="row" spacing={0.5} alignItems="center">
        <TextField
          label="Applied from"
          type="date"
          size="small"
          value={filters.appliedAfter}
          onChange={(e) => set("appliedAfter", e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }}
          sx={{ width: 160 }}
        />
        <TextField
          label="Applied to"
          type="date"
          size="small"
          value={filters.appliedBefore}
          onChange={(e) => set("appliedBefore", e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }}
          sx={{ width: 160 }}
        />
      </Stack>

      <Stack direction="row" spacing={0.5} alignItems="center">
        <TextField
          label="Match % min"
          type="number"
          size="small"
          value={filters.matchScoreMin}
          onChange={(e) => set("matchScoreMin", e.target.value)}
          slotProps={{ htmlInput: { min: 0, max: 100, step: 5 } }}
          sx={{ width: 100 }}
        />
        <TextField
          label="Match % max"
          type="number"
          size="small"
          value={filters.matchScoreMax}
          onChange={(e) => set("matchScoreMax", e.target.value)}
          slotProps={{ htmlInput: { min: 0, max: 100, step: 5 } }}
          sx={{ width: 100 }}
        />
      </Stack>

      <Button
        size="small"
        startIcon={<RestartAltIcon fontSize="small" />}
        onClick={() => onChange(EMPTY_CANDIDATE_FILTERS)}
        disabled={activeCount === 0}
      >
        Reset{activeCount > 0 ? ` (${activeCount})` : ""}
      </Button>
    </Stack>
  );
}
