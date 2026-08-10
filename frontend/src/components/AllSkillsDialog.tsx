import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";

import { extractErrorMessage, reportsApi } from "../api/client";
import type { LabeledCount } from "../api/types";
import TopSkillsBarChart from "./TopSkillsBarChart";

// The dashboard card only ever shows the top 5 (see CandidatesDashboardStats); this is the
// "View all skills" destination -- a modal was the lightest reasonable way to show the
// full ranked list without a new route, extra page chrome, or a second data-fetching page
// to keep in sync with the dashboard it's launched from.
export default function AllSkillsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [skills, setSkills] = useState<LabeledCount[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setSkills(null);
    setError(null);
    reportsApi
      .candidatesTopSkills()
      .then(setSkills)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load skills")));
  }, [open]);

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>All Skills</DialogTitle>
      <DialogContent>
        <Box sx={{ maxHeight: 480, overflowY: "auto", pt: 1 }}>
          {error ? (
            <Alert severity="error">{error}</Alert>
          ) : skills == null ? (
            <CircularProgress size={24} />
          ) : (
            <TopSkillsBarChart rows={skills} />
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
