// Part 17.12: /interviews/interviewers (HR) -- everyone's interview availability and the
// interviewer pools (per job or per skill) that interview scheduling picks from. The app is
// the only source: no Excel tracker.
import { useCallback, useEffect, useState } from "react";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useSearchParams } from "react-router-dom";

import { jobsApi } from "../../api/client";
import { DAY_KEYS, interviewersApi, type Availability, type Pool, type PoolIn } from "../../api/interviewersApi";
import type { JobRoleRead } from "../../api/types";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import AvailabilityEditor from "../../components/interviews/AvailabilityEditor";
import { useToast } from "../../components/servicedesk/shared";
import { useT } from "../../i18n";
import { EmptyState, Emoji, FriendlyError, PageHeader, StatusChip } from "../../ui-kit";

function hoursSummary(a: Availability, t: ReturnType<typeof useT>): string {
  if (!a.has_availability) return t("interviewers.hr.not_set");
  const parts = DAY_KEYS.map((d) => {
    const v = a.weekly_pattern[d];
    if (v === false) return null;
    const r = Array.isArray(v) && v.length ? v.map((x) => `${x.start}-${x.end}`).join(", ") : t("interviewers.hr.all_day");
    return `${t(`interviewers.dayshort.${d}`)} ${r}`;
  }).filter(Boolean);
  return parts.join(" · ") || t("interviewers.hr.no_days");
}

function PoolDialog({ pool, jobs, people, onClose, onSaved }: { pool: Pool | "new" | null; jobs: JobRoleRead[]; people: string[]; onClose: () => void; onSaved: () => void }) {
  const t = useT();
  const [form, setForm] = useState<PoolIn>({ name: "", job_role_id: null, skills: [], member_emails: [], active: true });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (pool === null) return;
    setError(null);
    setForm(pool === "new" ? { name: "", job_role_id: null, skills: [], member_emails: [], active: true }
      : { name: pool.name, job_role_id: pool.job_role_id, skills: pool.skills, member_emails: pool.member_emails, active: pool.active });
  }, [pool]);
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      if (pool === "new") await interviewersApi.createPool(form);
      else if (pool) await interviewersApi.updatePool(pool.id, form);
      onSaved();
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open={pool !== null} onClose={saving ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>{pool === "new" ? t("interviewers.pool.new") : t("interviewers.pool.edit")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField required autoFocus label={t("interviewers.pool.name")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={t("interviewers.pool.name_ph")} />
          <TextField select label={t("interviewers.pool.job")} value={form.job_role_id ?? ""} onChange={(e) => setForm({ ...form, job_role_id: e.target.value || null })} helperText={t("interviewers.pool.job_hint")}>
            <MenuItem value="">{t("interviewers.pool.any_job")}</MenuItem>
            {jobs.map((j) => <MenuItem key={j.id} value={j.id}>{j.title}</MenuItem>)}
          </TextField>
          <Autocomplete multiple freeSolo options={[]} value={form.skills} onChange={(_e, v) => setForm({ ...form, skills: v as string[] })}
            renderInput={(p) => <TextField {...p} label={t("interviewers.pool.skills")} helperText={t("interviewers.pool.skills_hint")} />} />
          <Autocomplete multiple freeSolo options={people} value={form.member_emails} onChange={(_e, v) => setForm({ ...form, member_emails: (v as string[]).map((x) => x.trim().toLowerCase()) })}
            renderInput={(p) => <TextField {...p} label={t("interviewers.pool.members")} helperText={t("interviewers.pool.members_hint")} />} />
          <FormControlLabel control={<Switch checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />} label={t("interviewers.pool.active")} />
          {error ? <FriendlyError error={error} compact /> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={saving || !form.name.trim()}>{saving ? t("interviewers.saving") : t("interviewers.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function InterviewersPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { can } = useMeBootstrap();
  const canEdit = can("recruitment.interview.edit");
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "pools" ? "pools" : "people";
  const [people, setPeople] = useState<{ items: Availability[]; slot_times_tomorrow: string[] } | null>(null);
  const [pools, setPools] = useState<Pool[] | null>(null);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState<Availability | null>(null);
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState<unknown>(null);
  const [poolOpen, setPoolOpen] = useState<Pool | "new" | null>(null);
  const [toast, show] = useToast();

  const load = useCallback(() => {
    setError(null);
    Promise.all([interviewersApi.all(), interviewersApi.pools()]).then(([a, p]) => { setPeople(a); setPools(p); }).catch(setError);
  }, []);
  useEffect(() => { load(); jobsApi.list().then(setJobs).catch(() => setJobs([])); }, [load]);

  const removePool = async (p: Pool) => {
    if (!window.confirm(t("interviewers.pool.remove_confirm", { name: p.name }))) return;
    try {
      await interviewersApi.deletePool(p.id);
      show(t("interviewers.pool.removed"));
      load();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <Box>
      <PageHeader emoji="people" title={t("interviewers.hr.title")} purpose={t("interviewers.hr.purpose")}
        primary={canEdit && tab === "pools" ? <Button variant="contained" onClick={() => setPoolOpen("new")}>{t("interviewers.pool.new")}</Button> : undefined} />
      <Tabs value={tab} onChange={(_e, v) => setParams(v === "pools" ? { tab: "pools" } : {}, { replace: true })} sx={{ mb: 2 }}>
        <Tab value="people" label={t("interviewers.hr.tab_people")} />
        <Tab value="pools" label={t("interviewers.hr.tab_pools")} />
      </Tabs>
      {error ? <FriendlyError error={error} onRetry={load} /> : !people || !pools ? <CircularProgress aria-label={t("interviewers.loading")} /> : tab === "people" ? (
        people.items.length === 0 ? <EmptyState illustration="empty" title={t("interviewers.hr.empty")} hint={t("interviewers.hr.empty_hint")} /> : (
          <Box sx={{ overflowX: "auto" }}>
            <Typography sx={{ fontSize: 13, color: f.muted, mb: 1 }}>{t("interviewers.hr.slots_tomorrow", { list: people.slot_times_tomorrow.join(", ") })}</Typography>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t("interviewers.hr.col.person")}</TableCell>
                  <TableCell>{t("interviewers.hr.col.hours")}</TableCell>
                  <TableCell>{t("interviewers.hr.col.blocked")}</TableCell>
                  <TableCell>{t("interviewers.hr.col.booked")}</TableCell>
                  <TableCell>{t("interviewers.hr.col.free")}</TableCell>
                  <TableCell>{t("interviewers.hr.col.pools")}</TableCell>
                  {canEdit && <TableCell />}
                </TableRow>
              </TableHead>
              <TableBody>
                {people.items.map((a) => (
                  <TableRow key={a.email} hover>
                    <TableCell><Typography sx={{ fontWeight: 700, fontSize: 14 }}>{a.name}</Typography><Typography sx={{ fontSize: 12, color: f.muted }}>{a.email}</Typography></TableCell>
                    <TableCell sx={{ fontSize: 13, maxWidth: 320 }}>{hoursSummary(a, t)}{a.max_interviews_per_day ? ` · ${t("interviewers.hr.max_day", { count: a.max_interviews_per_day })}` : ""}</TableCell>
                    <TableCell sx={{ fontSize: 13 }}>{a.exceptions.map((e) => e.date).join(", ") || "—"}</TableCell>
                    <TableCell>{a.booked_next_7_days}</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                        {a.free_tomorrow.length ? a.free_tomorrow.map((s) => <Chip key={s} size="small" color="success" variant="outlined" label={s} />) : <StatusChip tone="muted" emoji="pause" label={t("interviewers.none_free")} />}
                      </Stack>
                    </TableCell>
                    <TableCell sx={{ fontSize: 13 }}>{a.pools.join(", ") || "—"}</TableCell>
                    {canEdit && <TableCell><Button size="small" onClick={() => { setEditError(null); setEditing(a); }}>{t("interviewers.hr.edit")}</Button></TableCell>}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )
      ) : pools.length === 0 ? (
        <EmptyState illustration="empty" title={t("interviewers.pool.empty")} hint={t("interviewers.pool.empty_hint")}
          action={canEdit ? <Button variant="contained" onClick={() => setPoolOpen("new")}>{t("interviewers.pool.new")}</Button> : undefined} />
      ) : (
        <Stack spacing={1} component="ul" sx={{ listStyle: "none", p: 0, m: 0 }}>
          {pools.map((p) => (
            <Box component="li" key={p.id} sx={{ border: `1px solid ${f.line}`, borderRadius: "12px", p: 1.5, bgcolor: p.active ? f.surface : f.surface2 }}>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
                <Box sx={{ flex: 1 }}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography sx={{ fontWeight: 800 }}>{p.name}</Typography>
                    {!p.active && <StatusChip tone="muted" emoji="pause" label={t("interviewers.pool.inactive")} />}
                    {p.source === "excel_import" && <StatusChip tone="sky" emoji="page" label={t("interviewers.pool.from_excel")} />}
                  </Stack>
                  <Typography sx={{ fontSize: 13, color: f.muted }}>
                    {p.job_title ? t("interviewers.pool.for_job", { job: p.job_title }) : t("interviewers.pool.for_skills", { list: p.skills.join(", ") || t("interviewers.pool.any_job") })}
                  </Typography>
                  <Typography sx={{ fontSize: 13 }}>{t("interviewers.pool.members_list", { count: p.member_emails.length, list: p.member_emails.join(", ") })}</Typography>
                </Box>
                {canEdit && (
                  <Stack direction="row" spacing={1}>
                    <Button size="small" onClick={() => setPoolOpen(p)}>{t("interviewers.hr.edit")}</Button>
                    <Button size="small" color="error" onClick={() => removePool(p)} startIcon={<Emoji name="cross" size={12} />}>{t("interviewers.pool.remove")}</Button>
                  </Stack>
                )}
              </Stack>
            </Box>
          ))}
        </Stack>
      )}

      <Dialog open={Boolean(editing)} onClose={editSaving ? undefined : () => setEditing(null)} fullWidth maxWidth="md">
        <DialogTitle>{t("interviewers.hr.edit_title", { name: editing?.name ?? "" })}</DialogTitle>
        <DialogContent>
          {editing && <AvailabilityEditor initial={editing} saving={editSaving} error={editError}
            onSave={async (payload) => {
              setEditSaving(true);
              setEditError(null);
              try {
                await interviewersApi.saveFor(editing.email, { ...payload, interviewer_name: editing.name });
                setEditing(null);
                show(t("interviewers.hr.saved"));
                load();
              } catch (e) {
                setEditError(e);
              } finally {
                setEditSaving(false);
              }
            }} />}
        </DialogContent>
        <DialogActions><Button onClick={() => setEditing(null)} disabled={editSaving}>{t("action.cancel")}</Button></DialogActions>
      </Dialog>
      <PoolDialog pool={poolOpen} jobs={jobs} people={people?.items.map((a) => a.email) ?? []} onClose={() => setPoolOpen(null)}
        onSaved={() => { setPoolOpen(null); show(t("interviewers.pool.saved")); load(); }} />
      {toast}
    </Box>
  );
}
