// Part 15.6 -- /agencies (HR): the recruitment agencies the company works with. Add an
// agency, pick which jobs it may send candidates for, invite its people (they get a
// set-password link and see ONLY the agency portal), pause it, and see who it sent.
import { useCallback, useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { agencyApi, type AgencyDetail, type AgencyRow, type InviteResult } from "../../api/agencyApi";
import { jobsApi } from "../../api/client";
import type { JobRoleRead } from "../../api/types";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { Section, useDateFmt, useToast } from "../../components/servicedesk/shared";
import { useT } from "../../i18n";
import { Cell, EmptyState, Emoji, FriendlyError, PageGrid, PageHeader, StatusChip } from "../../ui-kit";

function AddAgencyDialog({ open, onClose, onAdded }: { open: boolean; onClose: () => void; onAdded: (a: AgencyRow) => void }) {
  const t = useT();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (open) { setName(""); setEmail(""); setNotes(""); setError(null); }
  }, [open]);
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      onAdded(await agencyApi.create({ name: name.trim(), contact_email: email.trim() || undefined, notes: notes.trim() || undefined }));
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open={open} onClose={saving ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("agencies.add.title")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField required autoFocus label={t("agencies.field.name")} placeholder={t("agencies.field.name_ph")} value={name} onChange={(e) => setName(e.target.value)} inputProps={{ maxLength: 255 }} />
          <TextField type="email" label={t("agencies.field.contact")} helperText={t("agencies.field.contact_hint")} value={email} onChange={(e) => setEmail(e.target.value)} />
          <TextField label={t("agencies.field.notes")} helperText={t("agencies.field.notes_hint")} value={notes} onChange={(e) => setNotes(e.target.value)} multiline minRows={2} />
          {error ? <FriendlyError error={error} compact /> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>{t("agency.common.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={saving || !name.trim()}>{saving ? t("agencies.saving") : t("agencies.add.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}

function JobsDialog({ agency, onClose, onSaved }: { agency: AgencyDetail | null; onClose: () => void; onSaved: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [jobs, setJobs] = useState<JobRoleRead[] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [q, setQ] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (!agency) return;
    setPicked(new Set(agency.job_list.map((j) => j.id)));
    setQ("");
    setError(null);
    jobsApi.list().then(setJobs).catch(setError);
  }, [agency]);
  // Published jobs first; already-assigned ones stay visible even if they have closed.
  const shown = useMemo(() => (jobs ?? [])
    .filter((j) => j.status === "published" || picked.has(j.id))
    .filter((j) => !q.trim() || `${j.title} ${j.location ?? ""}`.toLowerCase().includes(q.trim().toLowerCase())), [jobs, picked, q]);
  const toggle = (id: string) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const save = async () => {
    if (!agency) return;
    setSaving(true);
    setError(null);
    try {
      await agencyApi.setJobs(agency.id, [...picked]);
      onSaved();
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open={Boolean(agency)} onClose={saving ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("agencies.jobs.title", { agency: agency?.name ?? "" })}</DialogTitle>
      <DialogContent>
        <Typography sx={{ fontSize: 14, color: f.muted, mb: 1.5 }}>{t("agencies.jobs.intro")}</Typography>
        <TextField size="small" fullWidth label={t("agencies.jobs.search")} value={q} onChange={(e) => setQ(e.target.value)} sx={{ mb: 1 }} />
        {jobs === null && !error ? <Box sx={{ display: "grid", placeItems: "center", py: 3 }}><CircularProgress aria-label={t("agency.common.loading")} /></Box> : null}
        {jobs !== null && shown.length === 0 ? <EmptyState compact illustration="empty" title={t("agencies.jobs.none")} /> : null}
        <Stack>
          {shown.map((j) => (
            <FormControlLabel key={j.id} control={<Checkbox checked={picked.has(j.id)} onChange={() => toggle(j.id)} />}
              label={<span>{j.title}<Typography component="span" sx={{ fontSize: 13, color: f.muted }}>{j.location ? ` · ${j.location}` : ""}{j.status !== "published" ? ` · ${t("agencies.jobs.closed")}` : ""}</Typography></span>} />
          ))}
        </Stack>
        {error ? <FriendlyError error={error} compact /> : null}
      </DialogContent>
      <DialogActions>
        <Typography sx={{ flex: 1, pl: 2, fontSize: 13, color: f.muted }}>{t("agencies.jobs.count", { count: picked.size })}</Typography>
        <Button onClick={onClose} disabled={saving}>{t("agency.common.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={saving}>{saving ? t("agencies.saving") : t("agencies.jobs.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}

function InviteDialog({ agency, onClose, onInvited }: { agency: AgencyDetail | null; onClose: () => void; onInvited: (r: InviteResult) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (agency) { setEmail(""); setName(""); setError(null); }
  }, [agency]);
  const ok = /^\S+@\S+\.\S+$/.test(email.trim());
  const save = async () => {
    if (!agency) return;
    setSaving(true);
    setError(null);
    try {
      onInvited(await agencyApi.invite(agency.id, { email: email.trim(), full_name: name.trim() || undefined }));
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open={Boolean(agency)} onClose={saving ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("agencies.invite.title", { agency: agency?.name ?? "" })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography sx={{ fontSize: 14, color: f.muted }}>{t("agencies.invite.intro")}</Typography>
          <TextField required autoFocus type="email" label={t("agencies.invite.email")} value={email} onChange={(e) => setEmail(e.target.value)} />
          <TextField label={t("agencies.invite.name")} value={name} onChange={(e) => setName(e.target.value)} />
          {error ? <FriendlyError error={error} compact /> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>{t("agency.common.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={saving || !ok} startIcon={<Emoji name="envelope" size={16} />}>{saving ? t("agencies.saving") : t("agencies.invite.send")}</Button>
      </DialogActions>
    </Dialog>
  );
}

function AgencyPanel({ id, canEdit, onChanged, onToast }: { id: string; canEdit: boolean; onChanged: () => void; onToast: (m: string, s?: "success" | "info" | "warning" | "error") => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const [data, setData] = useState<AgencyDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [jobsFor, setJobsFor] = useState<AgencyDetail | null>(null);
  const [inviteFor, setInviteFor] = useState<AgencyDetail | null>(null);
  const [link, setLink] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    agencyApi.detail(id).then(setData).catch(setError);
  }, [id]);
  useEffect(() => { setData(null); setLink(null); load(); }, [load]);
  const refresh = () => { load(); onChanged(); };

  const toggleActive = async () => {
    if (!data) return;
    try {
      await agencyApi.update(data.id, { active: !data.active });
      onToast(t(data.active ? "agencies.paused" : "agencies.resumed", { agency: data.name }));
      refresh();
    } catch (e) {
      setError(e);
    }
  };
  const remove = async (userId: string, who: string) => {
    if (!data || !window.confirm(t("agencies.members.remove_confirm", { name: who }))) return;
    try {
      await agencyApi.removeMember(data.id, userId);
      onToast(t("agencies.members.removed", { name: who }));
      refresh();
    } catch (e) {
      setError(e);
    }
  };

  if (error) return <FriendlyError error={error} onRetry={load} compact />;
  if (!data) return <Box sx={{ display: "grid", placeItems: "center", py: 4 }}><CircularProgress aria-label={t("agency.common.loading")} /></Box>;

  return (
    <Stack spacing={2.5}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography component="h3" sx={{ fontWeight: 800, fontSize: 18, flex: 1 }}>{data.name}</Typography>
        {canEdit && <FormControlLabel control={<Switch checked={data.active} onChange={toggleActive} />} label={t(data.active ? "agencies.active" : "agencies.inactive")} />}
      </Stack>
      {data.contact_email || data.notes ? (
        <Typography sx={{ fontSize: 14, color: f.muted, whiteSpace: "pre-wrap" }}>{[data.contact_email, data.notes].filter(Boolean).join("\n")}</Typography>
      ) : null}

      <Box>
        <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
          <Typography sx={{ fontWeight: 800, flex: 1 }}>{t("agencies.jobs.heading", { count: data.job_list.length })}</Typography>
          {canEdit && <Button size="small" onClick={() => setJobsFor(data)}>{t("agencies.jobs.choose")}</Button>}
        </Stack>
        {data.job_list.length === 0 ? <Typography sx={{ fontSize: 14, color: f.muted }}>{t("agencies.jobs.empty")}</Typography> : (
          <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
            {data.job_list.map((j) => <StatusChip key={j.id} tone={j.open ? "brand" : "muted"} emoji="briefcase" label={j.open ? j.title : t("agencies.jobs.closed_named", { job: j.title })} />)}
          </Stack>
        )}
      </Box>

      <Box>
        <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
          <Typography sx={{ fontWeight: 800, flex: 1 }}>{t("agencies.members.heading", { count: data.member_list.length })}</Typography>
          {canEdit && <Button size="small" onClick={() => setInviteFor(data)}>{t("agencies.members.invite")}</Button>}
        </Stack>
        {link ? (
          <Box sx={{ p: 1.5, mb: 1, borderRadius: "12px", bgcolor: f.sunSoft }} role="status">
            <Typography sx={{ fontSize: 14, fontWeight: 700 }}>{t("agencies.invite.no_mail")}</Typography>
            <Typography sx={{ fontSize: 13, wordBreak: "break-all" }}>{link}</Typography>
            <Button size="small" sx={{ mt: 0.5 }} onClick={() => navigator.clipboard?.writeText(link).then(() => onToast(t("agencies.invite.copied")))}>{t("agencies.invite.copy")}</Button>
          </Box>
        ) : null}
        {data.member_list.length === 0 ? <Typography sx={{ fontSize: 14, color: f.muted }}>{t("agencies.members.empty")}</Typography> : (
          <Stack spacing={0.5} component="ul" sx={{ listStyle: "none", p: 0, m: 0 }}>
            {data.member_list.map((m) => (
              <Stack component="li" key={m.user_id} direction="row" alignItems="center" spacing={1}>
                <Emoji name="people" size={16} />
                <Typography sx={{ flex: 1, fontSize: 14 }}>{m.full_name && m.full_name !== m.email ? `${m.full_name} · ${m.email}` : m.email}</Typography>
                {canEdit && <IconButton size="small" aria-label={t("agencies.members.remove", { name: m.email })} onClick={() => remove(m.user_id, m.full_name || m.email)}><Emoji name="cross" size={14} /></IconButton>}
              </Stack>
            ))}
          </Stack>
        )}
      </Box>

      <Box>
        <Typography sx={{ fontWeight: 800, mb: 1 }}>{t("agencies.sent.heading", { count: data.submission_list.length })}</Typography>
        {data.submission_list.length === 0 ? <Typography sx={{ fontSize: 14, color: f.muted }}>{t("agencies.sent.empty")}</Typography> : (
          <Stack spacing={0.75} component="ul" sx={{ listStyle: "none", p: 0, m: 0 }}>
            {data.submission_list.map((s) => (
              <Stack component="li" key={s.application_id} direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap>
                <ButtonBase component={RouterLink} to={`/candidates/${s.application_id}`} sx={{ borderRadius: 1, fontWeight: 700, fontSize: 14, textAlign: "left" }}>
                  {s.candidate_name || t("agencies.sent.unnamed")}
                </ButtonBase>
                <Typography sx={{ fontSize: 13, color: f.muted, flex: 1 }}>{s.job_title} · {fmt.date(s.submitted_at)}</Typography>
                <StatusChip status={s.status} />
              </Stack>
            ))}
          </Stack>
        )}
      </Box>

      <JobsDialog agency={jobsFor} onClose={() => setJobsFor(null)} onSaved={() => { setJobsFor(null); onToast(t("agencies.jobs.saved")); refresh(); }} />
      <InviteDialog agency={inviteFor} onClose={() => setInviteFor(null)}
        onInvited={(r) => { setInviteFor(null); setLink(r.link); onToast(r.email_sent ? t("agencies.invite.sent") : t("agencies.invite.no_mail"), r.email_sent ? "success" : "warning"); refresh(); }} />
    </Stack>
  );
}

export default function AgenciesPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { can } = useMeBootstrap();
  const canEdit = can("recruitment.agency.edit");
  const [rows, setRows] = useState<AgencyRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [toast, show] = useToast();

  const load = useCallback(() => {
    setError(null);
    agencyApi.list().then((list) => {
      setRows(list);
      setSelected((cur) => cur && list.some((a) => a.id === cur) ? cur : list[0]?.id ?? null);
    }).catch(setError);
  }, []);
  useEffect(load, [load]);

  return (
    <Box>
      <PageHeader emoji="handshake" title={t("agencies.title")} purpose={t("agencies.purpose")}
        primary={canEdit ? <Button variant="contained" onClick={() => setAdding(true)} startIcon={<Emoji name="handshake" size={16} />}>{t("agencies.add.button")}</Button> : undefined} />
      {error ? <FriendlyError error={error} onRetry={load} /> : rows === null ? (
        <Box sx={{ display: "grid", placeItems: "center", py: 6 }}><CircularProgress aria-label={t("agency.common.loading")} /></Box>
      ) : rows.length === 0 ? (
        <EmptyState illustration="empty" title={t("agencies.empty")} hint={t("agencies.empty_hint")}
          action={canEdit ? <Button variant="contained" onClick={() => setAdding(true)}>{t("agencies.add.button")}</Button> : undefined} />
      ) : (
        <PageGrid>
          <Cell span={{ md: 12, lg: 5 }}>
            <Section emoji="handshake" title={t("agencies.list.title")}>
              <Stack spacing={1} component="ul" sx={{ listStyle: "none", p: 0, m: 0 }}>
                {rows.map((a) => (
                  <Box component="li" key={a.id}>
                    <ButtonBase onClick={() => setSelected(a.id)} aria-pressed={a.id === selected}
                      sx={{ display: "block", width: "100%", textAlign: "left", p: 1.5, borderRadius: "12px",
                        border: `2px solid ${a.id === selected ? f.brand : f.line}`, bgcolor: a.id === selected ? f.brandSoft : f.surface2 }}>
                      <Typography sx={{ fontWeight: 700 }}>{a.name}</Typography>
                      <Stack direction="row" spacing={0.75} sx={{ mt: 0.75 }} flexWrap="wrap" useFlexGap>
                        {!a.active && <StatusChip tone="muted" emoji="pause" label={t("agencies.inactive")} />}
                        <StatusChip tone="brand" emoji="briefcase" label={t("agencies.chip.jobs", { count: a.jobs })} />
                        <StatusChip tone="sky" emoji="people" label={t("agencies.chip.members", { count: a.members })} />
                        <StatusChip tone={a.submissions ? "ok" : "muted"} emoji="technologist" label={t("agencies.chip.sent", { count: a.submissions })} />
                      </Stack>
                    </ButtonBase>
                  </Box>
                ))}
              </Stack>
            </Section>
          </Cell>
          <Cell span={{ md: 12, lg: 7 }}>
            <Section emoji="clipboard" title={t("agencies.detail.title")}>
              {selected ? <AgencyPanel id={selected} canEdit={canEdit} onChanged={load} onToast={show} /> : null}
            </Section>
          </Cell>
        </PageGrid>
      )}
      <AddAgencyDialog open={adding} onClose={() => setAdding(false)}
        onAdded={(a) => { setAdding(false); show(t("agencies.add.done", { agency: a.name })); setSelected(a.id); load(); }} />
      {toast}
    </Box>
  );
}
