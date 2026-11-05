import RestartAltIcon from "@mui/icons-material/RestartAlt";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { INTERVIEW_STATUSES, type JobRoleRead, type UserRead } from "../api/types";
import { useT } from "../i18n";

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
// Interview List's own dimensions (Interviewer, how it was booked). `hideDates` is used by
// the week calendar, whose own prev/next buttons decide the dates.
export default function InterviewFiltersPanel({
  jobs,
  interviewers,
  filters,
  onChange,
  hideDates = false,
}: {
  jobs: JobRoleRead[];
  interviewers: UserRead[];
  filters: InterviewFilters;
  onChange: (filters: InterviewFilters) => void;
  hideDates?: boolean;
}) {
  const t = useT();
  const activeCount = Object.values(filters).filter(Boolean).length;
  const set = (key: keyof InterviewFilters, value: string) => onChange({ ...filters, [key]: value });

  return (
    <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap alignItems="center">
      <TextField select label={t("interviews.filter.job")} size="small" value={filters.jobRoleId} onChange={(e) => set("jobRoleId", e.target.value)} sx={{ minWidth: 160 }}>
        <MenuItem value="">{t("interviews.filter.all_jobs")}</MenuItem>
        {jobs.map((job) => (
          <MenuItem key={job.id} value={job.id}>
            {job.title}
          </MenuItem>
        ))}
      </TextField>

      <TextField select label={t("interviews.filter.interviewer")} size="small" value={filters.interviewerId} onChange={(e) => set("interviewerId", e.target.value)} sx={{ minWidth: 160 }}>
        <MenuItem value="">{t("interviews.filter.all_interviewers")}</MenuItem>
        {interviewers.map((interviewer) => (
          <MenuItem key={interviewer.id} value={interviewer.id}>
            {interviewer.full_name || interviewer.email}
          </MenuItem>
        ))}
      </TextField>

      <TextField select label={t("interviews.filter.status")} size="small" value={filters.status} onChange={(e) => set("status", e.target.value)} sx={{ minWidth: 150 }}>
        <MenuItem value="">{t("interviews.filter.all_statuses")}</MenuItem>
        {INTERVIEW_STATUSES.map((status) => (
          <MenuItem key={status} value={status}>
            {t(`interviews.status.${status}`)}
          </MenuItem>
        ))}
      </TextField>

      <TextField select label={t("interviews.filter.method")} size="small" value={filters.schedulingMethod} onChange={(e) => set("schedulingMethod", e.target.value)} sx={{ minWidth: 170 }}>
        <MenuItem value="">{t("interviews.filter.all_methods")}</MenuItem>
        <MenuItem value="manual">{t("interviews.method.manual")}</MenuItem>
        <MenuItem value="auto">{t("interviews.method.auto")}</MenuItem>
      </TextField>

      {!hideDates && (
        <Stack direction="row" spacing={0.5} alignItems="center">
          <TextField
            label={t("interviews.filter.from")}
            type="date"
            size="small"
            value={filters.scheduledAfter}
            onChange={(e) => set("scheduledAfter", e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
            sx={{ width: 160 }}
          />
          <TextField
            label={t("interviews.filter.to")}
            type="date"
            size="small"
            value={filters.scheduledBefore}
            onChange={(e) => set("scheduledBefore", e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
            sx={{ width: 160 }}
          />
        </Stack>
      )}

      <Button size="small" startIcon={<RestartAltIcon fontSize="small" />} onClick={() => onChange(EMPTY_INTERVIEW_FILTERS)} disabled={activeCount === 0}>
        {activeCount > 0 ? t("interviews.filter.reset_count", { count: activeCount }) : t("interviews.filter.reset")}
      </Button>
    </Stack>
  );
}
