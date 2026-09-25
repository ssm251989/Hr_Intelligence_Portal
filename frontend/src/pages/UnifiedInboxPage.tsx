import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, workflowApi, type InboxRow } from "../api/client";
import RefreshButton from "../components/RefreshButton";
import InboxOtherItems from "../components/InboxOtherItems";

// Part 5B section 3's Unified Inbox: every pending approval/task assigned to the current
// user, across every module -- real and module-agnostic (one workflow_steps table),
// scoped down to a plain table + approve/reject dialog rather than the full spec's
// richer per-item detail view (see docs/build_log.md's own Part 5 note).

function ActDialog({ row, action, onClose, onDone, onError }: {
  row: InboxRow | null;
  action: "approve" | "reject" | null;
  onClose: () => void;
  onDone: () => void;
  onError: (message: string) => void;
}) {
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => setComment(""), [row, action]);

  if (!row || !action) return null;

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await workflowApi.actOnStep(row.step_id, action, comment || undefined);
      onDone();
      onClose();
    } catch (err) {
      onError(extractErrorMessage(err, `Failed to ${action}`));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{action === "approve" ? "Approve" : "Reject"}: {row.definition_name}</DialogTitle>
      <DialogContent>
        <TextField
          label="Comment (optional)"
          multiline
          minRows={2}
          fullWidth
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          sx={{ mt: 1 }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" color={action === "approve" ? "success" : "error"} onClick={handleSubmit} disabled={submitting}>
          {submitting ? "Submitting..." : action === "approve" ? "Approve" : "Reject"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default function UnifiedInboxPage() {
  const [rows, setRows] = useState<InboxRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<{ row: InboxRow; action: "approve" | "reject" } | null>(null);

  const load = () => {
    setLoading(true);
    workflowApi
      .inbox()
      .then(setRows)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load approvals")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h5">Approvals</Typography>
        <RefreshButton loading={loading} onRefresh={load} />
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Workflow</TableCell>
              <TableCell>Step</TableCell>
              <TableCell>Due</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.length === 0 && !loading && (
              <TableRow>
                <TableCell colSpan={4}>
                  <Typography variant="body2" color="text.secondary" py={2} textAlign="center">
                    No pending approvals.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
            {rows.map((row) => (
              <TableRow key={row.step_id} hover>
                <TableCell>{row.definition_name}</TableCell>
                <TableCell>
                  <Chip label={row.node_id} size="small" variant="outlined" />
                </TableCell>
                <TableCell>{row.due_at ? new Date(row.due_at).toLocaleString() : "--"}</TableCell>
                <TableCell align="right">
                  <Stack direction="row" spacing={1} justifyContent="flex-end">
                    <Button size="small" color="success" onClick={() => setActing({ row, action: "approve" })}>
                      Approve
                    </Button>
                    <Button size="small" color="error" onClick={() => setActing({ row, action: "reject" })}>
                      Reject
                    </Button>
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      <InboxOtherItems />

      <ActDialog row={acting?.row ?? null} action={acting?.action ?? null} onClose={() => setActing(null)} onDone={load} onError={setError} />
    </Box>
  );
}
