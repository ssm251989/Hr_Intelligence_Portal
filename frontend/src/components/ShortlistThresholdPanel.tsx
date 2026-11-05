import { useEffect, useState } from "react";
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { screeningApi } from "../api/client";
import { passCount } from "../api/screeningExtra";
import type { ReEvaluateAllResult } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { useT } from "../i18n";
import { Emoji, FriendlyError, InfoTip } from "../ui-kit";
import ConfirmDialog from "./ConfirmDialog";
import { useScoreCounts } from "./screening/hooks";

// Part 17.4: the ONE company-level "Shortlist threshold" (0-100 Match score). Replaces the
// old "Automatic screening mark" (Candidates Dashboard) and "Interview-ready score"
// (Screening Dashboard) panels. Saved via PUT /screening/settings {shortlist_threshold};
// each job can override it in its own Shortlisting rules. The live "N of M at or above"
// count comes from the /ui/screening/score-counts histogram (Match score per candidate).
export default function ShortlistThresholdPanel({ refreshSignal = 0 }: { refreshSignal?: number }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { can } = useAuth();
  const canManage = can(ROLE_MATRIX.screeningDecisions);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [value, setValue] = useState(75);
  const [savedValue, setSavedValue] = useState(75);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reEvaluating, setReEvaluating] = useState(false);
  const [reEvalResult, setReEvalResult] = useState<ReEvaluateAllResult | null>(null);
  const [reEvalError, setReEvalError] = useState<unknown>(null);
  const [countsKey, setCountsKey] = useState(0);
  const counts = useScoreCounts({ scope: "screening" }, refreshSignal + countsKey);

  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    screeningApi
      .getSettings()
      .then((settings) => {
        const next = Math.round(Number(settings.shortlist_threshold));
        setValue(next);
        setSavedValue(next);
      })
      .catch(setLoadError)
      .finally(() => setLoading(false));
  }, []);

  const dirty = value !== savedValue;

  const handleSave = () => {
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    screeningApi
      .updateSettings({ shortlist_threshold: value })
      .then((settings) => {
        const next = Math.round(Number(settings.shortlist_threshold));
        setSaved(true);
        setValue(next);
        setSavedValue(next);
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

  const histogram = counts?.counts;
  const total = histogram ? histogram.reduce((a, b) => a + b, 0) : 0;
  const atOrAbove = histogram ? passCount(histogram, value) : 0;
  const countText = histogram
    ? t(total === 0 ? "screening.slider.no_scores" : "screening.shortlist.count", { count: atOrAbove, total })
    : null;

  return (
    <Card sx={{ mb: 3 }} data-tour="screening-threshold">
      <CardContent>
        <Stack direction="row" spacing={1.25} alignItems="center" mb={0.5}>
          <Emoji name="target" size={22} />
          <Typography variant="h6">{t("screening.shortlist.title")}</Typography>
          <InfoTip text={t("screening.shortlist.info")} label={t("screening.whats_this")} />
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2, maxWidth: "80ch" }}>
          {t("screening.shortlist.intro")}
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

        <Stack direction={{ xs: "column", sm: "row" }} spacing={{ xs: 1, sm: 3 }} alignItems={{ xs: "stretch", sm: "center" }}>
          <Box sx={{ flex: 1, px: 1 }}>
            <Slider
              value={value}
              onChange={(_e, next) => {
                if (typeof next === "number") {
                  setValue(next);
                  setSaved(false);
                }
              }}
              min={0}
              max={100}
              step={1}
              shiftStep={10}
              disabled={!canManage}
              valueLabelDisplay="auto"
              aria-label={t("screening.shortlist.aria")}
              getAriaValueText={(v) => t("screening.shortlist.value", { n: v })}
              marks={[{ value: 0, label: "0" }, { value: 50, label: "50" }, { value: 100, label: "100" }]}
              sx={{ color: f.brand }}
            />
          </Box>
          <Box
            role="status"
            aria-live="polite"
            sx={{ display: "flex", alignItems: "center", gap: 1, px: 1.5, py: 1, borderRadius: "12px", bgcolor: f.brandSoft, minWidth: 230 }}
          >
            <Emoji name="check" size={20} />
            <Box>
              <Typography sx={{ fontWeight: 800, fontVariantNumeric: "tabular-nums", lineHeight: 1.2 }}>
                {t("screening.shortlist.value", { n: value })}
              </Typography>
              {countText && <Typography variant="caption" sx={{ color: f.muted }}>{countText}</Typography>}
            </Box>
          </Box>
        </Stack>

        {canManage && (
          <>
            <Typography variant="caption" component="p" sx={{ color: f.muted, mt: 1.5, maxWidth: "80ch" }}>
              {t("screening.shortlist.recheck_hint")}
            </Typography>
            <Stack direction="row" spacing={1} justifyContent="flex-end" mt={1} flexWrap="wrap" useFlexGap>
              <Button
                variant="outlined"
                startIcon={<RefreshOutlinedIcon />}
                onClick={() => setConfirmOpen(true)}
                disabled={reEvaluating}
                sx={{ mr: { sm: "auto" } }}
              >
                {reEvaluating ? t("screening.auto.rechecking") : t("screening.auto.recheck")}
              </Button>
              {dirty && <Button onClick={() => setValue(savedValue)} disabled={saving}>{t("screening.threshold.reset")}</Button>}
              <Button variant="contained" onClick={handleSave} disabled={saving || !dirty}>
                {saving ? t("screening.saving") : t("screening.threshold.save")}
              </Button>
            </Stack>
          </>
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
