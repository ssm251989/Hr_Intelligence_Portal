import { useState } from "react";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";

import { applicationsApi, extractErrorMessage } from "../api/client";
import { isTerminalApplicationStatus, type CandidateApplicationRow } from "../api/types";
import ConfirmDialog from "./ConfirmDialog";

// An application can be put on hold from any non-terminal status, resumed only from
// on_hold, and deleted only while still at 'received' (see backend/app/candidates/hold.py
// and applications_router.py delete_application). Outside of those three, there's nothing
// this menu can do -- same "don't render an empty menu" rule as JobsPage's JobActionsMenu.
export default function CandidateActionsMenu({
  row,
  onChanged,
  onDeleted,
  onError,
}: {
  row: CandidateApplicationRow;
  onChanged: (applicationId: string, newStatus: string) => void;
  onDeleted: (applicationId: string) => void;
  onError: (message: string) => void;
}) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const [pending, setPending] = useState(false);
  const [confirmHoldOpen, setConfirmHoldOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const canResume = row.status === "on_hold";
  const canHold = !canResume && !isTerminalApplicationStatus(row.status);
  const canDelete = row.status === "received";

  if (!canResume && !canHold && !canDelete) {
    return null;
  }

  const runHoldToggle = async () => {
    setConfirmHoldOpen(false);
    setAnchorEl(null);
    setPending(true);
    try {
      const updated = canResume
        ? await applicationsApi.resume(row.application_id)
        : await applicationsApi.hold(row.application_id);
      onChanged(row.application_id, updated.status);
    } catch (err) {
      onError(extractErrorMessage(err, canResume ? "Failed to resume application" : "Failed to put application on hold"));
    } finally {
      setPending(false);
    }
  };

  const runDelete = async () => {
    setConfirmDeleteOpen(false);
    setPending(true);
    try {
      await applicationsApi.delete(row.application_id);
      onDeleted(row.application_id);
    } catch (err) {
      onError(extractErrorMessage(err, "Failed to delete application"));
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <IconButton size="small" onClick={(e) => setAnchorEl(e.currentTarget)} disabled={pending}>
        <MoreVertIcon fontSize="small" />
      </IconButton>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        {canResume && <MenuItem onClick={runHoldToggle}>Resume from Hold</MenuItem>}
        {canHold && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              setConfirmHoldOpen(true);
            }}
          >
            Put on Hold
          </MenuItem>
        )}
        {canDelete && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              setConfirmDeleteOpen(true);
            }}
            sx={{ color: "error.main" }}
          >
            <DeleteOutlineIcon fontSize="small" sx={{ mr: 1 }} />
            Delete
          </MenuItem>
        )}
      </Menu>

      <ConfirmDialog
        open={confirmHoldOpen}
        title="Put this application on hold?"
        message={`This pauses ${row.candidate_name || "this candidate"}'s application for ${row.job_title} -- no pipeline actions (screening, interviews, salary, BGV, offer) can be taken until it's resumed.`}
        confirmLabel="Put on Hold"
        confirming={pending}
        destructive={false}
        onConfirm={runHoldToggle}
        onCancel={() => setConfirmHoldOpen(false)}
      />
      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete this application?"
        message={`This will permanently delete ${row.candidate_name || "this candidate"}'s application for ${row.job_title}. This can't be undone.`}
        confirmLabel="Delete"
        confirming={pending}
        destructive
        onConfirm={runDelete}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </>
  );
}
