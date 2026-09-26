// Part 15.6 -- /agency: what a recruitment agency's own user sees (and nothing else). Their
// assigned open jobs as cards with "Send a candidate", a short send form (name, email,
// phone, resume, consent confirmation), and the candidates they sent with a plain stage.
import { useCallback, useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { agencyPortalApi, type AgencyStage, type PortalJob, type PortalMe, type PortalSubmission } from "../../api/agencyApi";
import { Section, useDateFmt, useToast } from "../../components/servicedesk/shared";
import { useT } from "../../i18n";
import { Cell, EmptyState, Emoji, FriendlyError, PageGrid, PageHeader, StatusChip, type Tone } from "../../ui-kit";

const STAGE_LOOK: Record<AgencyStage, { tone: Tone; emoji: string }> = {
  received: { tone: "sky", emoji: "inbox" },
  shortlisted: { tone: "ok", emoji: "star" },
  interviewing: { tone: "sky", emoji: "calendar" },
  final_stages: { tone: "brand", emoji: "hourglass" },
  offer: { tone: "ok", emoji: "envelope" },
  hired: { tone: "ok", emoji: "party" },
  not_selected: { tone: "coral", emoji: "cross" },
  on_hold: { tone: "muted", emoji: "pause" },
};

export function AgencyStageChip({ stage }: { stage: AgencyStage }) {
  const t = useT();
  const look = STAGE_LOOK[stage] ?? STAGE_LOOK.received;
  return <StatusChip tone={look.tone} emoji={look.emoji} label={t(`agency.stage.${stage}`)} />;
}

function SendDialog({ job, onClose, onSent }: { job: PortalJob | null; onClose: () => void; onSent: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [resume, setResume] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!job) return;
    setName(""); setEmail(""); setPhone(""); setResume(null); setConsent(false); setError(null);
  }, [job]);

  const emailOk = /^\S+@\S+\.\S+$/.test(email.trim());
  const ready = Boolean(job && name.trim() && emailOk && resume && consent);

  const submit = async () => {
    if (!job || !resume || !ready) return;
    setSending(true);
    setError(null);
    try {
      await agencyPortalApi.submit({ jobId: job.id, fullName: name.trim(), email: email.trim(), phone: phone.trim() || undefined, consent, resume });
      onSent();
    } catch (e) {
      setError(e);
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog open={Boolean(job)} onClose={sending ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("agency.send.title", { job: job?.title ?? "" })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography sx={{ fontSize: 14, color: f.muted }}>{t("agency.send.intro")}</Typography>
          <TextField required label={t("agency.send.name")} value={name} onChange={(e) => setName(e.target.value)} inputProps={{ maxLength: 255 }} autoFocus />
          <TextField required type="email" label={t("agency.send.email")} value={email} onChange={(e) => setEmail(e.target.value)}
            error={Boolean(email) && !emailOk} helperText={email && !emailOk ? t("agency.send.email_bad") : t("agency.send.email_hint")} />
          <TextField label={t("agency.send.phone")} value={phone} onChange={(e) => setPhone(e.target.value)} inputProps={{ maxLength: 50 }} />
          <Box>
            <Button variant="outlined" component="label" startIcon={<Emoji name="page" size={16} />}>
              {resume ? t("agency.send.resume_change") : t("agency.send.resume")}
              <input hidden type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={(e) => setResume(e.target.files?.[0] ?? null)} />
            </Button>
            <Typography sx={{ fontSize: 13, color: f.muted, mt: 0.5 }}>{resume ? resume.name : t("agency.send.resume_hint")}</Typography>
          </Box>
          <FormControlLabel control={<Checkbox checked={consent} onChange={(e) => setConsent(e.target.checked)} />} label={t("agency.send.consent")} />
          <Typography sx={{ fontSize: 13, color: f.muted }}>{t("agency.send.first_wins")}</Typography>
          {error ? <FriendlyError error={error} compact /> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={sending}>{t("agency.common.cancel")}</Button>
        <Button variant="contained" onClick={submit} disabled={!ready || sending} startIcon={<Emoji name="envelope" size={16} />}>
          {sending ? t("agency.send.sending") : t("agency.send.submit")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function JobCard({ job, onSend, canSend }: { job: PortalJob; onSend: () => void; canSend: boolean }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const [open, setOpen] = useState(false);
  const exp = job.experience_min_years != null || job.experience_max_years != null
    ? t("agency.job.experience", { min: job.experience_min_years ?? 0, max: job.experience_max_years ?? "+" }) : null;
  return (
    <Box component="li" sx={{ border: `1px solid ${f.line}`, borderRadius: "12px", p: 2, bgcolor: f.surface2 }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "flex-start" }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography component="h3" sx={{ fontWeight: 800 }}>{job.title}</Typography>
          <Typography sx={{ fontSize: 13, color: f.muted }}>
            {[job.department, job.location, job.job_type, exp].filter(Boolean).join(" · ")}
          </Typography>
          <Stack direction="row" spacing={0.75} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            {job.positions ? <StatusChip tone="brand" emoji="people" label={t("agency.job.positions", { count: job.positions })} /> : null}
            {job.deadline ? <StatusChip tone="sun" emoji="alarm_clock" label={t("agency.job.deadline", { date: fmt.date(job.deadline) })} /> : null}
            <StatusChip tone={job.sent ? "ok" : "muted"} emoji="envelope" label={t("agency.job.sent", { count: job.sent })} />
          </Stack>
          {job.jd_text ? (
            <>
              <Typography sx={{ fontSize: 14, mt: 1, whiteSpace: "pre-wrap", maxWidth: "75ch",
                ...(open ? {} : { display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }) }}>
                {job.jd_text}
              </Typography>
              <Button size="small" onClick={() => setOpen(!open)} sx={{ mt: 0.5 }}>{t(open ? "agency.job.less" : "agency.job.more")}</Button>
            </>
          ) : null}
        </Box>
        {canSend && <Button variant="contained" onClick={onSend} startIcon={<Emoji name="technologist" size={16} />} sx={{ flexShrink: 0 }}>{t("agency.job.send")}</Button>}
      </Stack>
    </Box>
  );
}

function Submissions({ reloadKey }: { reloadKey: number }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const [rows, setRows] = useState<PortalSubmission[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => {
    setError(null);
    agencyPortalApi.submissions().then(setRows).catch(setError);
  }, []);
  useEffect(load, [load, reloadKey]);

  if (error) return <FriendlyError error={error} onRetry={load} compact />;
  if (rows === null) return <Box sx={{ display: "grid", placeItems: "center", py: 4 }}><CircularProgress aria-label={t("agency.common.loading")} /></Box>;
  if (rows.length === 0) return <EmptyState compact illustration="empty" title={t("agency.sent.empty")} hint={t("agency.sent.empty_hint")} />;
  return (
    <Stack spacing={1} component="ul" sx={{ listStyle: "none", p: 0, m: 0 }}>
      {rows.map((r) => (
        <Box component="li" key={r.id} sx={{ border: `1px solid ${f.line}`, borderRadius: "12px", p: 1.5, bgcolor: f.surface2 }}>
          <Typography sx={{ fontWeight: 700 }}>{r.candidate_name || r.candidate_email}</Typography>
          <Typography sx={{ fontSize: 12, color: f.muted }}>
            {r.job_title} · {fmt.date(r.submitted_at)}{r.submitted_by ? ` · ${t("agency.sent.by", { name: r.submitted_by })}` : ""}
          </Typography>
          <Box sx={{ mt: 1 }}><AgencyStageChip stage={r.stage} /></Box>
        </Box>
      ))}
    </Stack>
  );
}

export default function AgencyPortalPage() {
  const t = useT();
  const [me, setMe] = useState<PortalMe | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [sendFor, setSendFor] = useState<PortalJob | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [toast, show] = useToast();

  const load = useCallback(() => {
    setError(null);
    agencyPortalApi.me().then(setMe).catch(setError);
  }, []);
  useEffect(load, [load, reloadKey]);

  return (
    <Box>
      <PageHeader emoji="handshake" title={me ? t("agency.portal.title_named", { agency: me.agency.name }) : t("agency.portal.title")} purpose={t("agency.portal.purpose")} />
      {error ? <FriendlyError error={error} onRetry={load} /> : me === null ? (
        <Box sx={{ display: "grid", placeItems: "center", py: 6 }}><CircularProgress aria-label={t("agency.common.loading")} /></Box>
      ) : (
        <PageGrid>
          <Cell span={{ md: 12, lg: 7 }}>
            <Section emoji="briefcase" title={t("agency.jobs.title")} hint={t("agency.jobs.hint")}>
              {!me.agency.active ? (
                <EmptyState compact illustration="empty" title={t("agency.jobs.paused")} hint={t("agency.jobs.paused_hint")} />
              ) : me.jobs.length === 0 ? (
                <EmptyState compact illustration="empty" title={t("agency.jobs.empty")} hint={t("agency.jobs.empty_hint")} />
              ) : (
                <Stack spacing={1.5} component="ul" sx={{ listStyle: "none", p: 0, m: 0 }}>
                  {me.jobs.map((j) => <JobCard key={j.id} job={j} canSend onSend={() => setSendFor(j)} />)}
                </Stack>
              )}
            </Section>
          </Cell>
          <Cell span={{ md: 12, lg: 5 }}>
            <Section emoji="inbox" title={t("agency.sent.title")}>
              <Submissions reloadKey={reloadKey} />
            </Section>
          </Cell>
        </PageGrid>
      )}
      <SendDialog job={sendFor} onClose={() => setSendFor(null)}
        onSent={() => { show(t("agency.send.done", { job: sendFor?.title ?? "" })); setSendFor(null); setReloadKey((k) => k + 1); }} />
      {toast}
    </Box>
  );
}
