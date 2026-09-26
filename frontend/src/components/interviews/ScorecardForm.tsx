import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Rating from "@mui/material/Rating";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { schedulingApi } from "../../api/client";
import type { InterviewFeedbackUpdate } from "../../api/types";
import { useT } from "../../i18n";
import Emoji from "../../ui-kit/Emoji";
import FriendlyError from "../../ui-kit/FriendlyError";
import InfoTip from "../../ui-kit/InfoTip";
import ConfirmDialog from "../ConfirmDialog";
import AiQuestionsSection from "./AiQuestionsSection";
import PanelFeedbackSection from "./PanelFeedbackSection";

type Decision = "" | "selected" | "rejected";
type Competency = "technical_rating" | "communication_rating" | "overall_rating";

interface ScoreState {
  technical_rating: number | null;
  communication_rating: number | null;
  overall_rating: number | null;
  comments: string;
  decision: Decision;
}

const EMPTY: ScoreState = { technical_rating: null, communication_rating: null, overall_rating: null, comments: "", decision: "" };

const COMPETENCIES: { key: Competency; label: string; emoji: string }[] = [
  { key: "technical_rating", label: "technical", emoji: "technologist" },
  { key: "communication_rating", label: "communication", emoji: "speech" },
  { key: "overall_rating", label: "overall", emoji: "star" },
];

// Spec I3/I6/I7: the interview scorecard -- competency ratings (1-5 stars) + ONE comment +
// the decision, with the AI question ideas and the rest of the panel's feedback inside it.
// Same PATCH /interviews/{id}/feedback call and "final decision" confirmation the old
// Record Feedback dialog had; it starts pre-filled with whatever was already recorded.
export default function ScorecardForm({
  interviewId,
  applicationId,
  candidateLabel,
  onSaved,
  onCancel,
}: {
  interviewId: string;
  applicationId: string | null;
  candidateLabel: string;
  onSaved: () => void;
  onCancel?: () => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [form, setForm] = useState<ScoreState>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [resolvedApplicationId, setResolvedApplicationId] = useState<string | null>(applicationId);
  const [savedCount, setSavedCount] = useState(0);

  const load = () => {
    setForm(EMPTY);
    setLoadError(null);
    setSaveError(null);
    setLoading(true);
    schedulingApi
      .get(interviewId)
      .then((interview) => {
        setResolvedApplicationId(interview.application_id);
        setForm({
          technical_rating: interview.technical_rating ?? null,
          communication_rating: interview.communication_rating ?? null,
          overall_rating: interview.overall_rating ?? null,
          comments: interview.comments ?? "",
          decision: (interview.decision as Decision | null) ?? "",
        });
      })
      .catch(setLoadError)
      .finally(() => setLoading(false));
  };

  useEffect(load, [interviewId]); // eslint-disable-line react-hooks/exhaustive-deps

  const doSubmit = async () => {
    setConfirmOpen(false);
    setSaving(true);
    setSaveError(null);
    const payload: InterviewFeedbackUpdate = {
      technical_rating: form.technical_rating,
      communication_rating: form.communication_rating,
      overall_rating: form.overall_rating,
      comments: form.comments || null,
      decision: form.decision || null,
    };
    try {
      await schedulingApi.submitFeedback(interviewId, payload);
      setSavedCount((n) => n + 1);
      onSaved();
    } catch (err) {
      setSaveError(err);
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

  if (loading) {
    return (
      <Stack alignItems="center" py={4} role="status" aria-label={t("interviews.score.loading")}>
        <CircularProgress size={28} />
      </Stack>
    );
  }
  if (loadError) return <FriendlyError error={loadError} onRetry={load} compact />;

  return (
    <Stack spacing={2.5}>
      {saveError ? <FriendlyError error={saveError} compact /> : null}

      <Box component="fieldset" sx={{ border: 0, p: 0, m: 0 }}>
        <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 1 }}>
          <Typography component="legend" sx={{ fontWeight: 700 }}>{t("interviews.score.ratings")}</Typography>
          <InfoTip text={t("interviews.score.ratings_info")} />
        </Stack>
        <Stack spacing={1}>
          {COMPETENCIES.map((c) => {
            const label = t(`interviews.score.${c.label}`);
            return (
              <Stack key={c.key} direction="row" spacing={1.5} alignItems="center" justifyContent="space-between"
                sx={{ px: 1.5, py: 1, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
                  <Emoji name={c.emoji} size={20} />
                  <Typography id={`score-${c.key}-${interviewId}`} sx={{ fontWeight: 600 }}>{label}</Typography>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Rating
                    name={`${c.key}-${interviewId}`}
                    value={form[c.key]}
                    onChange={(_e, v) => setForm({ ...form, [c.key]: v })}
                    aria-labelledby={`score-${c.key}-${interviewId}`}
                    getLabelText={(v) => t("interviews.score.stars", { count: v })}
                  />
                  <Typography sx={{ fontSize: 12, color: f.muted, minWidth: 56, fontVariantNumeric: "tabular-nums" }}>
                    {form[c.key] ? t("interviews.score.out_of", { value: form[c.key] as number }) : t("interviews.score.not_rated")}
                  </Typography>
                </Stack>
              </Stack>
            );
          })}
        </Stack>
      </Box>

      <TextField
        label={t("interviews.score.comment")}
        placeholder={t("interviews.score.comment_hint")}
        value={form.comments}
        onChange={(e) => setForm({ ...form, comments: e.target.value })}
        fullWidth
        multiline
        minRows={3}
      />

      <Box>
        <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 1 }}>
          <Typography sx={{ fontWeight: 700 }} id={`decision-${interviewId}`}>{t("interviews.score.decision")}</Typography>
          <InfoTip text={t("interviews.score.decision_info")} />
        </Stack>
        <ToggleButtonGroup
          exclusive
          value={form.decision}
          onChange={(_e, v: Decision | null) => setForm({ ...form, decision: v ?? "" })}
          aria-labelledby={`decision-${interviewId}`}
          sx={{ flexWrap: "wrap", gap: 1, "& .MuiToggleButton-root": { borderRadius: "11px !important", border: `1px solid ${f.line} !important`, px: 2, textTransform: "none", fontWeight: 700 } }}
        >
          <ToggleButton value="">
            <Emoji name="hourglass" size={16} />&nbsp;{t("interviews.decision.later")}
          </ToggleButton>
          <ToggleButton value="selected" sx={{ "&.Mui-selected": { bgcolor: f.okSoft, color: f.ok } }}>
            <Emoji name="thumbs_up" size={16} />&nbsp;{t("interviews.decision.selected")}
          </ToggleButton>
          <ToggleButton value="rejected" sx={{ "&.Mui-selected": { bgcolor: f.coralSoft, color: f.coral } }}>
            <Emoji name="cross" size={16} />&nbsp;{t("interviews.decision.rejected")}
          </ToggleButton>
        </ToggleButtonGroup>
      </Box>

      <Stack direction="row" spacing={1} justifyContent="flex-end">
        {onCancel && (
          <Button onClick={onCancel} disabled={saving}>
            {t("action.cancel")}
          </Button>
        )}
        <Button variant="contained" onClick={handleSubmit} disabled={saving}>
          {saving ? t("interviews.score.saving") : t("interviews.score.save")}
        </Button>
      </Stack>

      <PanelFeedbackSection interviewId={interviewId} refreshKey={savedCount} />
      {resolvedApplicationId && <AiQuestionsSection applicationId={resolvedApplicationId} />}

      <ConfirmDialog
        open={confirmOpen}
        title={t("interviews.score.confirm_title")}
        message={t("interviews.score.confirm_message", {
          name: candidateLabel,
          decision: form.decision ? t(`interviews.decision.${form.decision}`) : "",
        })}
        confirmLabel={t("interviews.score.confirm_button")}
        cancelLabel={t("action.cancel")}
        destructive={form.decision === "rejected"}
        confirming={saving}
        onConfirm={doSubmit}
        onCancel={() => setConfirmOpen(false)}
      />
    </Stack>
  );
}
