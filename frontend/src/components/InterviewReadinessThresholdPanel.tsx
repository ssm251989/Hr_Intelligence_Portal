import { useEffect, useState } from "react";
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
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";

// Part F: the Screening Dashboard's own, independent threshold -- separate from Part D's
// dashboard_min/max_score (Candidates Dashboard, received -> screened auto-advance). Saving
// here only ever writes interview_min/max_score (see screeningApi.updateSettings' partial-
// update contract) and never touches the dashboard pair. Purely descriptive: it drives the
// Screening List's "Remarks" column ("Interview ready" / "Below interview threshold"), not
// any status change -- advancing to interview_scheduled stays a human decision made via
// shortlisting + scheduling elsewhere in the app. No "Re-evaluate All" button here: the one
// on the Candidates Dashboard already recomputes both thresholds' outcomes together every
// time it runs (see run_screening), so this panel only ever needs Save.
export default function InterviewReadinessThresholdPanel() {
  const { can } = useAuth();
  const canManage = can(ROLE_MATRIX.screeningDecisions);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [minScore, setMinScore] = useState("");
  const [maxScore, setMaxScore] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    screeningApi
      .getSettings()
      .then((settings) => {
        setMinScore(String(settings.interview_min_score));
        setMaxScore(String(settings.interview_max_score));
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
      .updateSettings({ interview_min_score: minNum, interview_max_score: maxNum })
      .then(() => setSaved(true))
      .catch((err) => setSaveError(extractErrorMessage(err, "Failed to save screening settings")))
      .finally(() => setSaving(false));
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
          <Typography variant="h6">Interview Readiness Threshold</Typography>
          <Typography variant="body2" color="text.secondary">
            Applications scoring at or above the minimum show as "Interview ready" in the Screening List's Remarks
            column -- a separate, independent threshold from the Candidates Dashboard's Screened threshold. Purely
            informational: it never changes an application's status.
          </Typography>
        </Box>

        {loadError && <Alert severity="error" sx={{ mb: 2 }}>{loadError}</Alert>}
        {saveError && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setSaveError(null)}>{saveError}</Alert>}
        {saved && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(false)}>
            Threshold saved.
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
        </Stack>
        {!valid && (
          <Typography variant="caption" color="error" sx={{ display: "block", mt: 1 }}>
            Both scores must be between 0 and 100, and Min score can't be greater than Max score.
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}
