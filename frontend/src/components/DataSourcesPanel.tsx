import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { CandidateDataSourceStatus } from "../api/types";
import { candidateSourceIcon, candidateSourceIconColor } from "../utils/candidateSourceIcons";

function timeAgo(isoTimestamp: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(isoTimestamp).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// Real connection status per channel (see backend/app/reports/router.py
// _candidate_data_sources) -- LinkedIn/Naukri are never shown as connected here, since
// neither has real candidate-import access (separate from the job-posting LinkedIn
// integration built elsewhere in this app, which doesn't grant candidate import).
export default function DataSourcesPanel({ rows }: { rows: CandidateDataSourceStatus[] }) {
  return (
    <Stack spacing={2}>
      {rows.map((row) => {
        const Icon = candidateSourceIcon(row.source);
        const color = candidateSourceIconColor(row.source);
        return (
          <Stack key={row.source} direction="row" spacing={1.5} alignItems="center">
            {Icon && (
              <Box
                sx={{
                  width: 36,
                  height: 36,
                  borderRadius: "10px",
                  bgcolor: color ? `${color}1A` : "action.selected",
                  color: color ?? "action.active",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <Icon fontSize="small" />
              </Box>
            )}
            <Box sx={{ minWidth: 0, flexGrow: 1 }}>
              <Stack direction="row" spacing={0.75} alignItems="baseline" flexWrap="wrap">
                <Typography variant="body2" fontWeight={600} noWrap>
                  {row.label}
                </Typography>
                <Typography
                  variant="caption"
                  sx={{ color: row.connected ? "success.main" : "error.main", fontWeight: 600 }}
                >
                  {row.connected ? "Connected" : "Not connected"}
                </Typography>
              </Stack>
              {/* Only for genuinely connected sources with a real sync timestamp -- never a
                  fabricated time for a source that isn't connected (LinkedIn/Naukri) or
                  hasn't synced anything yet. */}
              {row.connected && (
                <Typography variant="caption" color="text.secondary" display="block">
                  {row.last_sync ? `Last sync: ${timeAgo(row.last_sync)}` : "No candidates synced yet"}
                </Typography>
              )}
            </Box>
          </Stack>
        );
      })}
    </Stack>
  );
}
