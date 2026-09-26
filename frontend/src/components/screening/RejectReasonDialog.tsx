import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { useT } from "../../i18n";
import { InfoTip } from "../../ui-kit";
import { useRejectReasons } from "./hooks";

// S7: turning a candidate down always needs a reason from the company's Rejection Reason
// list. Used for one candidate and for a selected batch.
export default function RejectReasonDialog({
  open, people, submitting, onCancel, onConfirm,
}: {
  open: boolean;
  /** Who this applies to: [name, job title]. */
  people: { id: string; name: string; job?: string }[];
  submitting: boolean;
  onCancel: () => void;
  onConfirm: (reason: string, feedback: string) => void;
}) {
  const t = useT();
  const { reasons, loading } = useRejectReasons(t);
  const [code, setCode] = useState("");
  const [feedback, setFeedback] = useState("");
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (open) {
      setCode("");
      setFeedback("");
      setTouched(false);
    }
  }, [open]);

  const chosen = reasons.find((r) => r.code === code);
  const missing = !chosen;

  return (
    <Dialog open={open} onClose={() => (submitting ? null : onCancel())} fullWidth maxWidth="sm" aria-labelledby="reject-title">
      <DialogTitle id="reject-title">{t("shortlisting.reject.title", { count: people.length })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          {people.length > 1 && (
            <>
              <Typography variant="body2" color="text.secondary">{t("shortlisting.bulk.applies_to")}</Typography>
              <Box sx={{ maxHeight: 180, overflowY: "auto" }}>
                <Stack spacing={0.75} divider={<Divider />}>
                  {people.map((p) => (
                    <Stack key={p.id} direction="row" justifyContent="space-between" gap={2}>
                      <Typography variant="body2">{p.name}</Typography>
                      <Typography variant="body2" color="text.secondary">{p.job}</Typography>
                    </Stack>
                  ))}
                </Stack>
              </Box>
            </>
          )}
          {people.length === 1 && <Typography variant="body2">{t("shortlisting.reject.one", { name: people[0].name })}</Typography>}

          <Stack direction="row" alignItems="flex-start" spacing={0.5}>
            <TextField
              select
              required
              label={t("shortlisting.reject.reason")}
              size="small"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              onBlur={() => setTouched(true)}
              fullWidth
              disabled={loading}
              error={touched && missing}
              helperText={touched && missing ? t("shortlisting.reject.reason_needed") : t("shortlisting.reject.reason_hint")}
            >
              {reasons.map((r) => (
                <MenuItem key={r.code} value={r.code}>{r.label}</MenuItem>
              ))}
            </TextField>
            <Box pt={0.75}><InfoTip text={t("shortlisting.reject.reason_info")} label={t("screening.whats_this")} /></Box>
          </Stack>

          <TextField
            label={t("shortlisting.feedback_optional")}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            fullWidth
            multiline
            minRows={3}
            placeholder={t("shortlisting.feedback_placeholder")}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel} disabled={submitting}>{t("action.cancel")}</Button>
        <Button
          variant="contained"
          color="error"
          disabled={submitting || missing}
          onClick={() => chosen && onConfirm(chosen.value, feedback)}
          startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : undefined}
        >
          {submitting ? t("screening.saving") : t("shortlisting.reject.confirm", { count: people.length })}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
