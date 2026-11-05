import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { schedulingApi } from "../../api/client";
import type { InterviewQuestionsResponse } from "../../api/types";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";
import Emoji from "../../ui-kit/Emoji";
import FriendlyError from "../../ui-kit/FriendlyError";
import InfoTip from "../../ui-kit/InfoTip";

export const AI_INTERVIEW_FEATURE = "recruitment.interview_kit";

export function QuestionGroups({ questions }: { questions: InterviewQuestionsResponse }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const groups: [string, string, string[]][] = [
    ["technologist", t("interviews.ai.technical"), questions.technical_questions],
    ["speech", t("interviews.ai.behavioural"), questions.behavioral_questions],
    ["magnifier", t("interviews.ai.gaps"), questions.questions_to_probe_gaps],
  ];
  return (
    <Stack spacing={2}>
      {groups.map(([emoji, title, items]) =>
        items.length === 0 ? null : (
          <Box key={title}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Emoji name={emoji} size={18} />
              <Typography sx={{ fontWeight: 700 }}>{title}</Typography>
            </Stack>
            <Stack component="ol" spacing={0.75} sx={{ m: 0, pl: 0, listStyle: "none" }}>
              {items.map((q, idx) => (
                <Box component="li" key={idx} sx={{ fontSize: 14, px: 1.25, py: 1, bgcolor: f.surface2, borderLeft: `3px solid ${f.brand}`, borderRadius: "0 8px 8px 0" }}>
                  {q}
                </Box>
              ))}
            </Stack>
          </Box>
        ),
      )}
    </Stack>
  );
}

// Spec I7: AI interview questions shown INSIDE the scorecard -- same
// POST /applications/{id}/interview-questions call as the prep-questions dialog, asked for
// only when the interviewer clicks (it costs an AI call), and hidden entirely when the
// company has the interview-kit AI feature turned off.
export default function AiQuestionsSection({ applicationId }: { applicationId: string }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { aiFeature } = useMeBootstrap();
  const [questions, setQuestions] = useState<InterviewQuestionsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (!aiFeature(AI_INTERVIEW_FEATURE)) return null;

  const load = () => {
    setLoading(true);
    setError(null);
    schedulingApi
      .generateQuestions(applicationId)
      .then(setQuestions)
      .catch(setError)
      .finally(() => setLoading(false));
  };

  return (
    <Box component="section" aria-label={t("interviews.ai.title")} sx={{ p: 2, borderRadius: "14px", border: `1px dashed ${f.line}`, bgcolor: f.surface }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ xs: "flex-start", sm: "center" }} justifyContent="space-between" sx={{ mb: questions || error ? 2 : 0 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Emoji name="sparkles" size={20} />
          <Typography sx={{ fontWeight: 700 }}>{t("interviews.ai.title")}</Typography>
          <InfoTip text={t("interviews.ai.info")} />
        </Stack>
        <Button variant={questions ? "text" : "outlined"} onClick={load} disabled={loading} startIcon={loading ? <CircularProgress size={14} /> : undefined}>
          {loading ? t("interviews.ai.loading") : questions ? t("interviews.ai.again") : t("interviews.ai.suggest")}
        </Button>
      </Stack>
      {error ? <FriendlyError error={error} onRetry={load} compact /> : questions ? <QuestionGroups questions={questions} /> : null}
    </Box>
  );
}
