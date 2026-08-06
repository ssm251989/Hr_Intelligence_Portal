import { useMemo, useState } from "react";
import FilterListIcon from "@mui/icons-material/FilterList";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Popover from "@mui/material/Popover";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import type { JobRoleRead } from "../api/types";

export interface JobFilters {
  status: string;
  department: string;
  location: string;
  dateFrom: string;
  dateTo: string;
}

export const EMPTY_JOB_FILTERS: JobFilters = {
  status: "",
  department: "",
  location: "",
  dateFrom: "",
  dateTo: "",
};

export function applyJobFilters(jobs: JobRoleRead[], filters: JobFilters): JobRoleRead[] {
  return jobs.filter((job) => {
    if (filters.status && job.status !== filters.status) return false;
    if (filters.department && job.department !== filters.department) return false;
    if (filters.location && job.location !== filters.location) return false;
    const createdAt = job.created_at.slice(0, 10);
    if (filters.dateFrom && createdAt < filters.dateFrom) return false;
    if (filters.dateTo && createdAt > filters.dateTo) return false;
    return true;
  });
}

function distinctSorted(values: (string | null | undefined)[]): string[] {
  return Array.from(new Set(values.filter((v): v is string => Boolean(v)))).sort();
}

export default function JobFiltersPanel({
  jobs,
  filters,
  onChange,
}: {
  jobs: JobRoleRead[];
  filters: JobFilters;
  onChange: (filters: JobFilters) => void;
}) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);

  const statuses = useMemo(() => distinctSorted(jobs.map((j) => j.status)), [jobs]);
  const departments = useMemo(() => distinctSorted(jobs.map((j) => j.department)), [jobs]);
  const locations = useMemo(() => distinctSorted(jobs.map((j) => j.location)), [jobs]);

  const activeCount = Object.values(filters).filter(Boolean).length;

  const set = (key: keyof JobFilters, value: string) => onChange({ ...filters, [key]: value });

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
          <Typography variant="subtitle2">Filter jobs</Typography>
          <TextField select label="Status" size="small" value={filters.status} onChange={(e) => set("status", e.target.value)}>
            <MenuItem value="">All</MenuItem>
            {statuses.map((status) => (
              <MenuItem key={status} value={status}>
                {status}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Department"
            size="small"
            value={filters.department}
            onChange={(e) => set("department", e.target.value)}
          >
            <MenuItem value="">All</MenuItem>
            {departments.map((dept) => (
              <MenuItem key={dept} value={dept}>
                {dept}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Location"
            size="small"
            value={filters.location}
            onChange={(e) => set("location", e.target.value)}
          >
            <MenuItem value="">All</MenuItem>
            {locations.map((loc) => (
              <MenuItem key={loc} value={loc}>
                {loc}
              </MenuItem>
            ))}
          </TextField>
          <Stack direction="row" spacing={1}>
            <TextField
              label="Created from"
              type="date"
              size="small"
              value={filters.dateFrom}
              onChange={(e) => set("dateFrom", e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <TextField
              label="Created to"
              type="date"
              size="small"
              value={filters.dateTo}
              onChange={(e) => set("dateTo", e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
          </Stack>
          <Button size="small" onClick={() => onChange(EMPTY_JOB_FILTERS)} disabled={activeCount === 0}>
            Clear filters
          </Button>
        </Stack>
      </Popover>
    </>
  );
}
