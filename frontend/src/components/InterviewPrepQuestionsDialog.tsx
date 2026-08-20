import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, schedulingApi } from "../api/client";
import type { InterviewQuestionsResponse } from "../api/types";

// Generate Prep Questions, carried over from the old InterviewsPage so this capability
// (POST /applications/{id}/interview-questions) doesn't quietly disappear from the UI in
// the redesign -- same AI call, just reachable from the Interview List's row menu instead
// of a per-job card.
export default function InterviewPrepQuestionsDialog({
  applicationId,
  candidateLabel,
  onClose,
}: {
  applicationId: string | null;
  candidateLabel: string;
  onClose: () => void;
}) {
  const [questions, setQuestions] = useState<InterviewQuestionsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!applicationId) return;
    setQuestions(null);
    setError(null);
    setLoading(true);
    schedulingApi
      .generateQuestions(applicationId)
      .then(setQuestions)
      .catch((err) => setError(extractErrorMessage(err, "Failed to generate interview questions")))
      .finally(() => setLoading(false));
  }, [applicationId]);

  const renderList = (title: string, items: string[]) => (
    <Stack spacing={0.5} mb={2}>
      <Typography variant="subtitle2">{title}</Typography>
      {items.map((q, idx) => (
        <Typography variant="body2" key={idx}>
          • {q}
        </Typography>
      ))}
    </Stack>
  );

  return (
    <Dialog open={applicationId != null} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Interview Prep Questions — {candidateLabel}</DialogTitle>
      <DialogContent>
        {loading ? (
          <Stack alignItems="center" py={4}>
            <CircularProgress size={28} />
          </Stack>
        ) : error ? (
          <Alert severity="error">{error}</Alert>
        ) : questions ? (
          <Stack mt={1}>
            {renderList("Technical Questions", questions.technical_questions)}
            {renderList("Behavioral Questions", questions.behavioral_questions)}
            {renderList("Questions to Probe Gaps", questions.questions_to_probe_gaps)}
          </Stack>
        ) : null}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
