import { useEffect, useState } from "react";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { schedulingApi } from "../api/client";
import type { InterviewQuestionsResponse } from "../api/types";
import { useT } from "../i18n";
import Emoji from "../ui-kit/Emoji";
import FriendlyError from "../ui-kit/FriendlyError";
import { QuestionGroups } from "./interviews/AiQuestionsSection";

// AI question ideas for one candidate (POST /applications/{id}/interview-questions) -- the
// Interview List's row action. The same questions also appear inside the scorecard.
export default function InterviewPrepQuestionsDialog({
  applicationId,
  candidateLabel,
  onClose,
}: {
  applicationId: string | null;
  candidateLabel: string;
  onClose: () => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [questions, setQuestions] = useState<InterviewQuestionsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const load = () => {
    if (!applicationId) return;
    setQuestions(null);
    setError(null);
    setLoading(true);
    schedulingApi
      .generateQuestions(applicationId)
      .then(setQuestions)
      .catch(setError)
      .finally(() => setLoading(false));
  };

  useEffect(load, [applicationId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Dialog open={applicationId != null} onClose={onClose} fullWidth maxWidth="sm" aria-labelledby="prep-questions-title">
      <DialogTitle id="prep-questions-title">
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Emoji name="sparkles" size={24} />
          <span>
            {t("interviews.ai.dialog_title")}
            <Typography component="span" sx={{ display: "block", color: f.muted, fontSize: 14, fontWeight: 500 }}>
              {candidateLabel}
            </Typography>
          </span>
        </Stack>
      </DialogTitle>
      <DialogContent>
        {loading ? (
          <Stack alignItems="center" spacing={1.5} py={4} role="status">
            <CircularProgress size={28} />
            <Typography sx={{ color: f.muted }}>{t("interviews.ai.loading")}</Typography>
          </Stack>
        ) : error ? (
          <FriendlyError error={error} onRetry={load} compact />
        ) : questions ? (
          <Stack mt={1}>
            <QuestionGroups questions={questions} />
          </Stack>
        ) : null}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.close")}</Button>
      </DialogActions>
    </Dialog>
  );
}
