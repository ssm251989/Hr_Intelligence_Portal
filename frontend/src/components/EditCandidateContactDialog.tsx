import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { candidatesApi, extractErrorMessage } from "../api/client";
import type { CandidateRead, UUID } from "../api/types";

// Basic contact info only (name/email/phone) -- everything else about a candidate comes
// from an upload/import/resume parse, not manual editing (see backend
// app/schemas/candidate.py CandidateUpdate).
//
// Fetches the full candidate record itself rather than taking initial values as props:
// the Candidates List row (CandidateApplicationRow) this dialog is opened from doesn't
// carry a phone number at all, so seeding the phone field from the row would always show
// it blank and silently wipe out a real phone number on save.
export default function EditCandidateContactDialog({
  candidateId,
  open,
  onClose,
  onSaved,
}: {
  candidateId: UUID | null;
  open: boolean;
  onClose: () => void;
  onSaved: (updated: CandidateRead) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !candidateId) return;
    setLoading(true);
    setError(null);
    candidatesApi
      .get(candidateId)
      .then((candidate) => {
        setFullName(candidate.full_name || "");
        setEmail(candidate.email || "");
        setPhone(candidate.phone || "");
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load candidate")))
      .finally(() => setLoading(false));
  }, [open, candidateId]);

  const handleSave = async () => {
    if (!candidateId) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await candidatesApi.update(candidateId, {
        full_name: fullName.trim() || null,
        email: email.trim() || null,
        phone: phone.trim() || null,
      });
      onSaved(updated);
      onClose();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to update candidate"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Edit Contact Info</DialogTitle>
      <DialogContent>
        {loading ? (
          <Stack alignItems="center" py={3}>
            <CircularProgress size={24} />
          </Stack>
        ) : (
          <Stack spacing={2} mt={1}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} fullWidth autoFocus />
            <TextField label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} fullWidth />
            <TextField label="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} fullWidth />
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button variant="contained" onClick={handleSave} disabled={saving || loading}>
          {saving ? "Saving..." : "Save"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
