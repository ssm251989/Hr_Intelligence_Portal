import Box from "@mui/material/Box";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { passCount } from "../../api/screeningExtra";
import { useT } from "../../i18n";
import { Emoji, InfoTip } from "../../ui-kit";

// S4: the Shortlist threshold as a slider (keyboard: arrows move 1 point, PageUp/PageDown 10) with a
// live "N candidates pass" read-out computed on the client from a score histogram (or from
// the scores already loaded on screen when the histogram isn't available).
export default function ThresholdSlider({
  value, onChange, counts, scores, label, info, disabled, id,
}: {
  value: [number, number];
  onChange: (next: [number, number]) => void;
  /** Histogram (index = score) covering every candidate; preferred. */
  counts?: number[] | null;
  /** Fallback: the scores loaded on screen. */
  scores?: (number | null | undefined)[];
  label: string;
  info: string;
  disabled?: boolean;
  id: string;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [min, max] = value;
  let pass: number;
  let total: number;
  if (counts) {
    pass = passCount(counts, min, max);
    total = counts.reduce((a, b) => a + b, 0);
  } else {
    const known = (scores ?? []).filter((s): s is number => s != null).map((s) => Math.round(s));
    pass = known.filter((s) => s >= min && s <= max).length;
    total = known.length;
  }
  const passText = t(total === 0 ? "screening.slider.no_scores" : "screening.slider.pass", { count: pass, total });

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={0.5} sx={{ mb: 0.5 }}>
        <Typography id={`${id}-label`} sx={{ fontWeight: 700 }}>{label}</Typography>
        <InfoTip text={info} label={t("screening.whats_this")} />
      </Stack>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={{ xs: 1, sm: 3 }} alignItems={{ xs: "stretch", sm: "center" }}>
        <Box sx={{ flex: 1, px: 1 }}>
          <Slider
            value={value}
            onChange={(_e, next) => Array.isArray(next) && onChange([next[0], next[1]])}
            min={0}
            max={100}
            step={1}
            shiftStep={10}
            disableSwap
            disabled={disabled}
            valueLabelDisplay="auto"
            aria-labelledby={`${id}-label`}
            getAriaLabel={(i) => (i === 0 ? t("screening.slider.min_aria") : t("screening.slider.max_aria"))}
            getAriaValueText={(v) => t("screening.slider.value_text", { n: v, count: pass })}
            marks={[{ value: 0, label: "0" }, { value: 50, label: "50" }, { value: 100, label: "100" }]}
            sx={{ color: f.brand }}
          />
        </Box>
        <Box
          role="status"
          aria-live="polite"
          sx={{ display: "flex", alignItems: "center", gap: 1, px: 1.5, py: 1, borderRadius: "12px", bgcolor: f.brandSoft, minWidth: 210 }}
        >
          <Emoji name="check" size={20} />
          <Box>
            <Typography sx={{ fontWeight: 800, fontVariantNumeric: "tabular-nums", lineHeight: 1.2 }}>{passText}</Typography>
            <Typography variant="caption" sx={{ color: f.muted }}>{t("screening.slider.range", { min, max })}</Typography>
          </Box>
        </Box>
      </Stack>
    </Box>
  );
}
