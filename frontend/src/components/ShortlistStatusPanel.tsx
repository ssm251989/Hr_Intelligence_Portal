import { useState } from "react";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { shortlistingApi } from "../api/client";
import { shortlistStatusOf, type ApplicationRead, type ShortlistStatus, type UUID } from "../api/types";
import { useT } from "../i18n";
import { FriendlyError, InfoTip, StageStepper } from "../ui-kit";
import { useRejectReasons } from "./screening/hooks";

// A reasonable starter list, extensible -- the optional "why" for shortlisting / pausing.
// Exported so the List page's bulk-decision dialog offers the exact same options.
// (Turning someone down uses the company's Rejection Reason list instead -- S7.)
export const REASON_OPTIONS = [
  "Move to Interview",
  "Strong technical fit",
  "Needs more experience",
  "Cultural fit concerns",
  "Salary expectations mismatch",
  "Not a match for this role",
  "Other",
];

// Fixed left-to-right display order for the stepper -- a visual "where is this candidate
// right now" indicator, not a literal linear flow (the real valid transitions branch; see
// app/shortlisting/service.py). The actual next-state actions are the buttons below it.
const STEP_ORDER: ShortlistStatus[] = ["under_review", "on_hold", "shortlisted", "not_shortlisted"];

interface Props {
  applicationId: UUID;
  candidateName?: string | null;
  currentApplicationStatus: string;
  onSaved: (updated: ApplicationRead) => void;
}

export default function ShortlistStatusPanel({ applicationId, candidateName, currentApplicationStatus, onSaved }: Props) {
  const t = useT();
  const { reasons: rejectReasons, loading: reasonsLoading } = useRejectReasons(t);
  const [reason, setReason] = useState("");
  const [rejectCode, setRejectCode] = useState("");
  const [feedback, setFeedback] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [saving, setSaving] = useState<ShortlistStatus | null>(null);
  const [error, setError] = useState<unknown>(null);

  const currentShortlistStatus = shortlistStatusOf(currentApplicationStatus);
  const activeStep = currentShortlistStatus ? STEP_ORDER.indexOf(currentShortlistStatus) : -1;
  const isTerminal = currentShortlistStatus === "shortlisted" || currentShortlistStatus === "not_shortlisted";
  const rejectReason = rejectReasons.find((r) => r.code === rejectCode);

  const validTargets: ShortlistStatus[] =
    currentShortlistStatus === "under_review"
      ? ["shortlisted", "on_hold", "not_shortlisted"]
      : currentShortlistStatus === "on_hold"
        ? ["under_review", "shortlisted", "not_shortlisted"]
        : [];

  const handleSuggest = async () => {
    setSuggesting(true);
    setError(null);
    try {
      const result = await shortlistingApi.suggestFeedback(applicationId);
      setFeedback(result.suggested_feedback);
    } catch (err) {
      setError(err);
    } finally {
      setSuggesting(false);
    }
  };

  const handleSave = async (target: ShortlistStatus) => {
    const chosenReason = target === "not_shortlisted" ? rejectReason?.value ?? "" : reason;
    if (target === "not_shortlisted" && !chosenReason) return;
    setSaving(target);
    setError(null);
    try {
      const updated = await shortlistingApi.updateStatus(applicationId, {
        target_status: target,
        reason: chosenReason || null,
        feedback: feedback || null,
      });
      onSaved(updated);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(null);
    }
  };

  if (currentShortlistStatus == null) {
    return <Alert severity="info">{t("shortlisting.panel.not_in_stage", { name: candidateName || t("shortlisting.panel.this_candidate") })}</Alert>;
  }

  const buttonLabel = (target: ShortlistStatus) =>
    saving === target ? t("screening.saving") : t(`shortlisting.panel.save_as.${target}`);

  return (
    <Stack spacing={2.5}>
      <StageStepper stages={STEP_ORDER.map((s) => t(`shortlisting.status.${s}`))} current={activeStep} />

      {error != null && <FriendlyError error={error} compact />}

      {isTerminal ? (
        <Alert severity="success">{t("shortlisting.panel.final", { status: t(`shortlisting.status.${currentShortlistStatus}`) })}</Alert>
      ) : (
        <>
          <TextField
            select
            label={t("shortlisting.panel.reason_optional")}
            size="small"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            fullWidth
          >
            <MenuItem value="">{t("shortlisting.panel.no_reason")}</MenuItem>
            {REASON_OPTIONS.map((option) => (
              <MenuItem key={option} value={option}>
                {option}
              </MenuItem>
            ))}
          </TextField>

          <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="subtitle2">{t("shortlisting.panel.feedback")}</Typography>
              <Button
                size="small"
                startIcon={suggesting ? <CircularProgress size={14} /> : <AutoAwesomeOutlinedIcon fontSize="small" />}
                onClick={handleSuggest}
                disabled={suggesting}
              >
                {suggesting ? t("shortlisting.panel.suggesting") : t("shortlisting.panel.suggest")}
              </Button>
            </Stack>
            <TextField
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              fullWidth
              multiline
              minRows={4}
              placeholder={t("shortlisting.panel.feedback_placeholder")}
              slotProps={{ htmlInput: { "aria-label": t("shortlisting.panel.feedback") } }}
            />
            <Typography variant="caption" color="text.secondary">{t("shortlisting.panel.suggest_hint")}</Typography>
          </Box>

          <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
            {validTargets
              .filter((target) => target !== "not_shortlisted")
              .map((target) => (
                <Button
                  key={target}
                  variant="contained"
                  color={target === "on_hold" ? "warning" : "primary"}
                  onClick={() => handleSave(target)}
                  disabled={saving != null}
                >
                  {buttonLabel(target)}
                </Button>
              ))}
          </Stack>

          {validTargets.includes("not_shortlisted") && (
            <Box sx={{ borderTop: 1, borderColor: "divider", pt: 2 }}>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "flex-start" }}>
                <Stack direction="row" alignItems="flex-start" spacing={0.5} sx={{ flex: 1 }}>
                  <TextField
                    select
                    required
                    size="small"
                    fullWidth
                    label={t("shortlisting.reject.reason")}
                    value={rejectCode}
                    onChange={(e) => setRejectCode(e.target.value)}
                    disabled={reasonsLoading}
                    helperText={t("shortlisting.reject.reason_hint")}
                  >
                    {rejectReasons.map((r) => (
                      <MenuItem key={r.code} value={r.code}>{r.label}</MenuItem>
                    ))}
                  </TextField>
                  <Box pt={0.75}><InfoTip text={t("shortlisting.reject.reason_info")} label={t("screening.whats_this")} /></Box>
                </Stack>
                <Button
                  variant="outlined"
                  color="error"
                  onClick={() => handleSave("not_shortlisted")}
                  disabled={saving != null || !rejectReason}
                >
                  {buttonLabel("not_shortlisted")}
                </Button>
              </Stack>
            </Box>
          )}
        </>
      )}
    </Stack>
  );
}
