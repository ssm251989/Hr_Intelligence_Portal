import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { extractErrorMessage, schedulingApi } from "../api/client";
import type { InterviewFeedbackUpdate } from "../api/types";
import ConfirmDialog from "./ConfirmDialog";

interface FeedbackFormState {
  technical_rating: string;
  communication_rating: string;
  overall_rating: string;
  comments: string;
  decision: "" | "selected" | "rejected";
}

const EMPTY_FORM: FeedbackFormState = {
  technical_rating: "",
  communication_rating: "",
  overall_rating: "",
  comments: "",
  decision: "",
};

// Record Feedback, extracted out of the old InterviewsPage's InterviewFeedbackForm so the
// Interview List's row action reuses the exact same PATCH /interviews/{id}/feedback logic
// rather than a second copy of it. Fetches the full interview (ratings/comments/decision
// aren't part of the list row) when opened, so the form starts pre-filled with whatever
// was already recorded.
export default function InterviewFeedbackDialog({
  interviewId,
  candidateLabel,
  onClose,
  onSaved,
}: {
  interviewId: string | null;
  candidateLabel: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<FeedbackFormState>(EMPTY_FORM);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    if (!interviewId) return;
    setForm(EMPTY_FORM);
    setError(null);
    setLoading(true);
    schedulingApi
      .get(interviewId)
      .then((interview) =>
        setForm({
          technical_rating: interview.technical_rating?.toString() ?? "",
          communication_rating: interview.communication_rating?.toString() ?? "",
          overall_rating: interview.overall_rating?.toString() ?? "",
          comments: interview.comments ?? "",
          decision: (interview.decision as "selected" | "rejected" | null) ?? "",
        })
      )
      .catch((err) => setError(extractErrorMessage(err, "Failed to load interview")))
      .finally(() => setLoading(false));
  }, [interviewId]);

  const doSubmit = async () => {
    if (!interviewId) return;
    setConfirmOpen(false);
    setSaving(true);
    setError(null);
    const payload: InterviewFeedbackUpdate = {
      technical_rating: form.technical_rating ? Number(form.technical_rating) : null,
      communication_rating: form.communication_rating ? Number(form.communication_rating) : null,
      overall_rating: form.overall_rating ? Number(form.overall_rating) : null,
      comments: form.comments || null,
      decision: form.decision || null,
    };
    try {
      await schedulingApi.submitFeedback(interviewId, payload);
      onSaved();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to save feedback"));
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = () => {
    if (form.decision) {
      setConfirmOpen(true);
      return;
    }
    doSubmit();
  };

  const ratingField = (label: string, key: "technical_rating" | "communication_rating" | "overall_rating") => (
    <TextField
      select
      label={label}
      value={form[key]}
      onChange={(e) => setForm({ ...form, [key]: e.target.value })}
      size="small"
      sx={{ minWidth: 140 }}
    >
      <MenuItem value="">—</MenuItem>
      {[1, 2, 3, 4, 5].map((n) => (
        <MenuItem key={n} value={n}>
          {n}
        </MenuItem>
      ))}
    </TextField>
  );

  return (
    <>
      <Dialog open={interviewId != null} onClose={onClose} fullWidth maxWidth="sm">
        <DialogTitle>Record Feedback — {candidateLabel}</DialogTitle>
        <DialogContent>
          {loading ? (
            <Stack alignItems="center" py={4}>
              <CircularProgress size={28} />
            </Stack>
          ) : (
            <Stack spacing={2} mt={1}>
              {error && <Alert severity="error">{error}</Alert>}
              <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                {ratingField("Technical", "technical_rating")}
                {ratingField("Communication", "communication_rating")}
                {ratingField("Overall", "overall_rating")}
                <TextField
                  select
                  label="Decision"
                  value={form.decision}
                  onChange={(e) => setForm({ ...form, decision: e.target.value as FeedbackFormState["decision"] })}
                  size="small"
                  sx={{ minWidth: 140 }}
                >
                  <MenuItem value="">—</MenuItem>
                  <MenuItem value="selected">Selected</MenuItem>
                  <MenuItem value="rejected">Rejected</MenuItem>
                </TextField>
              </Stack>
              <TextField
                label="Comments"
                value={form.comments}
                onChange={(e) => setForm({ ...form, comments: e.target.value })}
                fullWidth
                multiline
                minRows={2}
              />
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="contained" onClick={handleSubmit} disabled={loading || saving}>
            {saving ? "Saving..." : "Save Feedback"}
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={confirmOpen}
        title="Save final decision?"
        message={`Record this interview's decision as "${form.decision}"? This moves the application to the next stage and cannot be undone.`}
        confirmLabel="Save Decision"
        destructive={form.decision === "rejected"}
        confirming={saving}
        onConfirm={doSubmit}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
