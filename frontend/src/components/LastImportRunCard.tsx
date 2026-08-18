import { useEffect, useState } from "react";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import HourglassEmptyOutlinedIcon from "@mui/icons-material/HourglassEmptyOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, reportsApi } from "../api/client";
import type { AuditLogRead } from "../api/types";

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

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Box sx={{ minWidth: 90 }}>
      <Typography variant="h6" sx={{ lineHeight: 1.1 }}>
        {value}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
    </Box>
  );
}

// Part G: read-only visibility into the hourly local-folder auto-import (backend/
// app/local_import/) -- deliberately not a new endpoint, just the existing GET
// /reports/audit filtered to entity_type="local_import_run", limit=1. That query already
// returns whichever of the three actions a scan last logged (started / still_processing /
// completed -- see app/local_import/service.py), so this reads the single most recent
// entry and renders whichever state it turns out to be, rather than assuming it's always
// a finished run (a scan stuck mid-batch would otherwise silently show a stale old
// success instead of "still processing").
export default function LastImportRunCard() {
  const [entry, setEntry] = useState<AuditLogRead | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    reportsApi
      .auditLog({ entityType: "local_import_run", limit: 1 })
      .then((page) => setEntry(page.items[0] ?? null))
      .catch((err) => setError(extractErrorMessage(err, "Failed to load last import run")));
  }, []);

  if (entry === undefined) {
    return (
      <Card variant="outlined" sx={{ mb: 3 }}>
        <CardContent>
          <Skeleton variant="text" width="30%" height={32} sx={{ mb: 1.5 }} />
          <Skeleton variant="rounded" height={48} />
        </CardContent>
      </Card>
    );
  }

  const details = (entry?.details ?? {}) as Record<string, number | string | null | undefined>;

  return (
    <Card variant="outlined" sx={{ mb: 3 }}>
      <CardContent>
        <Typography variant="h6" mb={1.5}>
          Last Import Run
        </Typography>

        {error && <Alert severity="error">{error}</Alert>}

        {!error && entry === null && (
          <Typography color="text.secondary">No local-folder import has run yet.</Typography>
        )}

        {!error && entry && entry.action === "local_import_run_completed" && (
          <Stack spacing={1.5}>
            <Stack direction="row" spacing={1} alignItems="center">
              <CheckCircleOutlineIcon fontSize="small" color="success" />
              <Typography variant="body2" color="text.secondary">
                Completed {timeAgo(entry.created_at)}
              </Typography>
            </Stack>
            <Stack direction="row" spacing={3} flexWrap="wrap" useFlexGap>
              <Stat label="Files Found" value={Number(details.files_found) || 0} />
              <Stat label="Imported" value={Number(details.imported) || 0} />
              <Stat label="Duplicates Skipped" value={Number(details.duplicates) || 0} />
              <Stat label="Failed" value={Number(details.failed) || 0} />
            </Stack>
          </Stack>
        )}

        {!error && entry && entry.action === "local_import_run_still_processing" && (
          <Stack direction="row" spacing={1} alignItems="center">
            <HourglassEmptyOutlinedIcon fontSize="small" color="warning" />
            <Typography variant="body2" color="text.secondary">
              Still processing (started {timeAgo(entry.created_at)}) -- {String(details.files_pending ?? "some")}{" "}
              file(s) pending. This will pick back up on the next check.
            </Typography>
          </Stack>
        )}

        {!error && entry && entry.action === "local_import_run_started" && (
          <Stack direction="row" spacing={1} alignItems="center">
            <HourglassEmptyOutlinedIcon fontSize="small" color="action" />
            <Typography variant="body2" color="text.secondary">
              Import run in progress (started {timeAgo(entry.created_at)})...
            </Typography>
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}
