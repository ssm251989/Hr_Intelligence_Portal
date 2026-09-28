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

import { extractErrorMessage, http } from "../../api/client";
import { useT } from "../../i18n";

export const CLOSE_REASONS = ["filled", "cancelled", "business_hold", "other"] as const;
export interface CloseJobResult { on_hold: number; candidates_emailed: number; cancelled: { queued_emails: number; interview_links: number; form_links: number } }

// Part 18.8: close a job with a reason. Its active candidates go "On hold - job closed" (never
// rejected); pending emails / interview requests are cancelled; Reopen brings them back.
export default function CloseJobDialog({ open, jobId, title, onClose, onClosed }: {
  open: boolean; jobId: string; title: string; onClose: () => void; onClosed: (r: CloseJobResult) => void;
}) {
  const t = useT();
  const [reason, setReason] = useState<(typeof CLOSE_REASONS)[number]>("filled");
  const [note, setNote] = useState("");
  const [emailCandidates, setEmailCandidates] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) { setReason("filled"); setNote(""); setEmailCandidates(false); setError(null); }
  }, [open]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      onClosed(await http.post<CloseJobResult>(`/api/v1/ui/jobs/${jobId}/close`, { reason, note: note || null, email_candidates: emailCandidates }));
    } catch (err) {
      setError(extractErrorMessage(err, t("closejob.err")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t("closejob.title", { title })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Alert severity="info">{t("closejob.explain")}</Alert>
          <TextField select label={t("closejob.reason")} value={reason} onChange={(e) => setReason(e.target.value as (typeof CLOSE_REASONS)[number])} fullWidth>
            {CLOSE_REASONS.map((r) => <MenuItem key={r} value={r}>{t(`closejob.reason.${r}`)}</MenuItem>)}
          </TextField>
          <TextField label={t("closejob.note")} value={note} onChange={(e) => setNote(e.target.value)} fullWidth multiline minRows={2} />
          <FormControlLabel control={<Checkbox checked={emailCandidates} onChange={(e) => setEmailCandidates(e.target.checked)} />} label={t("closejob.email")} />
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>{t("lock.cancel")}</Button>
        <Button variant="contained" color="warning" onClick={submit} disabled={busy}>{t("closejob.confirm")}</Button>
      </DialogActions>
    </Dialog>
  );
}
