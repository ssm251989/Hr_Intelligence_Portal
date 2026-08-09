import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { LabeledCount } from "../api/types";

// Reference categorical palette (see the dataviz skill's references/palette.md),
// used in fixed order -- never cycled or reassigned by rank.
export const CATEGORICAL_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];
export const OTHER_COLOR = "#9e9d98"; // muted ink, not a categorical identity slot
const MAX_SLICES = 6;

export interface BreakdownSlice {
  label: string;
  count: number;
  color: string;
}

/** Assigns each row a fixed categorical color (folding anything past the 6th into
 * "Other") -- shared by every donut/legend/map breakdown so the same label always
 * gets the same slot within a given sorted set. */
export function toBreakdownSlices(rows: LabeledCount[]): BreakdownSlice[] {
  const sorted = [...rows].filter((row) => row.count > 0).sort((a, b) => b.count - a.count);
  const head = sorted.slice(0, MAX_SLICES);
  const tailTotal = sorted.slice(MAX_SLICES).reduce((sum, row) => sum + row.count, 0);

  const slices = head.map((row, index) => ({
    label: row.label,
    count: row.count,
    color: CATEGORICAL_COLORS[index],
  }));
  if (tailTotal > 0) {
    slices.push({ label: "Other", count: tailTotal, color: OTHER_COLOR });
  }
  return slices;
}

/** Vertical list: colored dot + name + count + percentage-of-total, one row per slice.
 * The table-view equivalent of the donut/map it sits beside -- every count/percent is
 * readable without hovering a chart. */
export default function BreakdownLegend({
  slices,
  total,
  emptyLabel = "No data yet.",
}: {
  slices: BreakdownSlice[];
  total: number;
  emptyLabel?: string;
}) {
  if (slices.length === 0) {
    return <Typography color="text.secondary">{emptyLabel}</Typography>;
  }
  return (
    <Stack spacing={0.75}>
      {slices.map((slice) => (
        <Stack key={slice.label} direction="row" spacing={1} alignItems="center">
          <Box sx={{ width: 10, height: 10, borderRadius: "50%", bgcolor: slice.color, flexShrink: 0 }} />
          {/* No fixed minWidth on the label -- that reserved a fixed gap regardless of
              how short the actual text was (e.g. "Goa", "Pune"), which is exactly what
              made this legend's name-to-count gap look wider than Department's or Status
              Overview's longer labels that happened to already fill that space. */}
          <Typography variant="body2">{slice.label}</Typography>
          <Typography variant="body2" color="text.secondary">
            {slice.count} ({total > 0 ? Math.round((slice.count / total) * 100) : 0}%)
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}
