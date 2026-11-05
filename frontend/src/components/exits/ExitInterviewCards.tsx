import { useCallback, useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { exitInterviewApi, type Answers, type ExitInterviewHr, type ExitInterviewView } from "../../api/exitInterviewApi";
import { useI18n } from "../../i18n";
import { Emoji, StatusChip } from "../../ui-kit";
import { ExitInterviewFields } from "./ExitInterviewFields";

// fix 2026-10-06: the exit interview is answered by the EMPLOYEE (here) and read by HR (HrExitInterviewCard).

const STATUS: Record<string, { tone: "muted" | "sun" | "ok"; emoji: string }> = {
  not_started: { tone: "muted", emoji: "hourglass" }, in_progress: { tone: "sun", emoji: "memo" }, submitted: { tone: "ok", emoji: "check" },
};

function StatusLine({ v }: { v: Pick<ExitInterviewView, "status" | "submitted_at"> }) {
  const { t } = useI18n();
  const s = STATUS[v.status];
  return <StatusChip tone={s.tone} emoji={s.emoji} label={v.status === "submitted" && v.submitted_at
    ? t("exitq.status.submitted_on", { date: new Date(v.submitted_at).toLocaleDateString() }) : t(`exitq.status.${v.status}`)} />;
}

/** Employee: "A few questions before you go" -- autosaves, Submit, then read-only. */
export function MyExitInterview({ firstTime, onSkip }: { firstTime?: boolean; onSkip?: () => void }) {
  const { t } = useI18n();
  const f = useTheme().palette.fresh;
  const [v, setV] = useState<ExitInterviewView | null>(null);
  const [answers, setAnswers] = useState<Answers>({});
  const [saved, setSaved] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  // the latest answers, so quick typing in several fields never drops one (state updates are async)
  const latest = useRef<Answers>({});
  latest.current = answers;
  const load = useCallback(() => exitInterviewApi.mine().then((r) => { setV(r); setAnswers(r.answers); }).catch(() => setV(null)), []);
  useEffect(() => { load(); return () => window.clearTimeout(timer.current); }, [load]);
  if (!v) return null;
  const change = (id: string, value: string | number | null) => {
    const next = { ...latest.current, [id]: value };
    latest.current = next;
    setAnswers(next);
    setSaved("saving");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { exitInterviewApi.saveDraft(latest.current).then(() => setSaved("saved")).catch(() => setSaved("idle")); }, 900);
  };
  const submit = async () => {
    setBusy(true);
    setError(null);
    window.clearTimeout(timer.current);
    try {
      const r = await exitInterviewApi.submit(latest.current);
      setV(r);
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Box data-testid="my-exit-interview" sx={{ p: 2, borderRadius: "14px", border: `2px solid ${firstTime && v.can_edit ? f.brand : f.line}`, bgcolor: f.surface }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
        <Emoji name="speech" size={20} />
        <Typography component="h3" sx={{ fontWeight: 800, flex: 1 }}>{firstTime ? t("exitq.step2") : t("exitq.title")}</Typography>
        <StatusLine v={v} />
      </Stack>
      <Alert severity="info" icon={<Emoji name="lock" size={16} />} sx={{ mb: 1.5 }}>{t("exitq.private")}</Alert>
      {v.can_edit ? (
        <>
          {v.deadline && <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("exitq.until", { date: new Date(`${v.deadline}T00:00:00`).toLocaleDateString() })}</Typography>}
          <ExitInterviewFields questions={v.questions} answers={answers} onChange={change} />
          {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2 }}>
            <Button variant="contained" onClick={submit} disabled={busy}>{t("exitq.submit")}</Button>
            {onSkip && <Button onClick={onSkip}>{t("exitq.skip")}</Button>}
            <Typography sx={{ fontSize: 12, color: f.muted }} role="status">{saved === "saving" ? t("exitq.saving") : saved === "saved" ? t("exitq.saved") : t("exitq.autosave")}</Typography>
          </Stack>
        </>
      ) : v.status === "submitted" ? (
        <>
          <Typography sx={{ fontSize: 14, mb: 1.5 }}>{t("exitq.thanks")}</Typography>
          <ExitInterviewFields questions={v.questions} answers={v.answers} readOnly />
        </>
      ) : <Typography sx={{ color: f.muted }}>{t("exitq.closed")}</Typography>}
    </Box>
  );
}

/** HR: read-only answers + AI summary + reminder + private notes; "Record answers from a call" only when the person can't answer. */
export function HrExitInterviewCard({ separationId, canEdit, onToast }: { separationId: string; canEdit: boolean; onToast: (m: string) => void }) {
  const { t } = useI18n();
  const f = useTheme().palette.fresh;
  const [v, setV] = useState<ExitInterviewHr | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [recording, setRecording] = useState(false);
  const [callAnswers, setCallAnswers] = useState<Answers>({});
  const load = useCallback(() => exitInterviewApi.hr(separationId).then((r) => { setV(r); setNotes(r.hr_notes); }).catch((e) => setError(extractErrorMessage(e, ""))), [separationId]);
  useEffect(() => { load(); }, [load]);
  if (error) return <Alert severity="warning">{error}</Alert>;
  if (!v) return null;
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setError(null);
    try { await fn(); onToast(ok); load(); } catch (e) { setError(extractErrorMessage(e, "")); }
  };
  return (
    <Box data-testid="hr-exit-interview">
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
        <StatusLine v={v} />
        {v.filled_by === "hr_call" && v.filled_by_hr && (
          <StatusChip tone="sky" emoji="phone" label={t("exitq.filled_by_hr", { date: new Date(v.filled_by_hr.at).toLocaleDateString() })} />
        )}
        {v.reminders.length > 0 && <Typography sx={{ fontSize: 12, color: f.muted }}>{t("exitq.reminded", { n: v.reminders.length, date: new Date(v.reminders[v.reminders.length - 1].at).toLocaleDateString() })}</Typography>}
      </Stack>
      <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("exitq.hr_hint")}</Typography>
      {v.status === "submitted" ? <ExitInterviewFields questions={v.questions} answers={v.answers} readOnly />
        : <Typography sx={{ color: f.muted, fontStyle: "italic" }}>{v.status === "in_progress" ? t("exitq.hr_in_progress") : t("exitq.hr_not_started")}</Typography>}
      {v.status === "submitted" && (v.ai_summary?.summary || v.ai_summary?.error) && (
        <Box sx={{ mt: 1.5, p: 1.5, bgcolor: f.skySoft, borderRadius: "12px" }} data-testid="exit-ai-summary">
          <Typography sx={{ fontWeight: 700, fontSize: 13 }}><Emoji name="sparkles" size={14} /> {t("exitq.ai_label")}</Typography>
          {v.ai_summary?.summary ? <Typography sx={{ fontSize: 14, whiteSpace: "pre-wrap", maxWidth: "75ch" }}>{v.ai_summary.summary}</Typography>
            : <Typography sx={{ fontSize: 13, color: f.muted }}>{t("exitq.ai_failed", { why: v.ai_summary?.error ?? "" })}</Typography>}
          {canEdit && v.ai_enabled && <Button size="small" onClick={() => act(() => exitInterviewApi.summary(separationId), t("exitq.ai_redone"))}>{t("exitq.ai_redo")}</Button>}
        </Box>
      )}
      {canEdit && v.status !== "submitted" && (
        <Stack direction="row" spacing={1} sx={{ mt: 1.5 }} flexWrap="wrap" useFlexGap>
          {!v.can_record_call && <Button variant="outlined" size="small" onClick={() => act(() => exitInterviewApi.remind(separationId), t("exitq.reminder_sent"))}>{t("exitq.remind")}</Button>}
          {v.can_record_call && !recording && <Button variant="outlined" size="small" onClick={() => { setCallAnswers({}); setRecording(true); }}>{t("exitq.record_call")}</Button>}
        </Stack>
      )}
      {recording && (
        <Box sx={{ mt: 1.5, p: 1.5, border: `1px dashed ${f.line}`, borderRadius: "12px" }}>
          <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("exitq.record_hint")}</Typography>
          <ExitInterviewFields questions={v.questions} answers={callAnswers} onChange={(id, val) => setCallAnswers((a) => ({ ...a, [id]: val }))} />
          <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
            <Button variant="contained" size="small" onClick={() => act(() => exitInterviewApi.recordCall(separationId, callAnswers).then(() => setRecording(false)), t("exitq.recorded"))}>{t("exitq.record_save")}</Button>
            <Button size="small" onClick={() => setRecording(false)}>{t("action.cancel")}</Button>
          </Stack>
        </Box>
      )}
      {canEdit && (
        <Box sx={{ mt: 2 }}>
          <TextField label={t("exitq.hr_notes")} helperText={t("exitq.hr_notes_hint")} value={notes} onChange={(e) => setNotes(e.target.value)} multiline minRows={2} fullWidth />
          {notes !== v.hr_notes && <Button size="small" sx={{ mt: 0.5 }} onClick={() => act(() => exitInterviewApi.notes(separationId, notes), t("exitq.notes_saved"))}>{t("exitq.notes_save")}</Button>}
        </Box>
      )}
    </Box>
  );
}
