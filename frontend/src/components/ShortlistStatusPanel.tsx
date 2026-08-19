import { useState } from "react";
import AutoAwesomeOutlinedIcon from "@mui/icons-material/AutoAwesomeOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Step from "@mui/material/Step";
import StepLabel from "@mui/material/StepLabel";
import Stepper from "@mui/material/Stepper";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, shortlistingApi } from "../api/client";
import { SHORTLIST_STATUS_LABELS, shortlistStatusOf, type ApplicationRead, type ShortlistStatus, type UUID } from "../api/types";

// A reasonable starter list, extensible -- not the full universe of reasons an evaluator
// might have, just the common ones with an "Other" escape hatch for free-text-only cases.
// Exported so the List page's bulk-decision dialog offers the exact same options, rather
// than a second, driftable copy of this list.
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
  const [reason, setReason] = useState("");
  const [feedback, setFeedback] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [saving, setSaving] = useState<ShortlistStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const currentShortlistStatus = shortlistStatusOf(currentApplicationStatus);
  const activeStep = currentShortlistStatus ? STEP_ORDER.indexOf(currentShortlistStatus) : -1;
  const isTerminal = currentShortlistStatus === "shortlisted" || currentShortlistStatus === "not_shortlisted";

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
      setError(extractErrorMessage(err, "Failed to generate an AI feedback suggestion"));
    } finally {
      setSuggesting(false);
    }
  };

  const handleSave = async (target: ShortlistStatus) => {
    setSaving(target);
    setError(null);
    try {
      const updated = await shortlistingApi.updateStatus(applicationId, {
        target_status: target,
        reason: reason || null,
        feedback: feedback || null,
      });
      onSaved(updated);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to update shortlist status"));
    } finally {
      setSaving(null);
    }
  };

  if (currentShortlistStatus == null) {
    return (
      <Alert severity="info">
        {candidateName || "This candidate"}'s application isn't currently in the shortlisting stage -- there's
        nothing to update here.
      </Alert>
    );
  }

  return (
    <Stack spacing={3}>
      <Stepper activeStep={activeStep} alternativeLabel>
        {STEP_ORDER.map((status) => (
          <Step key={status}>
            <StepLabel>{SHORTLIST_STATUS_LABELS[status]}</StepLabel>
          </Step>
        ))}
      </Stepper>

      {error && (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {isTerminal ? (
        <Alert severity="success">
          This decision is final -- {SHORTLIST_STATUS_LABELS[currentShortlistStatus]} is a terminal state, no
          further shortlisting status change is available.
        </Alert>
      ) : (
        <>
          <TextField
            select
            label="Reason / Recommendation"
            size="small"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            fullWidth
          >
            <MenuItem value="">No reason selected</MenuItem>
            {REASON_OPTIONS.map((option) => (
              <MenuItem key={option} value={option}>
                {option}
              </MenuItem>
            ))}
          </TextField>

          <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="subtitle2">Feedback</Typography>
              <Button
                size="small"
                startIcon={suggesting ? <CircularProgress size={14} /> : <AutoAwesomeOutlinedIcon fontSize="small" />}
                onClick={handleSuggest}
                disabled={suggesting}
              >
                {suggesting ? "Generating..." : "AI Suggestion"}
              </Button>
            </Stack>
            <TextField
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              fullWidth
              multiline
              minRows={4}
              placeholder="Evaluator feedback -- edit the AI suggestion above or write your own."
            />
            <Typography variant="caption" color="text.secondary">
              AI Suggestion drafts a starting point from this candidate's real screening data -- always review and
              edit before saving; it's never saved automatically.
            </Typography>
          </Box>

          <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
            {validTargets.map((target) => (
              <Button
                key={target}
                variant={target === "not_shortlisted" ? "outlined" : "contained"}
                color={target === "not_shortlisted" ? "error" : target === "on_hold" ? "warning" : "primary"}
                onClick={() => handleSave(target)}
                disabled={saving != null}
              >
                {saving === target ? "Saving..." : `Save as ${SHORTLIST_STATUS_LABELS[target]}`}
              </Button>
            ))}
          </Stack>
        </>
      )}
    </Stack>
  );
}
