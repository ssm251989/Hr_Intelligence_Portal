import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, interviewSchedulingApi } from "../api/client";
import type { InterviewSchedulingSettingsSaveResult } from "../api/types";

// Interview Scheduling automation's one-time setup: the absolute path to the Excel tracker
// (Interviewer Pool + Interview Log sheets -- see backend app/interview_scheduling/
// tracker.py) the rest of that feature reads/writes. Same one-time-path-config idiom as
// Part G's Local Import settings, just surfaced here on the Settings page instead of an
// import wizard step, since there's no comparable "wizard" for this feature.
export default function InterviewTrackerSettingsCard() {
  const [trackerPath, setTrackerPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveResult, setSaveResult] = useState<InterviewSchedulingSettingsSaveResult | null>(null);

  useEffect(() => {
    interviewSchedulingApi
      .getSettings()
      .then((settings) => setTrackerPath(settings.tracker_path ?? ""))
      .catch(() => {
        // Best-effort prefill -- an empty form is still usable if this fails.
      })
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    if (!trackerPath.trim()) {
      setError("Tracker path is required");
      return;
    }
    setSaving(true);
    setError(null);
    setSaveResult(null);
    try {
      const result = await interviewSchedulingApi.updateSettings({ tracker_path: trackerPath.trim() });
      setSaveResult(result);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to save the interview tracker path"));
    } finally {
      setSaving(false);
    }
  };

  const columnsAddedEntries = saveResult ? Object.entries(saveResult.validation.columns_added) : [];

  return (
    <Card variant="outlined" sx={{ maxWidth: 480 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Interview Scheduling Tracker
        </Typography>
        <Typography variant="body2" color="text.secondary" mb={2}>
          The Excel workbook the Interview Scheduling automation reads its Interviewer Pool from and writes its
          Interview Log to. A one-time absolute path on the server machine running this app -- if the file doesn't
          exist yet, it's created with the two expected sheets; if it already exists, it's validated and only ever
          patched with whatever sheets/columns are missing, never overwritten.
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {saveResult && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaveResult(null)}>
            {saveResult.validation.created ? (
              "Tracker created with both sheets."
            ) : saveResult.validation.sheets_added.length > 0 || columnsAddedEntries.length > 0 ? (
              <>
                Existing tracker validated.{" "}
                {saveResult.validation.sheets_added.length > 0 &&
                  `Added missing sheet(s): ${saveResult.validation.sheets_added.join(", ")}. `}
                {columnsAddedEntries.map(([sheet, columns]) => `${sheet}: added ${columns.join(", ")}. `)}
              </>
            ) : (
              "Existing tracker already has everything expected -- nothing changed."
            )}{" "}
            {saveResult.interviewer_pool_rows_added} Interviewer Pool row
            {saveResult.interviewer_pool_rows_added === 1 ? "" : "s"} added for currently published/ready-for-
            publishing jobs (of {saveResult.interviewer_pool_jobs_considered} considered) -- this also runs
            automatically whenever interview slots are proposed for a candidate, so a job published later still
            gets a row.
          </Alert>
        )}

        {loading ? (
          <CircularProgress size={24} />
        ) : (
          <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
            <TextField
              label="Tracker file path"
              placeholder="e.g. /srv/hr-automation/interview-tracker.xlsx"
              size="small"
              value={trackerPath}
              onChange={(e) => setTrackerPath(e.target.value)}
              sx={{ minWidth: 320, flexGrow: 1 }}
            />
            <Button variant="contained" onClick={handleSave} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
