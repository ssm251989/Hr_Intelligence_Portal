import { useMemo, useState } from "react";
import FilterListIcon from "@mui/icons-material/FilterList";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Popover from "@mui/material/Popover";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import type { JobRoleRead } from "../api/types";
import { useT } from "../i18n";
import { statusStyle } from "../ui-kit";

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
  const t = useT();
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);

  const statuses = useMemo(() => distinctSorted(jobs.map((j) => j.status)), [jobs]);
  const departments = useMemo(() => distinctSorted(jobs.map((j) => j.department)), [jobs]);
  const locations = useMemo(() => distinctSorted(jobs.map((j) => j.location)), [jobs]);

  const activeCount = Object.values(filters).filter(Boolean).length;

  const set = (key: keyof JobFilters, value: string) => onChange({ ...filters, [key]: value });
  const statusLabel = (status: string) => {
    const key = `status.${status}`;
    const translated = t(key);
    return translated !== key ? translated : statusStyle(status).label;
  };

  return (
    <>
      <Button variant="outlined" size="small" startIcon={<FilterListIcon />} onClick={(e) => setAnchorEl(e.currentTarget)} aria-haspopup="dialog">
        {activeCount > 0 ? t("jobs.flt.button_n", { count: activeCount }) : t("jobs.flt.button")}
      </Button>
      <Popover
        open={Boolean(anchorEl)}
        anchorEl={anchorEl}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
      >
        <Stack spacing={2} p={2.5} sx={{ width: 300 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{t("jobs.flt.title")}</Typography>
          <TextField select label={t("jobs.flt.status")} size="small" value={filters.status} onChange={(e) => set("status", e.target.value)}>
            <MenuItem value="">{t("jobs.flt.all")}</MenuItem>
            {statuses.map((status) => (
              <MenuItem key={status} value={status}>
                {statusLabel(status)}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label={t("jobs.flt.dept")} size="small" value={filters.department} onChange={(e) => set("department", e.target.value)}>
            <MenuItem value="">{t("jobs.flt.all")}</MenuItem>
            {departments.map((dept) => (
              <MenuItem key={dept} value={dept}>
                {dept}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label={t("jobs.flt.loc")} size="small" value={filters.location} onChange={(e) => set("location", e.target.value)}>
            <MenuItem value="">{t("jobs.flt.all")}</MenuItem>
            {locations.map((loc) => (
              <MenuItem key={loc} value={loc}>
                {loc}
              </MenuItem>
            ))}
          </TextField>
          <Stack direction="row" spacing={1}>
            <TextField label={t("jobs.flt.from")} type="date" size="small" value={filters.dateFrom} onChange={(e) => set("dateFrom", e.target.value)}
              slotProps={{ inputLabel: { shrink: true } }} fullWidth />
            <TextField label={t("jobs.flt.to")} type="date" size="small" value={filters.dateTo} onChange={(e) => set("dateTo", e.target.value)}
              slotProps={{ inputLabel: { shrink: true } }} fullWidth />
          </Stack>
          <Button size="small" onClick={() => onChange(EMPTY_JOB_FILTERS)} disabled={activeCount === 0}>
            {t("jobs.flt.clear")}
          </Button>
        </Stack>
      </Popover>
    </>
  );
}
