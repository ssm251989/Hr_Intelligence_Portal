import { useEffect, useState } from "react";
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

import { http } from "../../api/client";
import { useT } from "../../i18n";
import { FriendlyError, InfoTip } from "../../ui-kit";

// Adds a person to the employee list (existing POST /api/v1/core-hr/employees). The employee
// number is given automatically. Job details are added afterwards from their profile.

const WORKER_TYPES = ["employee", "contractor", "intern", "consultant", "gig"];
const START_STATUSES = ["pre_hire", "active"];
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function AddPersonDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const t = useT();
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [type, setType] = useState("employee");
  const [status, setStatus] = useState("pre_hire");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (open) {
      setFirst(""); setLast(""); setEmail(""); setPhone(""); setType("employee"); setStatus("pre_hire"); setError(null);
    }
  }, [open]);

  const badEmail = Boolean(email.trim()) && !EMAIL_RE.test(email.trim());
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const row = await http.post<{ id: string }>("/api/v1/core-hr/employees", {
        first_name: first.trim(), last_name: last.trim() || undefined, personal_email: email.trim() || undefined,
        personal_phone: phone.trim() || undefined, worker_type: type, status,
      });
      onCreated(row.id);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("people.add.title")}</DialogTitle>
      <DialogContent>
        <Typography sx={{ mb: 2, fontSize: 14 }}>{t("people.add.intro")}</Typography>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField autoFocus required fullWidth label={t("people.field.first_name")} value={first} onChange={(e) => setFirst(e.target.value)} placeholder={t("people.add.first_placeholder")} helperText={t("people.add.first_hint")} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField fullWidth label={t("people.field.last_name")} value={last} onChange={(e) => setLast(e.target.value)} placeholder={t("people.add.last_placeholder")} helperText={t("people.add.last_hint")} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField fullWidth type="email" label={t("people.field.personal_email")} value={email} onChange={(e) => setEmail(e.target.value)} error={badEmail}
              placeholder={t("people.add.email_placeholder")} helperText={badEmail ? t("people.add.email_invalid") : t("people.add.email_hint")} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField fullWidth type="tel" label={t("people.field.phone")} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder={t("people.add.phone_placeholder")} helperText={t("people.add.phone_hint")} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select fullWidth label={t("people.field.worker_type")} value={type} onChange={(e) => setType(e.target.value)} helperText={t("people.add.type_hint")}
              slotProps={{ input: { endAdornment: <InfoTip text={t("people.field.worker_type_tip")} /> } }}>
              {WORKER_TYPES.map((k) => <MenuItem key={k} value={k}>{t(`people.worker.${k}`)}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select fullWidth label={t("people.field.status")} value={status} onChange={(e) => setStatus(e.target.value)} helperText={t("people.add.status_hint")}>
              {START_STATUSES.map((k) => <MenuItem key={k} value={k}>{t(`people.status.${k}`)}</MenuItem>)}
            </TextField>
          </Grid>
        </Grid>
        {error != null && <Box sx={{ mt: 2 }}><FriendlyError compact error={error} what={t("people.add.failed")} /></Box>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={busy || !first.trim() || badEmail}>{busy ? t("people.saving") : t("people.add.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}
