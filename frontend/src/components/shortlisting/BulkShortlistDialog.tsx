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
import { REASON_OPTIONS } from "../ShortlistStatusPanel";

// Shortlist a selected batch: reason optional, note optional (same as the page had before 17.6).
export default function BulkShortlistDialog({
  open, people, submitting, onCancel, onConfirm,
}: {
  open: boolean;
  people: { id: string; name: string; job?: string }[];
  submitting: boolean;
  onCancel: () => void;
  onConfirm: (reason: string, feedback: string) => void;
}) {
  const t = useT();
  const [reason, setReason] = useState("");
  const [feedback, setFeedback] = useState("");
  useEffect(() => {
    if (open) {
      setReason("");
      setFeedback("");
    }
  }, [open]);

  return (
    <Dialog open={open} onClose={() => (submitting ? null : onCancel())} fullWidth maxWidth="sm" aria-labelledby="bulk-shortlist-title">
      <DialogTitle id="bulk-shortlist-title">{t("shortlisting.bulk.title", { count: people.length })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          <Typography variant="body2" color="text.secondary">{t("shortlisting.bulk.applies_to")}</Typography>
          <Box sx={{ maxHeight: 200, overflowY: "auto" }}>
            <Stack spacing={0.75} divider={<Divider />}>
              {people.map((p) => (
                <Stack key={p.id} direction="row" justifyContent="space-between" gap={2}>
                  <Typography variant="body2">{p.name}</Typography>
                  <Typography variant="body2" color="text.secondary">{p.job}</Typography>
                </Stack>
              ))}
            </Stack>
          </Box>
          <TextField select label={t("shortlisting.panel.reason_optional")} size="small" value={reason} onChange={(e) => setReason(e.target.value)} fullWidth>
            <MenuItem value="">{t("shortlisting.panel.no_reason")}</MenuItem>
            {REASON_OPTIONS.map((option) => (
              <MenuItem key={option} value={option}>{option}</MenuItem>
            ))}
          </TextField>
          <TextField
            label={t("shortlisting.bulk.feedback")}
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
          color="success"
          onClick={() => onConfirm(reason, feedback)}
          disabled={submitting}
          startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : undefined}
        >
          {submitting ? t("screening.saving") : t("shortlisting.bulk.confirm", { count: people.length })}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
