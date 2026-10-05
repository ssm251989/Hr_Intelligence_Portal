import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { onboardingExtraApi, type ExitKind, type JoinerReasons } from "../../api/onboardingExtra";
import { useT } from "../../i18n";
import { explainError } from "../../ui-kit";

// Fix 2026-10-05: one dialog for every joiner action. The server decides what is allowed (joiner_stage.py);
// this only asks for what each action needs. Exits (absconded / resigned / terminated) get a second
// "are you sure" step because they create an exit case and switch off access.

export type JoinerDialogKind = "withdraw_offer" | "candidate_declined" | "no_show" | "not_reporting" | "stop_not_reporting" | ExitKind;

// literal keys so the i18n check can see them
const TITLE: Record<JoinerDialogKind, { titleKey: string; hintKey: string }> = {
  withdraw_offer: { titleKey: "joinerx.withdraw.title", hintKey: "joinerx.withdraw.body" },
  candidate_declined: { titleKey: "joinerx.declined.title", hintKey: "joinerx.declined.body" },
  no_show: { titleKey: "joinerx.no_show.title", hintKey: "joinerx.no_show.body" },
  not_reporting: { titleKey: "joinerx.not_reporting.title", hintKey: "joinerx.not_reporting.body" },
  stop_not_reporting: { titleKey: "joinerx.stop.title", hintKey: "joinerx.stop.body" },
  absconded: { titleKey: "joinerx.absconded.title", hintKey: "joinerx.absconded.body" },
  resigned: { titleKey: "joinerx.resigned.title", hintKey: "joinerx.resigned.body" },
  terminated: { titleKey: "joinerx.terminated.title", hintKey: "joinerx.terminated.body" },
};
const REASON_LABEL: Record<string, { labelKey: string }> = {
  accepted_other_offer: { labelKey: "joinerx.r.accepted_other_offer" }, compensation: { labelKey: "joinerx.r.compensation" },
  location: { labelKey: "joinerx.r.location" }, role: { labelKey: "joinerx.r.role" }, personal: { labelKey: "joinerx.r.personal" },
  counter_offer: { labelKey: "joinerx.r.counter_offer" }, no_response: { labelKey: "joinerx.r.no_response" }, other: { labelKey: "joinerx.r.other" },
  no_contact: { labelKey: "joinerx.r.no_contact" }, health: { labelKey: "joinerx.r.health" }, relocation: { labelKey: "joinerx.r.relocation" },
  other_job: { labelKey: "joinerx.r.other_job" }, better_offer: { labelKey: "joinerx.r.better_offer" }, role_mismatch: { labelKey: "joinerx.r.role_mismatch" },
  culture: { labelKey: "joinerx.r.culture" }, performance: { labelKey: "joinerx.r.performance" }, conduct: { labelKey: "joinerx.r.conduct" },
  attendance: { labelKey: "joinerx.r.attendance" }, background_check: { labelKey: "joinerx.r.background_check" },
};
const EXITS: JoinerDialogKind[] = ["absconded", "resigned", "terminated"];

const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export default function JoinerActionDialog({ kind, caseId, name, lastSeen, onClose, onDone }: {
  kind: JoinerDialogKind | null; caseId: string | null; name: string; lastSeen?: string | null; onClose: () => void; onDone: (kind: JoinerDialogKind) => void;
}) {
  const t = useT();
  const [reasons, setReasons] = useState<JoinerReasons | null>(null);
  const [reason, setReason] = useState("");
  const [code, setCode] = useState("");
  const [notes, setNotes] = useState("");
  const [day, setDay] = useState(todayIso());
  const [contacted, setContacted] = useState("");
  const [rehire, setRehire] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!kind) return;
    setReason(""); setCode(""); setNotes(""); setContacted(""); setError(null); setConfirming(false);
    setDay(kind === "absconded" && lastSeen ? lastSeen : todayIso());
    setRehire(kind === "resigned");
    if (!reasons) onboardingExtraApi.joinerReasons().then(setReasons).catch(() => setReasons(null));
  }, [kind, lastSeen, reasons]);

  if (!kind || !caseId) return null;
  const isExit = EXITS.includes(kind);
  const list: Record<string, string> | null = kind === "candidate_declined" ? reasons?.declined ?? null : kind === "no_show" ? reasons?.no_show ?? null
    : isExit ? reasons?.exit[kind as ExitKind] ?? null : null;
  const label = (c: string) => (REASON_LABEL[c] ? t(REASON_LABEL[c].labelKey) : (list?.[c] ?? c));

  const ready = (() => {
    if (kind === "withdraw_offer") return reason.trim().length >= 3;
    if (kind === "stop_not_reporting") return notes.trim().length >= 3;
    if (kind === "not_reporting") return Boolean(day);
    if (list) return Boolean(code) && (code !== "other" || notes.trim().length > 0) && (!isExit || (notes.trim().length >= 3 && Boolean(day)));
    return true;
  })();

  const submit = async () => {
    if (isExit && !confirming) { setConfirming(true); return; }
    setSaving(true); setError(null);
    try {
      if (kind === "withdraw_offer") await onboardingExtraApi.revoke(caseId, { reason: reason.trim(), notes: notes.trim() || undefined });
      else if (kind === "candidate_declined") await onboardingExtraApi.declined(caseId, { reason_code: code, notes: notes.trim() || undefined });
      else if (kind === "no_show") await onboardingExtraApi.noShow(caseId, { reason_code: code, notes: notes.trim() || undefined, contacted_on: contacted || null });
      else if (kind === "not_reporting") await onboardingExtraApi.notReporting(caseId, { last_seen: day, notes: notes.trim() || undefined });
      else if (kind === "stop_not_reporting") await onboardingExtraApi.stopNotReporting(caseId, notes.trim());
      else await onboardingExtraApi.recordExit(caseId, { kind: kind as ExitKind, last_working_day: day, reason_code: code, notes: notes.trim(), rehire_eligible: rehire, confirm: true });
      onDone(kind);
    } catch (e) {
      setError(e);
      setConfirming(false);
    } finally {
      setSaving(false);
    }
  };

  const err = error ? explainError(error) : null;
  const danger = kind === "withdraw_offer" || isExit;
  return (
    <Dialog open onClose={saving ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t(TITLE[kind].titleKey, { name })}</DialogTitle>
      <DialogContent>
        {confirming ? (
          <Stack spacing={1.5} sx={{ pt: 1 }}>
            <Alert severity="warning">{t("joinerx.confirm.body", { name, date: new Date(`${day}T00:00:00`).toLocaleDateString() })}</Alert>
            <Typography>{t("joinerx.confirm.what")}</Typography>
            <Typography component="ul" sx={{ m: 0, pl: 3 }}>
              <li>{t("joinerx.confirm.exit_case")}</li>
              <li>{t("joinerx.confirm.access")}</li>
              <li>{t("joinerx.confirm.opening")}</li>
              <li>{rehire ? t("joinerx.confirm.rehire_yes") : t("joinerx.confirm.rehire_no")}</li>
            </Typography>
          </Stack>
        ) : (
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Typography color="text.secondary">{t(TITLE[kind].hintKey, { name })}</Typography>
            {kind === "withdraw_offer" && (
              <TextField label={t("joinerx.f.reason")} required value={reason} onChange={(e) => setReason(e.target.value)} helperText={t("joinerx.f.reason_internal")} />
            )}
            {list && (
              <TextField select required label={t("joinerx.f.reason")} value={code} onChange={(e) => setCode(e.target.value)}>
                {Object.keys(list).map((c) => <MenuItem key={c} value={c}>{label(c)}</MenuItem>)}
              </TextField>
            )}
            {(kind === "not_reporting" || isExit) && (
              <TextField type="date" required label={kind === "not_reporting" ? t("joinerx.f.last_seen") : t("joinerx.f.lwd")} value={day}
                onChange={(e) => setDay(e.target.value)} slotProps={{ inputLabel: { shrink: true }, htmlInput: kind === "absconded" || kind === "not_reporting" ? { max: todayIso() } : undefined }}
                helperText={kind === "absconded" ? t("joinerx.f.lwd_absconded") : kind === "not_reporting" ? t("joinerx.f.last_seen_hint") : undefined} />
            )}
            {kind === "no_show" && (
              <TextField type="date" label={t("joinerx.f.contacted_on")} value={contacted} onChange={(e) => setContacted(e.target.value)}
                slotProps={{ inputLabel: { shrink: true }, htmlInput: { max: todayIso() } }} helperText={t("joinerx.f.optional")} />
            )}
            <TextField label={isExit || kind === "stop_not_reporting" ? t("joinerx.f.notes_required") : t("joinerx.f.notes")} value={notes}
              onChange={(e) => setNotes(e.target.value)} multiline minRows={2} required={isExit || kind === "stop_not_reporting" || code === "other"} />
            {isExit && (
              <FormControlLabel control={<Checkbox checked={rehire} onChange={(e) => setRehire(e.target.checked)} />} label={t("joinerx.f.rehire")} />
            )}
            {kind === "withdraw_offer" && <Alert severity="info">{t("joinerx.withdraw.email_note", { name })}</Alert>}
          </Stack>
        )}
        {err && <Alert severity="error" sx={{ mt: 2 }}><b>{err.what}</b> {err.fix}</Alert>}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={confirming ? () => setConfirming(false) : onClose} disabled={saving}>{confirming ? t("joinerx.back") : t("action.cancel")}</Button>
        <Button variant="contained" color={danger ? "error" : "primary"} disabled={saving || !ready} onClick={submit}>
          {saving ? t("joinerx.saving") : confirming ? t("joinerx.confirm.yes") : t(`joinerx.go.${kind}`)}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
