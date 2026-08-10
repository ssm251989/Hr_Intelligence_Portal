import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { LabeledCount } from "../api/types";

// Fixed bucket order + color-by-band (green for the strongest matches down to red for
// the weakest) -- backend/app/reports/stats.py always returns all 5 buckets, even at 0,
// so the axis never reflows as real scores come in.
const BUCKET_COLORS: Record<string, string> = {
  "90-100": "#008300",
  "70-89": "#1baf7a",
  "50-69": "#eda100",
  "30-49": "#eb6834",
  "0-29": "#c62828",
};

export default function MatchScoreDistributionChart({ rows }: { rows: LabeledCount[] }) {
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  const maxCount = Math.max(...rows.map((row) => row.count), 1);

  if (total === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        No screened applications yet.
      </Typography>
    );
  }

  return (
    <Stack spacing={1.5}>
      {rows.map((row) => (
        <Stack key={row.label} direction="row" spacing={1.5} alignItems="center">
          <Typography variant="body2" color="text.secondary" sx={{ width: 56, flexShrink: 0 }}>
            {row.label}
          </Typography>
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Box
              sx={{
                height: 10,
                borderRadius: 1,
                bgcolor: BUCKET_COLORS[row.label] ?? "primary.main",
                width: `${(row.count / maxCount) * 100}%`,
                minWidth: row.count > 0 ? 4 : 0,
              }}
            />
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ minWidth: 60, textAlign: "right" }}>
            {row.count} ({total > 0 ? Math.round((row.count / total) * 100) : 0}%)
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}
