import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { useT } from "../../i18n";
import { Emoji, useReducedMotion } from "../../ui-kit";
import { useMoney } from "../offers/shared";

// L-B1: where the expected salary sits in the job's band -- min / mid / max bar with a
// marker. Above band = coral marker AND words ("12% above the band"), never colour alone.
// The whole bar has a text equivalent for screen readers (role="img" + aria-label).

export type BandPosition = "below" | "in" | "above" | "unknown";

export function bandPosition(value: number | null | undefined, min: number | null | undefined, max: number | null | undefined): { pos: BandPosition; pct: number } {
  if (value == null || min == null || max == null) return { pos: "unknown", pct: 0 };
  if (value > max) return { pos: "above", pct: max > 0 ? Math.round(((value - max) / max) * 100) : 0 };
  if (value < min) return { pos: "below", pct: min > 0 ? Math.round(((min - value) / min) * 100) : 0 };
  return { pos: "in", pct: 0 };
}

export default function SalaryBandBar({
  expected, min, max, approved,
}: {
  expected: number | null | undefined;
  min: number | null | undefined;
  max: number | null | undefined;
  approved?: number | null;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const money = useMoney();
  const reduced = useReducedMotion();

  if (min == null || max == null) {
    return (
      <Stack direction="row" spacing={1} alignItems="center" sx={{ color: f.muted }}>
        <Emoji name="question" size={16} />
        <Typography sx={{ fontSize: 14 }}>
          {t("salary.band.none", { expected: money(expected) })}
        </Typography>
      </Stack>
    );
  }

  const mid = (min + max) / 2;
  const { pos, pct } = bandPosition(expected, min, max);
  const values = [min, max, ...(expected != null ? [expected] : []), ...(approved != null ? [approved] : [])];
  const span = Math.max(max - min, max * 0.1, 1);
  const lo = Math.min(...values) - span * 0.25;
  const hi = Math.max(...values) + span * 0.25;
  const at = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  const markerColour = pos === "above" ? f.coral : pos === "below" ? f.sky : f.brand;

  const words =
    pos === "above" ? t("salary.band.above", { pct }) : pos === "below" ? t("salary.band.below", { pct }) : pos === "in" ? t("salary.band.in") : t("salary.band.no_expected");
  const aria = t("salary.band.aria", { expected: money(expected), min: money(min), mid: money(mid), max: money(max), words });

  return (
    <Box>
      <Box role="img" aria-label={aria} sx={{ position: "relative", height: 44, mx: 1 }}>
        {/* whole track */}
        <Box sx={{ position: "absolute", left: 0, right: 0, top: 18, height: 8, borderRadius: 4, bgcolor: f.line }} />
        {/* the band */}
        <Box sx={{ position: "absolute", left: at(min), width: `calc(${at(max)} - ${at(min)})`, top: 16, height: 12, borderRadius: 6, bgcolor: f.brandSoft, border: `2px solid ${f.brand}` }} />
        {/* above-band stretch highlighted in coral */}
        {pos === "above" && expected != null && (
          <Box sx={{ position: "absolute", left: at(max), width: `calc(${at(expected)} - ${at(max)})`, top: 18, height: 8, bgcolor: f.coralSoft, borderTop: `2px dashed ${f.coral}`, borderBottom: `2px dashed ${f.coral}` }} />
        )}
        {/* mid tick */}
        <Box sx={{ position: "absolute", left: at(mid), top: 12, width: 2, height: 20, bgcolor: f.brand, transform: "translateX(-1px)" }} />
        {approved != null && (
          <Box title={t("salary.band.approved_marker")} sx={{ position: "absolute", left: at(approved), top: 10, width: 4, height: 24, borderRadius: 2, bgcolor: f.ok, transform: "translateX(-2px)" }} />
        )}
        {expected != null && (
          <Box
            sx={{
              position: "absolute", left: at(expected), top: 8, width: 28, height: 28, borderRadius: "50%", transform: "translateX(-14px)",
              bgcolor: f.surface, border: `3px solid ${markerColour}`, display: "grid", placeItems: "center", boxShadow: f.shadow,
              transition: reduced ? "none" : "left 400ms ease",
            }}
          >
            <Emoji name={pos === "above" ? "warning" : "money"} size={14} />
          </Box>
        )}
      </Box>
      <Box sx={{ position: "relative", height: 34, mx: 1, fontSize: 12, color: f.muted, fontVariantNumeric: "tabular-nums" }} aria-hidden>
        {[
          { v: min, l: t("salary.band.min") },
          { v: mid, l: t("salary.band.mid") },
          { v: max, l: t("salary.band.max") },
        ].map(({ v, l }) => (
          <Box key={l} sx={{ position: "absolute", left: at(v), transform: "translateX(-50%)", textAlign: "center", whiteSpace: "nowrap" }}>
            <Box component="span" sx={{ display: "block", fontWeight: 700 }}>{l}</Box>
            {money(v)}
          </Box>
        ))}
      </Box>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mt: 0.5 }}>
        <Emoji name={pos === "above" ? "warning" : pos === "in" ? "check" : "light_bulb"} size={16} />
        <Typography sx={{ fontWeight: 700, fontSize: 14, color: pos === "above" ? f.coral : pos === "in" ? f.ok : f.ink }}>
          {t("salary.band.expected_is", { expected: money(expected), words })}
        </Typography>
      </Stack>
    </Box>
  );
}
