import Box from "@mui/material/Box";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import type { EvidenceLine, ScoreFactor, ScreeningDetail } from "../../api/screeningExtra";
import { useT } from "../../i18n";
import { Emoji, useToneColours, type Tone } from "../../ui-kit";

export const FACTORS: ScoreFactor[] = ["skills", "experience", "location", "certificates", "resume_match"];

export function scoreTone(value: number | null | undefined): Tone {
  if (value == null) return "muted";
  if (value >= 75) return "ok";
  if (value >= 50) return "sun";
  return "coral";
}

/** Bars for the five things the score is made of (S1). */
export function ScoreBreakdown({ breakdown, dense }: { breakdown: ScreeningDetail["breakdown"]; dense?: boolean }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const rows = FACTORS.filter((k) => breakdown[k] != null);
  if (rows.length === 0) return <Typography variant="body2" sx={{ color: f.muted }}>{t("screening.breakdown.none")}</Typography>;
  return (
    <Stack spacing={dense ? 0.75 : 1} sx={{ minWidth: 200 }}>
      {rows.map((k) => {
        const v = Math.round(Number(breakdown[k]));
        return (
          <Box key={k}>
            <Stack direction="row" justifyContent="space-between">
              <Typography variant="caption" sx={{ fontWeight: 600 }}>{t(`screening.factor.${k}`)}</Typography>
              <Typography variant="caption" sx={{ fontVariantNumeric: "tabular-nums", fontWeight: 700 }}>{t("screening.points", { n: v })}</Typography>
            </Stack>
            <LinearProgress
              variant="determinate"
              value={Math.max(0, Math.min(100, v))}
              aria-label={`${t(`screening.factor.${k}`)} ${t("screening.points", { n: v })}`}
              sx={{ height: 6, borderRadius: 99, bgcolor: f.line, "& .MuiLinearProgress-bar": { bgcolor: f.brand, borderRadius: 99 } }}
            />
          </Box>
        );
      })}
    </Stack>
  );
}

/** One score per candidate; hover/focus shows what it is made of (S1). */
export function ScoreBadge({ value, detail, fallbackHint }: { value: number | null | undefined; detail?: ScreeningDetail; fallbackHint?: string }) {
  const t = useT();
  const { bg, fg } = useToneColours(scoreTone(value));
  if (value == null) {
    return <Typography variant="body2" sx={{ color: "text.secondary" }}>{t("screening.score.none")}</Typography>;
  }
  const n = Math.round(value);
  const title = (
    <Box sx={{ p: 0.5 }}>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>{t("screening.score.hover_title", { n })}</Typography>
      {detail ? <ScoreBreakdown breakdown={detail.breakdown} dense /> : <Typography variant="body2">{fallbackHint || t("screening.score.hover_hint")}</Typography>}
    </Box>
  );
  return (
    <Tooltip title={title} arrow>
      <Box
        component="span"
        tabIndex={0}
        aria-label={t("screening.score.aria", { n })}
        sx={{
          display: "inline-flex", alignItems: "baseline", gap: 0.4, px: 1.1, py: 0.35, borderRadius: 999, bgcolor: bg, color: fg,
          fontWeight: 800, fontVariantNumeric: "tabular-nums", cursor: "help", outlineOffset: 2,
        }}
      >
        {n}
        <Box component="span" sx={{ fontSize: 11, fontWeight: 600, opacity: 0.85 }}>/ 100</Box>
      </Box>
    </Tooltip>
  );
}

const EVIDENCE_EMOJI: Record<EvidenceLine["kind"], string> = {
  experience: "briefcase", skill: "check", certificate: "trophy", education: "graduation", gap: "warning",
};

/** Lines taken from the resume that explain the score (S2) -- the mockup's "Why this score". */
export function EvidenceList({ lines, max = 6 }: { lines: EvidenceLine[]; max?: number }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  if (lines.length === 0) return <Typography variant="body2" sx={{ color: f.muted }}>{t("screening.evidence.none")}</Typography>;
  return (
    <Box component="ul" sx={{ listStyle: "none", m: 0, p: 0, display: "flex", flexDirection: "column", gap: 1 }}>
      {lines.slice(0, max).map((line, i) => (
        <Box
          component="li"
          key={i}
          sx={{
            fontSize: 13, px: 1.25, py: 1, bgcolor: f.surface2, borderRadius: "0 8px 8px 0",
            borderLeft: `3px solid ${line.kind === "gap" ? f.coral : f.brand}`, display: "flex", gap: 1, alignItems: "flex-start",
          }}
        >
          <Emoji name={EVIDENCE_EMOJI[line.kind]} size={16} />
          <span>
            <b>{t(`screening.evidence.${line.kind}`)}</b> “{line.text}”
          </span>
        </Box>
      ))}
    </Box>
  );
}
