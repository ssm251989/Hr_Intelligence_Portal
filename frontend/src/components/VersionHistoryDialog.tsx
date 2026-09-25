import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";

import { experienceApi, extractErrorMessage } from "../api/client";

// Part 14 section 7 (docs/HRMS_COMPLETE_SPEC.txt): version history + revert for templates,
// workflows, letters and prompts. Revert creates a NEW draft from the chosen version -- it
// still goes through preview/simulate and publish; history is never rewritten.

interface Props {
  open: boolean;
  kind: "message_template" | "workflow_definition" | "letter_template" | "prompt_template";
  objectKey: string;
  onClose: () => void;
  onReverted?: () => void;
}

export default function VersionHistoryDialog({ open, kind, objectKey, onClose, onReverted }: Props) {
  const [rows, setRows] = useState<{ id: string; version: number; status: string; created_at: string | null }[]>([]);
  const [message, setMessage] = useState<{ severity: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (open) experienceApi.versions(kind, objectKey).then(setRows).catch((err) => setMessage({ severity: "error", text: extractErrorMessage(err, "Failed to load history") }));
  }, [open, kind, objectKey]);

  const revert = (version: number) =>
    experienceApi
      .revertVersion(kind, objectKey, version)
      .then((r) => {
        setMessage({ severity: "success", text: `Created draft v${r.version} from v${version}. Preview it, then publish.` });
        onReverted?.();
        return experienceApi.versions(kind, objectKey).then(setRows);
      })
      .catch((err) => setMessage({ severity: "error", text: extractErrorMessage(err, "Revert failed") }));

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Version history · {objectKey}</DialogTitle>
      <DialogContent>
        {message && <Alert severity={message.severity} sx={{ mb: 1 }}>{message.text}</Alert>}
        <List dense>
          {rows.map((r) => (
            <ListItem key={r.id} secondaryAction={r.status !== "draft" ? <Button size="small" onClick={() => revert(r.version)}>Revert to this</Button> : null}>
              <ListItemText primary={`v${r.version}`} secondary={r.created_at ? new Date(r.created_at).toLocaleString() : undefined} />
              <Chip size="small" label={r.status} color={r.status === "published" ? "success" : "default"} sx={{ mr: 12 }} />
            </ListItem>
          ))}
        </List>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
