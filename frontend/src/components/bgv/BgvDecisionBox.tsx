import { useState } from "react";
import Alert from "@mui/material/Alert";
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

import { extractErrorMessage, http } from "../../api/client";
import { useT } from "../../i18n";

type Mode = "passed" | "resend" | "failed" | null;
const DOCS = ["pan", "aadhaar", "degree", "experience"];

// Part 18.18: HR decides BGV -- Passed / Resend form / Failed. Failed needs a reason and shows the
// email to the candidate first (editable). The system never fails BGV by itself.
export default function BgvDecisionBox({ applicationId, notAllValid, onDone }: { applicationId: string; notAllValid: boolean; onDone: () => void }) {
  const t = useT();
  const [mode, setMode] = useState<Mode>(null);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [codes, setCodes] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = (m: Mode) => { setMode(m); setError(null); setNote(""); setReason(""); setMessage(""); setCodes(new Set()); };
  const preview = async () => {
    try {
      const r = await http.get<{ message: string }>(`/api/v1/ui/bgv/${applicationId}/failed-preview?reason=${encodeURIComponent(reason)}`);
      setMessage(r.message);
    } catch (err) { setError(extractErrorMessage(err, t("bgvx.err"))); }
  };
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await http.post(`/api/v1/ui/bgv/${applicationId}/decide`, {
        decision: mode, note: note || null, reason: reason || null, message: mode === "failed" ? message || null : null, codes: Array.from(codes),
      });
      setMode(null);
      onDone();
    } catch (err) { setError(extractErrorMessage(err, t("bgvx.err"))); } finally { setBusy(false); }
  };

  return (
    <Box sx={{ mt: 2 }}>
      <Typography sx={{ fontWeight: 700, mb: 1 }}>{t("bgvx.title")}</Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        <Button variant="contained" color="success" onClick={() => open("passed")}>{t("bgvx.passed")}</Button>
        <Button variant="outlined" onClick={() => open("resend")}>{t("bgvx.resend")}</Button>
        <Button variant="outlined" color="error" onClick={() => open("failed")}>{t("bgvx.failed")}</Button>
      </Stack>
      <Dialog open={mode !== null} onClose={busy ? undefined : () => setMode(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{mode ? t(`bgvx.title_${mode}`) : ""}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ pt: 1 }}>
            {mode === "passed" && (notAllValid ? <Alert severity="warning">{t("bgvx.passed_warn")}</Alert> : <Alert severity="info">{t("bgvx.passed_info")}</Alert>)}
            {mode === "resend" && (
              <>
                <Typography variant="body2">{t("bgvx.resend_info")}</Typography>
                {DOCS.map((d) => (
                  <FormControlLabel key={d} label={t(`bgvx.doc.${d}`)}
                    control={<Checkbox checked={codes.has(d)} onChange={() => setCodes((s) => { const n = new Set(s); if (n.has(d)) n.delete(d); else n.add(d); return n; })} />} />
                ))}
                <TextField label={t("bgvx.note")} value={note} onChange={(e) => setNote(e.target.value)} multiline minRows={2} />
              </>
            )}
            {mode === "failed" && (
              <>
                <TextField label={t("bgvx.reason")} required value={reason} onChange={(e) => setReason(e.target.value)} multiline minRows={2} />
                <Button onClick={preview} disabled={!reason.trim()}>{t("bgvx.preview")}</Button>
                {message && <TextField label={t("bgvx.email")} value={message} onChange={(e) => setMessage(e.target.value)} multiline minRows={8} helperText={t("bgvx.email_hint")} />}
              </>
            )}
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMode(null)} disabled={busy}>{t("lock.cancel")}</Button>
          <Button variant="contained" color={mode === "failed" ? "error" : mode === "passed" ? "success" : "primary"} onClick={submit}
            disabled={busy || (mode === "resend" && codes.size === 0) || (mode === "failed" && (!reason.trim() || !message))}>
            {mode ? t(`bgvx.confirm_${mode}`) : ""}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
