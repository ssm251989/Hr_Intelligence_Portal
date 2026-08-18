import { useEffect, useState } from "react";
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, screeningApi } from "../api/client";
import type { ReEvaluateAllResult } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import ConfirmDialog from "./ConfirmDialog";

// Part D: the Candidates Dashboard's configurable auto-advance-to-'screened' threshold
// (app/models/screening_settings.py's singleton row) plus its bulk "Re-evaluate All"
// action. Saving the threshold here takes effect immediately for every future screening
// call -- new uploads and the manual Screen button alike, since run_screening always
// reads the current settings row rather than a value cached at some earlier point.
// Re-evaluate All is the only way to apply a changed threshold to *existing* candidates.
export default function ScreeningThresholdPanel() {
  const { can } = useAuth();
  const canManage = can(ROLE_MATRIX.screeningDecisions);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [minScore, setMinScore] = useState("");
  const [maxScore, setMaxScore] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reEvaluating, setReEvaluating] = useState(false);
  const [reEvalResult, setReEvalResult] = useState<ReEvaluateAllResult | null>(null);
  const [reEvalError, setReEvalError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    screeningApi
      .getSettings()
      .then((settings) => {
        setMinScore(String(settings.dashboard_min_score));
        setMaxScore(String(settings.dashboard_max_score));
      })
      .catch((err) => setLoadError(extractErrorMessage(err, "Failed to load screening settings")))
      .finally(() => setLoading(false));
  }, []);

  const minNum = Number(minScore);
  const maxNum = Number(maxScore);
  const valid =
    minScore !== "" &&
    maxScore !== "" &&
    !Number.isNaN(minNum) &&
    !Number.isNaN(maxNum) &&
    minNum >= 0 &&
    maxNum <= 100 &&
    minNum <= maxNum;

  const handleSave = () => {
    if (!valid) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    screeningApi
      .updateSettings({ dashboard_min_score: minNum, dashboard_max_score: maxNum })
      .then(() => setSaved(true))
      .catch((err) => setSaveError(extractErrorMessage(err, "Failed to save screening settings")))
      .finally(() => setSaving(false));
  };

  const handleReEvaluateAll = () => {
    setConfirmOpen(false);
    setReEvaluating(true);
    setReEvalError(null);
    setReEvalResult(null);
    screeningApi
      .reEvaluateAll()
      .then(setReEvalResult)
      .catch((err) => setReEvalError(extractErrorMessage(err, "Failed to re-evaluate candidates")))
      .finally(() => setReEvaluating(false));
  };

  if (loading) {
    return (
      <Card variant="outlined" sx={{ mb: 3 }}>
        <CardContent>
          <Skeleton variant="text" width="40%" height={32} sx={{ mb: 2 }} />
          <Skeleton variant="rounded" height={56} />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card variant="outlined" sx={{ mb: 3 }}>
      <CardContent>
        <Box mb={2}>
          <Typography variant="h6">Auto-Screening Threshold</Typography>
          <Typography variant="body2" color="text.secondary">
            Applications scoring at or above the minimum automatically advance to "Screened." Changes apply to new
            uploads right away -- use Re-evaluate All to apply the new threshold to existing candidates too.
          </Typography>
        </Box>

        {loadError && <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>}
        {saveError && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setSaveError(null)}>{saveError}</Alert>}
        {saved && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(false)}>
            Threshold saved.
          </Alert>
        )}
        {reEvalError && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setReEvalError(null)}>
            {reEvalError}
          </Alert>
        )}
        {reEvalResult && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setReEvalResult(null)}>
            Re-evaluated {reEvalResult.updated} of {reEvalResult.considered} eligible application
            {reEvalResult.considered === 1 ? "" : "s"} -- {reEvalResult.advanced_to_screened} newly advanced to
            Screened. Skipped {reEvalResult.skipped_already_decided} candidate
            {reEvalResult.skipped_already_decided === 1 ? "" : "s"} already past a decision (or on hold).
            {reEvalResult.failed > 0 ? ` ${reEvalResult.failed} couldn't be re-screened and were left untouched.` : ""}
          </Alert>
        )}

        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
          <TextField
            label="Min score"
            type="number"
            size="small"
            value={minScore}
            onChange={(e) => {
              setMinScore(e.target.value);
              setSaved(false);
            }}
            slotProps={{ htmlInput: { min: 0, max: 100 } }}
            sx={{ width: 120 }}
            disabled={!canManage}
          />
          <TextField
            label="Max score"
            type="number"
            size="small"
            value={maxScore}
            onChange={(e) => {
              setMaxScore(e.target.value);
              setSaved(false);
            }}
            slotProps={{ htmlInput: { min: 0, max: 100 } }}
            sx={{ width: 120 }}
            disabled={!canManage}
          />
          {canManage && (
            <Button variant="contained" onClick={handleSave} disabled={!valid || saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          )}
          {canManage && (
            <Button
              variant="outlined"
              startIcon={<RefreshOutlinedIcon />}
              onClick={() => setConfirmOpen(true)}
              disabled={reEvaluating}
              sx={{ ml: { sm: "auto" } }}
            >
              {reEvaluating ? "Re-evaluating..." : "Re-evaluate All"}
            </Button>
          )}
        </Stack>
        {!valid && (
          <Typography variant="caption" color="error" sx={{ display: "block", mt: 1 }}>
            Both scores must be between 0 and 100, and Min score can't be greater than Max score.
          </Typography>
        )}
      </CardContent>

      <ConfirmDialog
        open={confirmOpen}
        title="Re-evaluate all candidates?"
        message="Re-runs screening against the current threshold for every application still awaiting a decision (status Received or Screened). Candidates already past that stage, or on hold, are left completely untouched -- this never overwrites a human decision."
        confirmLabel="Re-evaluate All"
        confirming={reEvaluating}
        destructive={false}
        onConfirm={handleReEvaluateAll}
        onCancel={() => setConfirmOpen(false)}
      />
    </Card>
  );
}
