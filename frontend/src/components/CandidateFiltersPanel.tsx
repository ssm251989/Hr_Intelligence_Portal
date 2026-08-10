import { useState } from "react";
import FilterListIcon from "@mui/icons-material/FilterList";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Popover from "@mui/material/Popover";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { APPLICATION_STATUSES, CANDIDATE_SOURCES, candidateSourceLabel, type JobRoleRead } from "../api/types";
import { statusLabel } from "./StatusChip";

export interface CandidateFilters {
  jobRoleId: string;
  status: string;
  source: string;
  location: string;
}

export const EMPTY_CANDIDATE_FILTERS: CandidateFilters = {
  jobRoleId: "",
  status: "",
  source: "",
  location: "",
};

export default function CandidateFiltersPanel({
  jobs,
  filters,
  onChange,
}: {
  jobs: JobRoleRead[];
  filters: CandidateFilters;
  onChange: (filters: CandidateFilters) => void;
}) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);

  const activeCount = Object.values(filters).filter(Boolean).length;
  const set = (key: keyof CandidateFilters, value: string) => onChange({ ...filters, [key]: value });

  return (
    <>
      <Button variant="outlined" startIcon={<FilterListIcon />} onClick={(e) => setAnchorEl(e.currentTarget)}>
        Filters{activeCount > 0 ? ` (${activeCount})` : ""}
      </Button>
      <Popover
        open={Boolean(anchorEl)}
        anchorEl={anchorEl}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
      >
        <Stack spacing={2} p={2} sx={{ width: 280 }}>
          <Typography variant="subtitle2">Filter candidates</Typography>
          <TextField select label="Job" size="small" value={filters.jobRoleId} onChange={(e) => set("jobRoleId", e.target.value)}>
            <MenuItem value="">All</MenuItem>
            {jobs.map((job) => (
              <MenuItem key={job.id} value={job.id}>
                {job.title}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label="Stage" size="small" value={filters.status} onChange={(e) => set("status", e.target.value)}>
            <MenuItem value="">All</MenuItem>
            {APPLICATION_STATUSES.map((status) => (
              <MenuItem key={status} value={status}>
                {statusLabel(status)}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label="Source" size="small" value={filters.source} onChange={(e) => set("source", e.target.value)}>
            <MenuItem value="">All</MenuItem>
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
          />
          <Button size="small" onClick={() => onChange(EMPTY_CANDIDATE_FILTERS)} disabled={activeCount === 0}>
            Reset
          </Button>
        </Stack>
      </Popover>
    </>
  );
}
