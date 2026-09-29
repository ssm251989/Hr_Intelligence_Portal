import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { extractErrorMessage, interviewSchedulingApi, type SchedulingStatus } from "../../api/client";
import { interviewersApi, type Availability } from "../../api/interviewersApi";
import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";
import ScheduleInterviewDialog from "../ScheduleInterviewDialog";

const EMOJI: Record<SchedulingStatus["state"], string> = {
  not_started: "calendar", waiting_interviewer: "hourglass", waiting_candidate: "hourglass", needs_manual: "warning",
  scheduled: "calendar", done: "check", cancelled: "pause",
};

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : d.toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

// Part 18.28: "Waiting for Jr to pick interview times - email sent 10:32 AM" + what HR can do.
// Computed by the backend from the real negotiation / interview rows, never from a stage label.
export default function SchedulingStatusCard({ applicationId, candidateName, canWrite, onChanged }: {
  applicationId: string; candidateName: string | null; canWrite: boolean; onChanged?: () => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [st, setSt] = useState<SchedulingStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [changeOpen, setChangeOpen] = useState(false);
  const [bookOpen, setBookOpen] = useState(false);
  const [people, setPeople] = useState<Availability[]>([]);
  const [pick, setPick] = useState("");

  const load = useCallback(() => {
    interviewSchedulingApi.status(applicationId).then(setSt).catch(() => setSt(null));
  }, [applicationId]);
  useEffect(() => { load(); }, [load]);

  const run = async (key: string, fn: () => Promise<SchedulingStatus>, done: string): Promise<boolean> => {
    setBusy(key); setError(null); setNotice(null);
    try {
      setSt(await fn());
      setNotice(done);
      onChanged?.();
      return true;
    } catch (err) {
      setError(extractErrorMessage(err, t("sched.failed")));
      return false;
    } finally {
      setBusy(null);
    }
  };

  const openChange = () => {
    setPick(""); setError(null); setChangeOpen(true);
    interviewersApi.all().then((r) => setPeople(r.items)).catch(() => setPeople([]));
  };

  if (!st) return null;
  const name = st.interviewer_name || st.interviewer_email || t("sched.the_interviewer");
  const line = {
    not_started: st.message || t("sched.not_started"),
    waiting_interviewer: t("sched.waiting_interviewer", { name, time: when(st.sent_at) }),
    waiting_candidate: t("sched.waiting_candidate", { name: candidateName || t("sched.the_candidate"), time: when(st.sent_at) }),
    needs_manual: st.message || t("sched.needs_manual"),
    scheduled: t("sched.scheduled", { name, time: when(st.scheduled_at) }),
    done: t("sched.done", { name }),
    cancelled: t("sched.cancelled", { time: when(st.sent_at) }),
  }[st.state];
  const picked = people.find((p) => p.email === pick);

  return (
    <Box sx={{ p: 1.75, mb: 2, borderRadius: "14px", border: `1px solid ${f.line}`, bgcolor: f.surface2 }} data-testid="scheduling-status">
      <Stack direction="row" spacing={1.25} alignItems="flex-start">
        <Emoji name={EMOJI[st.state]} size={22} />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontWeight: 800, fontSize: 14 }}>{t(`sched.title.${st.state}`)}</Typography>
          <Typography sx={{ fontSize: 13.5, color: f.muted, mt: 0.25 }}>{line}</Typography>
          {st.state.startsWith("waiting") && st.expires_at && (
            <Typography sx={{ fontSize: 12, color: f.muted, mt: 0.25 }}>{t("sched.link_until", { time: when(st.expires_at) })}</Typography>
          )}
        </Box>
      </Stack>
      {error && <Alert severity="warning" sx={{ mt: 1.25 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mt: 1.25 }} onClose={() => setNotice(null)}>{notice}</Alert>}
      {canWrite && (st.can_resend || st.can_change || st.can_book || st.can_cancel) && (
        <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: "wrap", rowGap: 1 }}>
          {st.can_resend && (
            <Button size="small" variant="outlined" disabled={Boolean(busy)} onClick={() => run("resend", () => interviewSchedulingApi.resend(applicationId), t("sched.resent"))}>
              {busy === "resend" ? t("sched.working") : t("sched.resend")}
            </Button>
          )}
          {st.can_change && <Button size="small" variant="outlined" disabled={Boolean(busy)} onClick={openChange}>{t("sched.change")}</Button>}
          {st.can_book && <Button size="small" variant="contained" disabled={Boolean(busy)} onClick={() => setBookOpen(true)}>{t("sched.book")}</Button>}
          {st.can_cancel && (
            <Button size="small" color="error" disabled={Boolean(busy)}
              onClick={() => { if (window.confirm(t("sched.cancel_confirm"))) void run("cancel", () => interviewSchedulingApi.cancel(applicationId), t("sched.cancelled_done")); }}>
              {busy === "cancel" ? t("sched.working") : t("sched.cancel")}
            </Button>
          )}
        </Stack>
      )}

      <Dialog open={changeOpen} onClose={busy ? undefined : () => setChangeOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{t("sched.change_title")}</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: 13.5, color: f.muted, mb: 2 }}>{t("sched.change_hint")}</Typography>
          <TextField select fullWidth label={t("sched.interviewer")} value={pick} onChange={(e) => setPick(e.target.value)}>
            {people.map((p) => (
              <MenuItem key={p.email} value={p.email}>
                {(p.name || p.email) + " · " + p.email + (p.has_availability ? "" : ` · ${t("sched.no_availability")}`)}
              </MenuItem>
            ))}
          </TextField>
          {picked && !picked.has_availability && (
            <Alert severity="warning" sx={{ mt: 1.5 }}
              action={<Button size="small" component={RouterLink} to={`/interviews/interviewers?edit=${encodeURIComponent(picked.email)}`}>{t("sched.add_availability")}</Button>}>
              {t("sched.needs_availability", { name: picked.name || picked.email })}
            </Alert>
          )}
          {error && <Alert severity="warning" sx={{ mt: 1.5 }}>{error}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setChangeOpen(false)} disabled={Boolean(busy)}>{t("action.cancel")}</Button>
          <Button variant="contained" disabled={!pick || !picked?.has_availability || Boolean(busy)}
            onClick={async () => { if (await run("change", () => interviewSchedulingApi.changeInterviewer(applicationId, pick), t("sched.changed", { name: picked?.name || pick }))) setChangeOpen(false); }}>
            {busy === "change" ? t("sched.working") : t("sched.send_times")}
          </Button>
        </DialogActions>
      </Dialog>

      <ScheduleInterviewDialog open={bookOpen} presetApplicationId={applicationId} onClose={() => setBookOpen(false)}
        onScheduled={() => { setBookOpen(false); load(); onChanged?.(); }} />
    </Box>
  );
}
