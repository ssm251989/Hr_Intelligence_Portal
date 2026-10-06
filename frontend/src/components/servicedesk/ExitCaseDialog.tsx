// Part 15.6 -- one person's exit for HR: confirm last day, talk about staying, withdraw,
// exit interview (X3), relieving letter status + issue (X5), close the exit.
import { useEffect, useState, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

import { serviceDeskExtra, type SeparationRow } from "../../api/serviceDeskExtra";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";
import ConfirmDialog from "../ConfirmDialog";
import { Emoji, FriendlyError, InfoTip, StageStepper, StatusChip } from "../../ui-kit";
import { LetterChip, LetterPreviewButton, letterState } from "./LetterStatus";
import { HrExitInterviewCard } from "../exits/ExitInterviewCards";
import { SeparationStatusChip, typeLabel, useDateFmt } from "./shared";

const STAGES = ["submitted", "approved", "clearance", "completed"];
export function stageIndex(status: string): number {
  if (status === "retention") return 0;
  const i = STAGES.indexOf(status);
  return i < 0 ? 0 : i;
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function Block({ emoji, title, children, tip }: { emoji: string; title: string; children: ReactNode; tip?: string }) {
  const f = useTheme().palette.fresh;
  return (
    <Box component="section" sx={{ border: `1px solid ${f.line}`, borderRadius: "14px", p: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
        <Emoji name={emoji} size={18} />
        <Typography component="h3" sx={{ fontWeight: 800 }}>{title}</Typography>
        {tip && <InfoTip text={tip} />}
      </Stack>
      {children}
    </Box>
  );
}


export default function ExitCaseDialog({ separation, onClose, onChanged, onToast, reasonLabel }: {
  separation: SeparationRow | null; onClose: () => void; onChanged: () => void; onToast: (m: string) => void; reasonLabel: (c?: string | null) => string;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fullScreen = useMediaQuery(useTheme().breakpoints.down("sm"));
  const fmt = useDateFmt();
  const { can } = useMeBootstrap();
  const s = separation;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [lwd, setLwd] = useState("");
  const [waived, setWaived] = useState("");
  const [buyout, setBuyout] = useState("");
  const [retention, setRetention] = useState("");
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [rehire, setRehire] = useState(true);
  const [alumni, setAlumni] = useState(false);
  const [regretted, setRegretted] = useState(false);

  const standard = s ? addDays(s.submitted_on ?? new Date().toISOString().slice(0, 10), s.notice_period_days) : "";

  useEffect(() => {
    if (!s) return;
    setError(null);
    setLwd(s.approved_lwd ?? s.requested_lwd ?? standard);
    setWaived("");
    setBuyout("");
    setRetention("");
    setRehire(s.rehire_eligible ?? true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s?.id]);

  const run = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onToast(msg);
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (!s) return null;
  const name = s.employee_name ?? s.employee_code ?? "—";
  const canEdit = can("separation.case.edit");
  const canApprove = can("separation.case.approve");
  const lwdPassed = s.approved_lwd ? new Date(`${s.approved_lwd}T23:59:59`) < new Date() : false;

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="md" fullScreen={fullScreen} aria-labelledby="sd-exit-title">
      <DialogTitle id="sd-exit-title">{t("exits.case.title", { name })}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
            <SeparationStatusChip status={s.status} />
            <StatusChip tone="muted" emoji="door" label={typeLabel(t, s.type)} />
            {s.exit_interview_done
              ? <StatusChip tone="ok" emoji="speech" label={t("exits.interview.done")} />
              : <StatusChip tone="sun" emoji="speech" label={t("exits.interview.pending")} />}
          </Stack>
          {s.status !== "withdrawn" && (
            <StageStepper stages={STAGES.map((k) => t(`exits.step.${k}`))} current={stageIndex(s.status)} />
          )}
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" }, gap: 1.5, bgcolor: f.surface2, borderRadius: "12px", p: 1.5 }}>
            {[
              [t("exits.col.submitted"), fmt.date(s.submitted_on)],
              [t("exits.col.lwd"), s.approved_lwd ? fmt.date(s.approved_lwd) : s.requested_lwd ? t("exits.me.requested", { date: fmt.date(s.requested_lwd) }) : t("exits.me.lwd_pending")],
              [t("exits.case.reason"), s.reason_code ? reasonLabel(s.reason_code) : "—"],
              [t("exits.col.clearance"), t("exits.me.progress_text", { done: s.items_total - s.items_pending, total: s.items_total })],
            ].map(([k, v]) => (
              <Box key={k}>
                <Typography sx={{ fontSize: 12, color: f.muted }}>{k}</Typography>
                <Typography sx={{ fontSize: 14, fontWeight: 600 }}>{v}</Typography>
              </Box>
            ))}
          </Box>
          {s.reason_text && <Typography sx={{ whiteSpace: "pre-wrap", maxWidth: "75ch", color: f.muted }}>“{s.reason_text}”</Typography>}
          {error ? <FriendlyError error={error} compact /> : null}

          {s.status === "retention" && canEdit && (
            <Block emoji="handshake" title={t("exits.case.retention_title")}>
              <TextField fullWidth multiline minRows={2} label={t("exits.case.retention_notes")} placeholder={t("exits.case.retention_ph")} value={retention} onChange={(e) => setRetention(e.target.value)} />
              <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                <Button variant="contained" disabled={busy || !retention.trim()} onClick={() => run(() => serviceDeskExtra.retention(s.id, retention.trim(), true), t("exits.case.withdrawn"))}>{t("exits.case.stays")}</Button>
                <Button variant="outlined" disabled={busy || !retention.trim()} onClick={() => run(() => serviceDeskExtra.retention(s.id, retention.trim(), false), t("helpdesk.common.saved"))}>{t("exits.case.leaves")}</Button>
              </Stack>
            </Block>
          )}

          {["submitted", "approved"].includes(s.status) && canApprove && (
            <Block emoji="calendar" title={t("exits.case.lwd_title")}>
              <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
                <TextField type="date" required label={t("exits.case.lwd")} value={lwd} onChange={(e) => setLwd(e.target.value)} InputLabelProps={{ shrink: true }}
                  helperText={t("exits.case.lwd_hint", { date: fmt.date(standard) })} sx={{ minWidth: 220 }} />
                <TextField type="number" label={t("exits.case.waived")} placeholder={t("exits.case.waived_ph")} value={waived} onChange={(e) => setWaived(e.target.value)} inputProps={{ min: 0 }}
                  InputProps={{ endAdornment: <InfoTip text={t("exits.case.waived_tip")} /> }} />
                <TextField type="number" label={t("exits.case.buyout")} placeholder={t("exits.case.buyout_ph")} value={buyout} onChange={(e) => setBuyout(e.target.value)} inputProps={{ min: 0 }}
                  InputProps={{ endAdornment: <InfoTip text={t("exits.case.buyout_tip")} /> }} />
              </Stack>
              <Button sx={{ mt: 1.5 }} variant="contained" disabled={busy || !lwd}
                onClick={() => run(() => serviceDeskExtra.approveLwd(s.id, lwd, Number(waived) || 0, Number(buyout) || 0), t("exits.case.approved"))}>{t("exits.case.approve")}</Button>
            </Block>
          )}

          {/* fix 2026-10-06: the exit interview is answered by the EMPLOYEE; HR sees it read-only (managers not at all) */}
          {can("separation_hr.exit_interview.view") && (
            <Block emoji="speech" title={t("exits.interview.title")}>
              <HrExitInterviewCard separationId={s.id} canEdit={can("separation_hr.exit_interview.edit")} onToast={onToast} />
            </Block>
          )}

          <Block emoji="page" title={t("exits.letter.title")} tip={t("exits.letter.hold_tip")}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <LetterChip s={s} />
              {letterState(s) === "ready" && canApprove && (
                <Button variant="contained" size="small" disabled={busy} onClick={() => run(() => serviceDeskExtra.issueLetters(s.id), t("exits.letter.issued_toast"))}>{t("exits.letter.issue")}</Button>
              )}
              {s.letters.relieving && <LetterPreviewButton separationId={s.id} />}
            </Stack>
          </Block>

          {s.status === "clearance" && canApprove && (
            <Block emoji="check" title={t("exits.case.complete_title")}>
              <Typography sx={{ color: f.muted, fontSize: 14, mb: 1 }}>{t("exits.case.complete_hint")}</Typography>
              <Stack>
                <FormControlLabel control={<Checkbox checked={rehire} onChange={(e) => setRehire(e.target.checked)} />} label={t("exits.case.rehire")} />
                <FormControlLabel control={<Checkbox checked={alumni} onChange={(e) => setAlumni(e.target.checked)} />} label={t("exits.case.alumni")} />
                <FormControlLabel control={<Checkbox checked={regretted} onChange={(e) => setRegretted(e.target.checked)} />} label={t("exits.case.regretted")} />
              </Stack>
              <Button sx={{ mt: 1 }} variant="contained" disabled={busy || s.blocking_pending > 0 || !lwdPassed}
                onClick={() => run(() => serviceDeskExtra.complete(s.id, { rehire_eligible: rehire, alumni_opt_in: alumni, regretted }), t("exits.case.completed"))}>
                {t("exits.case.complete")}
              </Button>
            </Block>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        {["submitted", "retention", "approved"].includes(s.status) && canEdit && (
          <Button color="error" onClick={() => setWithdrawOpen(true)} disabled={busy} sx={{ mr: "auto" }}>{t("exits.case.withdraw")}</Button>
        )}
        <Button variant="contained" onClick={onClose}>{t("action.close")}</Button>
      </DialogActions>
      <ConfirmDialog open={withdrawOpen} title={t("exits.case.withdraw")} message={t("exits.case.withdraw_confirm")} confirmLabel={t("exits.case.withdraw")}
        cancelLabel={t("action.cancel")} confirming={busy}
        onCancel={() => setWithdrawOpen(false)}
        onConfirm={() => { setWithdrawOpen(false); run(() => serviceDeskExtra.withdraw(s.id), t("exits.case.withdrawn")); }} />
    </Dialog>
  );
}
