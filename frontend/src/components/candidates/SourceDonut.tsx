import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import type { LabeledCount } from "../../api/types";
import { useT } from "../../i18n";
import { EmptyState, useReducedMotion } from "../../ui-kit";
import { useFresh } from "./stages";

// Part 15.4 dashboard "Candidates by source": donut in theme.palette.chart colours (fixed
// order, biggest first, anything past the palette folds into "Other") with a legend that
// carries every number in words, so nothing depends on colour or hovering.
export default function SourceDonut({ rows }: { rows: LabeledCount[] }) {
  const t = useT();
  const f = useFresh();
  const reduced = useReducedMotion();
  const palette = (useTheme().palette as { chart?: string[] }).chart ?? [f.brand, f.sky, f.sun, f.coral, f.ok, f.muted];
  const sorted = [...rows].filter((r) => r.count > 0).sort((a, b) => b.count - a.count);
  const head = sorted.slice(0, palette.length - 1);
  const rest = sorted.slice(palette.length - 1).reduce((s, r) => s + r.count, 0);
  const slices = [...head.map((r, i) => ({ ...r, color: palette[i] })), ...(rest > 0 ? [{ label: t("candidates.dash.other"), count: rest, color: f.muted }] : [])];
  const total = slices.reduce((s, r) => s + r.count, 0);

  if (total === 0) return <EmptyState compact illustration="no-data" title={t("candidates.dash.no_sources")} />;

  return (
    <Stack direction={{ xs: "column", sm: "row", md: "column", lg: "row" }} spacing={2} alignItems="center">
      <Box sx={{ width: 150, height: 150, position: "relative", flexShrink: 0 }} role="img"
        aria-label={slices.map((s) => `${s.label} ${s.count}`).join(", ")}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={slices} dataKey="count" nameKey="label" innerRadius={48} outerRadius={70} paddingAngle={2} stroke={f.surface} strokeWidth={2} isAnimationActive={!reduced}>
              {slices.map((s) => <Cell key={s.label} fill={s.color} />)}
            </Pie>
            <Tooltip contentStyle={{ background: f.surface, border: `1px solid ${f.line}`, borderRadius: 10, color: f.ink }} />
          </PieChart>
        </ResponsiveContainer>
        <Box sx={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", pointerEvents: "none", textAlign: "center" }}>
          <Box>
            <Typography sx={{ fontWeight: 800, fontSize: 22, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>{total.toLocaleString()}</Typography>
            <Typography sx={{ fontSize: 11, color: f.muted }}>{t("candidates.dash.in_total")}</Typography>
          </Box>
        </Box>
      </Box>
      <Stack spacing={0.75} sx={{ minWidth: 0, flex: 1 }}>
        {slices.map((s) => (
          <Stack key={s.label} direction="row" spacing={1} alignItems="center">
            <Box sx={{ width: 10, height: 10, borderRadius: "3px", bgcolor: s.color, flexShrink: 0 }} />
            <Typography sx={{ fontSize: 13, flex: 1, minWidth: 0 }} noWrap>{s.label}</Typography>
            <Typography sx={{ fontSize: 13, color: f.muted, fontVariantNumeric: "tabular-nums" }}>
              {s.count} ({Math.round((s.count / total) * 100)}%)
            </Typography>
          </Stack>
        ))}
      </Stack>
    </Stack>
  );
}
