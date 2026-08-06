import { Cell, Pie, PieChart, Tooltip } from "recharts";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { LabeledCount } from "../api/types";

// Reference categorical palette (see the dataviz skill's references/palette.md),
// used in fixed order -- never cycled or reassigned by rank.
const CATEGORICAL_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];
const OTHER_COLOR = "#9e9d98"; // muted ink, not a categorical identity slot
const MAX_SLICES = 6;

interface SliceDatum {
  label: string;
  count: number;
  color: string;
}

function toSlices(rows: LabeledCount[]): SliceDatum[] {
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

function DonutTooltip({ active, payload, total }: { active?: boolean; payload?: { payload: SliceDatum }[]; total: number }) {
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

export default function LabeledDonutChart({ title, rows }: { title: string; rows: LabeledCount[] }) {
  const slices = toSlices(rows);
  const total = slices.reduce((sum, row) => sum + row.count, 0);

  return (
    <Box>
      <Typography variant="h6" mb={2}>
        {title}
      </Typography>
      {total === 0 ? (
        <Typography color="text.secondary">No jobs yet.</Typography>
      ) : (
        <Stack direction="row" spacing={3} alignItems="center" flexWrap="wrap" useFlexGap>
          <PieChart width={200} height={200}>
            <Pie
              data={slices}
              dataKey="count"
              nameKey="label"
              innerRadius={55}
              outerRadius={90}
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
          {/* Text legend doubles as the table-view equivalent -- every count/percent
              is readable without hovering, not gated behind the tooltip. */}
          <Stack spacing={0.75}>
            {slices.map((slice) => (
              <Stack key={slice.label} direction="row" spacing={1} alignItems="center">
                <Box sx={{ width: 10, height: 10, borderRadius: "50%", bgcolor: slice.color, flexShrink: 0 }} />
                <Typography variant="body2" sx={{ minWidth: 120 }}>
                  {slice.label}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {slice.count} ({total > 0 ? Math.round((slice.count / total) * 100) : 0}%)
                </Typography>
              </Stack>
            ))}
          </Stack>
        </Stack>
      )}
    </Box>
  );
}
