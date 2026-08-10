import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { CandidateDataSourceStatus } from "../api/types";

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
    <Stack spacing={1.75}>
      {rows.map((row) => (
        <Stack key={row.source} direction="row" justifyContent="space-between" alignItems="center">
          <Stack direction="row" spacing={1} alignItems="center">
            {row.connected ? (
              <CheckCircleIcon sx={{ fontSize: 18, color: "success.main" }} />
            ) : (
              <CancelIcon sx={{ fontSize: 18, color: "text.disabled" }} />
            )}
            <Typography variant="body2">{row.label}</Typography>
          </Stack>
          <Typography variant="caption" color="text.secondary">
            {row.connected ? (row.last_sync ? `Synced ${timeAgo(row.last_sync)}` : "Connected") : "Not connected"}
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}
