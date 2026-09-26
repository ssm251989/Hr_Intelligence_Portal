import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { screeningApi } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { useT } from "../i18n";
import { Emoji, FriendlyError } from "../ui-kit";
import { useScoreCounts } from "./screening/hooks";
import ThresholdSlider from "./screening/ThresholdSlider";

// Part F: the Screening Dashboard's own, independent threshold -- separate from Part D's
// dashboard_min/max_score (Candidates Dashboard, received -> screened auto-advance). Saving
// here only ever writes interview_min/max_score (see screeningApi.updateSettings' partial-
// update contract) and never touches the dashboard pair. Purely descriptive: it drives the
// Screening List's "Remarks" column ("Interview ready" / "Below interview threshold"), not
// any status change. Part 15.4: the two number boxes became one range slider (S4) with a
// live "N candidates pass" count.
export default function InterviewReadinessThresholdPanel({ refreshSignal = 0 }: { refreshSignal?: number }) {
  const t = useT();
  const { can } = useAuth();
  const canManage = can(ROLE_MATRIX.screeningDecisions);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [range, setRange] = useState<[number, number]>([75, 100]);
  const [savedRange, setSavedRange] = useState<[number, number]>([75, 100]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const counts = useScoreCounts({ scope: "screening" }, refreshSignal);

  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    screeningApi
      .getSettings()
      .then((settings) => {
        const next: [number, number] = [Number(settings.interview_min_score), Number(settings.interview_max_score)];
        setRange(next);
        setSavedRange(next);
      })
      .catch(setLoadError)
      .finally(() => setLoading(false));
  }, []);

  const [minNum, maxNum] = range;
  const valid = minNum >= 0 && maxNum <= 100 && minNum <= maxNum;
  const dirty = minNum !== savedRange[0] || maxNum !== savedRange[1];

  const handleSave = () => {
    if (!valid) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    screeningApi
      .updateSettings({ interview_min_score: minNum, interview_max_score: maxNum })
      .then(() => {
        setSaved(true);
        setSavedRange(range);
      })
      .catch(setSaveError)
      .finally(() => setSaving(false));
  };

  if (loading) {
    return (
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Skeleton variant="text" width="40%" height={32} sx={{ mb: 2 }} />
          <Skeleton variant="rounded" height={56} />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card sx={{ mb: 3 }} data-tour="screening-threshold">
      <CardContent>
        <Stack direction="row" spacing={1.25} alignItems="center" mb={0.5}>
          <Emoji name="target" size={22} />
          <Typography variant="h6">{t("screening.ready.title")}</Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2, maxWidth: "80ch" }}>
          {t("screening.ready.intro")}
        </Typography>

        {loadError != null && <Box mb={2}><FriendlyError error={loadError} compact /></Box>}
        {saveError != null && <Box mb={2}><FriendlyError error={saveError} compact onRetry={handleSave} /></Box>}
        {saved && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(false)}>
            {t("screening.threshold.saved")}
          </Alert>
        )}

        <ThresholdSlider
          id="interview-ready"
          value={range}
          onChange={(next) => {
            setRange(next);
            setSaved(false);
          }}
          counts={counts?.counts}
          label={t("screening.ready.slider")}
          info={t("screening.ready.info")}
          disabled={!canManage}
        />
        {canManage && (
          <Stack direction="row" spacing={1} justifyContent="flex-end" mt={1.5}>
            {dirty && (
              <Button onClick={() => setRange(savedRange)} disabled={saving}>{t("screening.threshold.reset")}</Button>
            )}
            <Button variant="contained" onClick={handleSave} disabled={!valid || saving || !dirty}>
              {saving ? t("screening.saving") : t("screening.threshold.save")}
            </Button>
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
