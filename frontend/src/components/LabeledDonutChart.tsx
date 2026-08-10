import { Cell, Pie, PieChart, Tooltip } from "recharts";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { LabeledCount } from "../api/types";
import BreakdownLegend, { toBreakdownSlices, type BreakdownSlice } from "./BreakdownLegend";

function DonutTooltip({
  active,
  payload,
  total,
}: {
  active?: boolean;
  payload?: { payload: BreakdownSlice }[];
  total: number;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const { label, count } = payload[0].payload;
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <Box sx={{ bgcolor: "background.paper", border: 1, borderColor: "divider", borderRadius: 1, px: 1.5, py: 1 }}>
      <Typography variant="body2" fontWeight="bold">
        {count} ({pct}%)
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
    </Box>
  );
}

export default function LabeledDonutChart({
  title,
  rows,
  size = 200,
  legendMinWidth = 160,
  spacing = 3,
}: {
  title: string;
  rows: LabeledCount[];
  // Lets a narrower host column (e.g. a 4-across dashboard row) shrink the chart+legend
  // footprint so the side-by-side layout still fits without the legend wrapping below --
  // the defaults reproduce this component's original fixed 200px/160px/24px sizing
  // exactly, so existing callers (Jobs by Department, Job Status Overview) are unaffected.
  size?: number;
  legendMinWidth?: number;
  spacing?: number;
}) {
  const slices = toBreakdownSlices(rows);
  const total = slices.reduce((sum, row) => sum + row.count, 0);
  const innerRadius = Math.round(size * 0.275);
  const outerRadius = Math.round(size * 0.45);
  const compact = size < 160;

  return (
    <Box>
      {title && (
        <Typography variant="h6" mb={2}>
          {title}
        </Typography>
      )}
      {total === 0 ? (
        <Typography color="text.secondary">No data yet.</Typography>
      ) : (
        <Stack direction="row" spacing={spacing} alignItems="center" flexWrap="wrap" useFlexGap>
          <Box sx={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
            <PieChart width={size} height={size}>
              <Pie
                data={slices}
                dataKey="count"
                nameKey="label"
                innerRadius={innerRadius}
                outerRadius={outerRadius}
                paddingAngle={2}
                stroke="none"
                isAnimationActive={false}
              >
                {slices.map((slice) => (
                  <Cell key={slice.label} fill={slice.color} />
                ))}
              </Pie>
              <Tooltip content={<DonutTooltip total={total} />} />
            </PieChart>
            {/* Center total, absolutely positioned over the donut hole rather than a
                recharts label -- simpler to style consistently and keeps the SVG itself
                just the ring. pointerEvents none so it never blocks slice hover/tooltip. */}
            <Box
              sx={{
                position: "absolute",
                inset: 0,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                pointerEvents: "none",
              }}
            >
              <Typography variant={compact ? "body1" : "h5"} fontWeight="bold">
                {total}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Total
              </Typography>
            </Box>
          </Box>
          {/* Text legend doubles as the table-view equivalent -- every count/percent
              is readable without hovering, not gated behind the tooltip. */}
          <Box sx={{ flexGrow: 1, minWidth: legendMinWidth }}>
            <BreakdownLegend slices={slices} total={total} />
          </Box>
        </Stack>
      )}
    </Box>
  );
}
