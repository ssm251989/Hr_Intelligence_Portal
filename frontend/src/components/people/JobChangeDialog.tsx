import { useEffect, useMemo, useState } from "react";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { peopleApi, type JobInfo, type PeopleFilters, type PersonRow } from "../../api/peopleApi";
import { useT } from "../../i18n";
import { FriendlyError, InfoTip } from "../../ui-kit";

// E4: job details are never edited silently -- every change is a new dated job record through
// the existing lifecycle-events API. If the company has an approval step for that kind of change
// the server starts it and nothing changes until it's approved ("Waiting for approval" badge).

export const JOB_CHANGE_TYPES = ["transfer", "promotion", "redesignation", "manager_change", "confirmation", "probation_extension"] as const;
const WORK_MODES = ["onsite", "hybrid", "remote"];

export default function JobChangeDialog({
  open, employeeId, job, filters, people, onClose, onDone,
}: {
  open: boolean;
  employeeId: string;
  job: JobInfo | null;
  filters: PeopleFilters | null;
  people: PersonRow[];
  onClose: () => void;
  onDone: (applied: boolean) => void;
}) {
  const t = useT();
  const today = new Date().toISOString().slice(0, 10);
  const [type, setType] = useState<string>("transfer");
  const [effective, setEffective] = useState(today);
  const [designation, setDesignation] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [locationId, setLocationId] = useState("");
  const [managerId, setManagerId] = useState<string | null>(null);
  const [grade, setGrade] = useState("");
  const [workMode, setWorkMode] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!open) return;
    setType("transfer");
    setEffective(today);
    setDesignation(job?.designation ?? "");
    setDepartmentId(job?.department_id ?? "");
    setLocationId(job?.location_id ?? "");
    setManagerId(job?.manager_id ?? null);
    setGrade(job?.grade ?? "");
    setWorkMode(job?.work_mode ?? "");
    setReason("");
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const changes = useMemo(() => {
    const c: Record<string, unknown> = {};
    if (designation.trim() && designation.trim() !== (job?.designation ?? "")) c.designation = designation.trim();
    if (departmentId && departmentId !== (job?.department_id ?? "")) c.department_id = departmentId;
    if (locationId && locationId !== (job?.location_id ?? "")) c.location_id = locationId;
    if ((managerId ?? "") !== (job?.manager_id ?? "") && managerId) c.manager_employee_id = managerId;
    if (grade.trim() && grade.trim() !== (job?.grade ?? "")) c.grade = grade.trim();
    if (workMode && workMode !== (job?.work_mode ?? "")) c.work_mode = workMode;
    if (type === "confirmation") c.confirmation_date = effective;
    return c;
  }, [designation, departmentId, locationId, managerId, grade, workMode, type, effective, job]);

  const managerOptions = people.filter((p) => p.id !== employeeId);
  const manager = managerOptions.find((p) => p.id === managerId) ?? null;
  const nothing = Object.keys(changes).length === 0;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await peopleApi.requestJobChange(employeeId, { event_type: type, effective_from: effective, changes, reason: reason.trim() || undefined });
      onDone(res.applied);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>{t("people.jobchange.title")}</DialogTitle>
      <DialogContent>
        <Typography sx={{ mb: 2, fontSize: 14 }}>{t("people.jobchange.intro")}</Typography>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select fullWidth label={t("people.jobchange.type")} value={type} onChange={(e) => setType(e.target.value)} helperText={t("people.jobchange.type_hint")}>
              {JOB_CHANGE_TYPES.map((k) => <MenuItem key={k} value={k}>{t(`people.event.${k}`)}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField type="date" fullWidth label={t("people.jobchange.effective")} value={effective} onChange={(e) => setEffective(e.target.value)}
              helperText={t("people.jobchange.effective_hint")} slotProps={{ inputLabel: { shrink: true } }} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField fullWidth label={t("people.field.designation")} value={designation} onChange={(e) => setDesignation(e.target.value)}
              placeholder={t("people.jobchange.designation_placeholder")} helperText={t("people.jobchange.designation_hint")} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField fullWidth label={t("people.field.grade")} value={grade} onChange={(e) => setGrade(e.target.value)}
              placeholder={t("people.jobchange.grade_placeholder")} helperText={t("people.jobchange.grade_hint")}
              slotProps={{ input: { endAdornment: <InfoTip text={t("people.field.grade_tip")} /> } }} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select fullWidth label={t("people.field.department")} value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} helperText={t("people.jobchange.department_hint")}>
              <MenuItem value="">{t("people.jobchange.no_change")}</MenuItem>
              {(filters?.departments ?? []).map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select fullWidth label={t("people.field.location")} value={locationId} onChange={(e) => setLocationId(e.target.value)} helperText={t("people.jobchange.location_hint")}>
              <MenuItem value="">{t("people.jobchange.no_change")}</MenuItem>
              {(filters?.locations ?? []).map((l) => <MenuItem key={l.id} value={l.id}>{l.name}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <Autocomplete
              options={managerOptions}
              value={manager}
              onChange={(_e, v) => setManagerId(v?.id ?? null)}
              getOptionLabel={(o) => (o.designation ? `${o.name} · ${o.designation}` : o.name)}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              renderInput={(params) => <TextField {...params} label={t("people.field.manager")} placeholder={t("people.jobchange.manager_placeholder")} helperText={t("people.jobchange.manager_hint")} />}
            />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select fullWidth label={t("people.field.work_mode")} value={workMode} onChange={(e) => setWorkMode(e.target.value)} helperText={t("people.jobchange.work_mode_hint")}>
              <MenuItem value="">{t("people.jobchange.no_change")}</MenuItem>
              {WORK_MODES.map((m) => <MenuItem key={m} value={m}>{t(`people.work_mode.${m}`)}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid size={12}>
            <TextField fullWidth multiline minRows={2} label={t("people.jobchange.reason")} value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder={t("people.jobchange.reason_placeholder")} helperText={t("people.jobchange.reason_hint")} />
          </Grid>
        </Grid>
        {error != null && <Box sx={{ mt: 2 }}><FriendlyError compact error={error} what={t("people.jobchange.failed")} /></Box>}
      </DialogContent>
      <DialogActions>
        {nothing && <Typography sx={{ mr: "auto", ml: 2, fontSize: 13 }}>{t("people.jobchange.nothing")}</Typography>}
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={submit} disabled={busy || nothing || !effective}>{busy ? t("people.saving") : t("people.jobchange.submit")}</Button>
      </DialogActions>
    </Dialog>
  );
}
