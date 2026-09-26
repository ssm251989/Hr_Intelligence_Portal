import { useEffect, useState } from "react";
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { screeningApi } from "../api/client";
import type { ReEvaluateAllResult } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { useT } from "../i18n";
import { Emoji, FriendlyError } from "../ui-kit";
import ConfirmDialog from "./ConfirmDialog";
import { useScoreCounts } from "./screening/hooks";
import ThresholdSlider from "./screening/ThresholdSlider";

// Part D: the Candidates Dashboard's configurable auto-advance-to-'screened' threshold
// plus its bulk "Re-evaluate All" action. Saving the threshold takes effect immediately for
// every future screening call; Re-evaluate All is the only way to apply a changed threshold
// to *existing* candidates. Part 15.4: range slider with a live pass count (S4).
export default function ScreeningThresholdPanel() {
  const t = useT();
  const { can } = useAuth();
  const canManage = can(ROLE_MATRIX.screeningDecisions);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [range, setRange] = useState<[number, number]>([60, 100]);
  const [savedRange, setSavedRange] = useState<[number, number]>([60, 100]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reEvaluating, setReEvaluating] = useState(false);
  const [reEvalResult, setReEvalResult] = useState<ReEvaluateAllResult | null>(null);
  const [reEvalError, setReEvalError] = useState<unknown>(null);
  const [countsKey, setCountsKey] = useState(0);
  const counts = useScoreCounts({ scope: "screening" }, countsKey);

  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    screeningApi
      .getSettings()
      .then((settings) => {
        const next: [number, number] = [Number(settings.dashboard_min_score), Number(settings.dashboard_max_score)];
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
      .updateSettings({ dashboard_min_score: minNum, dashboard_max_score: maxNum })
      .then(() => {
        setSaved(true);
        setSavedRange(range);
      })
      .catch(setSaveError)
      .finally(() => setSaving(false));
  };

  const handleReEvaluateAll = () => {
    setConfirmOpen(false);
    setReEvaluating(true);
    setReEvalError(null);
    setReEvalResult(null);
    screeningApi
      .reEvaluateAll()
      .then((result) => {
        setReEvalResult(result);
        setCountsKey((k) => k + 1);
      })
      .catch(setReEvalError)
      .finally(() => setReEvaluating(false));
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
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Stack direction="row" spacing={1.25} alignItems="center" mb={0.5}>
          <Emoji name="magnifier" size={22} />
          <Typography variant="h6">{t("screening.auto.title")}</Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2, maxWidth: "80ch" }}>
          {t("screening.auto.intro")}
        </Typography>

        {loadError != null && <Box mb={2}><FriendlyError error={loadError} compact /></Box>}
        {saveError != null && <Box mb={2}><FriendlyError error={saveError} compact onRetry={handleSave} /></Box>}
        {saved && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(false)}>
            {t("screening.threshold.saved")}
          </Alert>
        )}
        {reEvalError != null && <Box mb={2}><FriendlyError error={reEvalError} compact onRetry={handleReEvaluateAll} /></Box>}
        {reEvalResult && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setReEvalResult(null)}>
            {t("screening.auto.result", {
              updated: reEvalResult.updated,
              count: reEvalResult.considered,
              advanced: reEvalResult.advanced_to_screened,
              skipped: reEvalResult.skipped_already_decided,
            })}
            {reEvalResult.failed > 0 ? ` ${t("screening.auto.result_failed", { count: reEvalResult.failed })}` : ""}
          </Alert>
        )}

        <ThresholdSlider
          id="auto-screen"
          value={range}
          onChange={(next) => {
            setRange(next);
            setSaved(false);
          }}
          counts={counts?.counts}
          label={t("screening.auto.slider")}
          info={t("screening.auto.info")}
          disabled={!canManage}
        />
        {canManage && (
          <Stack direction="row" spacing={1} justifyContent="flex-end" mt={1.5} flexWrap="wrap" useFlexGap>
            <Button
              variant="outlined"
              startIcon={<RefreshOutlinedIcon />}
              onClick={() => setConfirmOpen(true)}
              disabled={reEvaluating}
              sx={{ mr: { sm: "auto" } }}
            >
              {reEvaluating ? t("screening.auto.rechecking") : t("screening.auto.recheck")}
            </Button>
            {dirty && <Button onClick={() => setRange(savedRange)} disabled={saving}>{t("screening.threshold.reset")}</Button>}
            <Button variant="contained" onClick={handleSave} disabled={!valid || saving || !dirty}>
              {saving ? t("screening.saving") : t("screening.threshold.save")}
            </Button>
          </Stack>
        )}
      </CardContent>

      <ConfirmDialog
        open={confirmOpen}
        title={t("screening.auto.confirm_title")}
        message={t("screening.auto.confirm_body")}
        confirmLabel={t("screening.auto.recheck")}
        confirming={reEvaluating}
        destructive={false}
        onConfirm={handleReEvaluateAll}
        onCancel={() => setConfirmOpen(false)}
      />
    </Card>
  );
}
