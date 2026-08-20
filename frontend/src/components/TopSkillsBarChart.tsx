import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { LabeledCount } from "../api/types";

// Same hand-rolled proportional-bar idiom as TopPerformingJobs.tsx -- this app has no
// existing recharts <BarChart> usage, and a ranked list with a bar per row reads the same
// either way while staying consistent with the rest of the dashboard's chart language.
// Also reused (beyond its original Top Missing Skills use) for the Interview Dashboard's
// Interviewer Workload panel -- emptyMessage lets each caller word its own "no data yet"
// state rather than every reuse showing skill-specific copy.
export default function TopSkillsBarChart({
  rows,
  emptyMessage = "No parsed skills yet.",
}: {
  rows: LabeledCount[];
  emptyMessage?: string;
}) {
  if (rows.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        {emptyMessage}
      </Typography>
    );
  }

  const maxCount = Math.max(...rows.map((row) => row.count), 1);

  return (
    <Stack spacing={1.5}>
      {rows.map((row) => (
        <Stack key={row.label} direction="row" spacing={1.5} alignItems="center">
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="body2" noWrap>
              {row.label}
            </Typography>
            <Box
              sx={{
                height: 8,
                borderRadius: 1,
                bgcolor: "primary.main",
                width: `${(row.count / maxCount) * 100}%`,
                minWidth: row.count > 0 ? 4 : 0,
                mt: 0.5,
              }}
            />
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ minWidth: 36, textAlign: "right" }}>
            {row.count}
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}
