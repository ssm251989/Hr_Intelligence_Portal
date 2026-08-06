import { useState } from "react";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import CheckIcon from "@mui/icons-material/Check";
import MuiLink from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, jobsApi } from "../api/client";
import type { JobRoleRead } from "../api/types";

interface PlatformRowProps {
  label: string;
  url: string | null | undefined;
  canWrite: boolean;
  onSave: (url: string) => Promise<void>;
}

function PlatformRow({ label, url, canWrite, onSave }: PlatformRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(url || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(draft.trim());
      setEditing(false);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to save posting URL"));
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <Stack direction="row" spacing={0.5} alignItems="center">
        <Typography variant="body2" color="text.secondary">
          {label}:
        </Typography>
        {url ? (
          <MuiLink href={url} target="_blank" rel="noopener noreferrer" variant="body2">
            view posting
          </MuiLink>
        ) : (
          <Typography variant="body2" color="text.secondary" fontStyle="italic">
            not posted yet
          </Typography>
        )}
        {canWrite && (
          <IconButton size="small" onClick={() => setEditing(true)} aria-label={`Edit ${label} posting URL`}>
            <EditOutlinedIcon fontSize="inherit" />
          </IconButton>
        )}
      </Stack>
    );
  }

  return (
    <Stack spacing={0.5}>
      <Stack direction="row" spacing={1} alignItems="center">
        <TextField
          size="small"
          label={`${label} posting URL`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          fullWidth
        />
        <IconButton size="small" onClick={handleSave} disabled={saving} aria-label="Save">
          <CheckIcon fontSize="inherit" />
        </IconButton>
      </Stack>
      {error && (
        <Typography variant="caption" color="error">
          {error}
        </Typography>
      )}
    </Stack>
  );
}

export default function PostingLinksEditor({
  job,
  canWrite,
  onUpdated,
}: {
  job: JobRoleRead;
  canWrite: boolean;
  onUpdated: (job: JobRoleRead) => void;
}) {
  const platforms = job.published_platforms as Record<string, boolean>;
  if (!platforms.naukri && !platforms.linkedin) {
    return null;
  }

  const save = async (field: "posting_url_naukri" | "posting_url_linkedin", value: string) => {
    const updated = await jobsApi.update(job.id, { [field]: value || null });
    onUpdated(updated);
  };

  return (
    <Box mt={1}>
      <Stack spacing={0.5}>
        {platforms.naukri && (
          <PlatformRow
            label="Naukri.com"
            url={job.posting_url_naukri}
            canWrite={canWrite}
            onSave={(url) => save("posting_url_naukri", url)}
          />
        )}
        {platforms.linkedin && (
          <PlatformRow
            label="LinkedIn"
            url={job.posting_url_linkedin}
            canWrite={canWrite}
            onSave={(url) => save("posting_url_linkedin", url)}
          />
        )}
      </Stack>
    </Box>
  );
}
