import Box from "@mui/material/Box";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";

// Same look as ui-kit StepForm (step count + save state, progress bar, step pills), for the
// job wizard -- which keeps its own per-step server saves, so it can't hand its state to
// StepForm itself.
export default function WizardProgress({
  steps, active, saveText,
}: {
  steps: { key: string; emoji: string; title: string }[];
  active: number;
  saveText: string;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const pct = Math.round(((active + 1) / steps.length) * 100);
  return (
    <Box sx={{ mb: 2.5 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Typography sx={{ fontWeight: 700 }}>{t("jobs.wiz.step_of", { n: active + 1, total: steps.length })}</Typography>
        <Typography sx={{ fontSize: 12, color: f.muted }} aria-live="polite">{saveText}</Typography>
      </Stack>
      <LinearProgress variant="determinate" value={pct} aria-label={t("jobs.wiz.progress", { pct })} />
      <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: "wrap", rowGap: 1 }} role="list" aria-label={t("jobs.wiz.steps")}>
        {steps.map((s, i) => (
          <Box key={s.key} role="listitem" aria-current={i === active ? "step" : undefined}
            sx={{
              display: "inline-flex", alignItems: "center", gap: 0.75, px: 1.25, py: 0.5, borderRadius: 999, fontSize: 12, fontWeight: 700,
              bgcolor: i === active ? f.brandSoft : i < active ? f.okSoft : f.surface2, color: i === active ? f.brand : i < active ? f.ok : f.muted,
            }}>
            <Emoji name={i < active ? "check" : s.emoji} size={14} />
            {s.title}
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
