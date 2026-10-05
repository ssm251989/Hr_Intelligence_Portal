import { useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { candidatesApi, extractErrorMessage } from "../../api/client";
import type { CandidateRead } from "../../api/types";
import { useT } from "../../i18n";

// Fix 2026-10-05: resumes give one line ("Gunda Kishore") and many names put the family name first.
// HR corrects first / last / preferred name here; emails, the welcome portal and the pre-hire
// employee record use them from then on.
export default function NameEditDialog({ candidate, onClose, onSaved }: { candidate: CandidateRead; onClose: () => void; onSaved: () => void }) {
  const t = useT();
  const parts = candidate.name_parts;
  // not known yet: start from the plain word split, so "Swap" fixes a family-name-first name in one click
  const words = (candidate.full_name ?? "").trim().split(/\s+/).filter(Boolean);
  const [first, setFirst] = useState(candidate.first_name ?? (parts?.first_name || words[0] || ""));
  const [last, setLast] = useState(candidate.last_name ?? (parts?.first_name ? parts.last_name : words.slice(1).join(" ")));
  const [preferred, setPreferred] = useState(candidate.preferred_name ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const swap = () => { setFirst(last); setLast(first); };
  const save = async () => {
    setBusy(true); setProblem(null);
    try {
      await candidatesApi.update(candidate.id, { first_name: first.trim() || null, last_name: last.trim() || null, preferred_name: preferred.trim() || null });
      onSaved();
    } catch (e) {
      setProblem(extractErrorMessage(e, t("candidates.names.failed")));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t("candidates.names.title")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography sx={{ fontSize: 14 }} color="text.secondary">{t("candidates.names.intro", { name: candidate.full_name ?? "" })}</Typography>
          {parts?.source === "resume" && <Alert severity="info">{t("candidates.names.from_resume")}</Alert>}
          {parts?.source === "none" && <Alert severity="warning">{t("candidates.names.unknown")}</Alert>}
          <TextField label={t("candidates.names.first")} value={first} onChange={(e) => setFirst(e.target.value)} required inputProps={{ maxLength: 120 }} />
          <TextField label={t("candidates.names.last")} value={last} onChange={(e) => setLast(e.target.value)} inputProps={{ maxLength: 120 }} />
          <Button onClick={swap} sx={{ alignSelf: "flex-start" }}>{t("candidates.names.swap")}</Button>
          <TextField label={t("candidates.names.preferred")} value={preferred} onChange={(e) => setPreferred(e.target.value)}
            helperText={t("candidates.names.preferred_hint")} inputProps={{ maxLength: 120 }} />
          {problem && <Alert severity="error">{problem}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>{t("candidates.names.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={busy || !first.trim()}>{busy ? t("candidates.names.saving") : t("candidates.names.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}
