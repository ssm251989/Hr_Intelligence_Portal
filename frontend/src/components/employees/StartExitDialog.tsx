// Part 20.3: HR starts an exit from the Employees list / profile -- Resigned, Terminated, Absconded (emails the
// absconding notice), Retirement, Contract end. No manager step: HR decides. Optionally confirms the last day now,
// which starts the exit checklist.
import { useState } from "react";
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
import { useNavigate } from "react-router-dom";

import { extractErrorMessage } from "../../api/client";
import type { EmployeeRow } from "../../api/employeesApi";
import { selfServiceApi, type StartExitKind } from "../../api/selfServiceApi";
import { useT } from "../../i18n";

const KINDS: StartExitKind[] = ["resigned", "terminated", "absconded", "retirement", "contract_end"];

export default function StartExitDialog({ row, onClose, onToast }: { row: EmployeeRow; onClose: () => void; onToast: (m: string) => void }) {
  const t = useT();
  const nav = useNavigate();
  const today = new Date().toISOString().slice(0, 10);
  const [kind, setKind] = useState<StartExitKind>("resigned");
  const [lwd, setLwd] = useState(today);
  const [notes, setNotes] = useState("");
  const [confirmNow, setConfirmNow] = useState(true);
  const [sendNotice, setSendNotice] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await selfServiceApi.startExit(row.id, { kind, last_working_day: lwd, notes, confirm_now: confirmNow, send_notice: kind === "absconded" && sendNotice });
      onToast(t("emp.exit.started"));
      onClose();
      nav(`/exits?open=${r.separation_id}`);
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm" aria-labelledby="emp-exit-title">
      <DialogTitle id="emp-exit-title">{t("emp.exit.title", { name: row.name })}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={1.75}>
          <TextField select label={t("emp.exit.kind")} value={kind} onChange={(e) => setKind(e.target.value as StartExitKind)}>
            {KINDS.map((k) => <MenuItem key={k} value={k}>{t(`emp.exit.kind.${k}`)}</MenuItem>)}
          </TextField>
          <TextField type="date" label={t("emp.exit.lwd")} value={lwd} onChange={(e) => setLwd(e.target.value)} InputLabelProps={{ shrink: true }}
            helperText={t(kind === "absconded" ? "emp.exit.lwd_absconded" : "emp.exit.lwd_hint")} inputProps={kind === "absconded" ? { max: today } : undefined} />
          <TextField label={t("emp.exit.notes")} placeholder={t("emp.exit.notes_ph")} value={notes} onChange={(e) => setNotes(e.target.value)} multiline minRows={3} required />
          <FormControlLabel control={<Checkbox checked={confirmNow} onChange={(e) => setConfirmNow(e.target.checked)} />} label={t("emp.exit.confirm_now")} />
          {kind === "absconded" && (
            <FormControlLabel control={<Checkbox checked={sendNotice} onChange={(e) => setSendNotice(e.target.checked)} />} label={t("emp.exit.send_notice")} />
          )}
          <Typography sx={{ fontSize: 13, color: "text.secondary" }}>{t("emp.exit.hint")}</Typography>
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" color="error" onClick={go} disabled={busy || notes.trim().length < 3}>{t("emp.exit.go")}</Button>
      </DialogActions>
    </Dialog>
  );
}
