import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, privacyApi, type BreachRow, type PrivacyRequestRow } from "../api/client";

// Part 13 section E (docs/HRMS_COMPLETE_SPEC.txt): data principal request queue (with SLA
// due dates) and the breach register. Erasure/export/retention actions are backend-complete
// and deliberately require explicit per-request steps (verify -> act).

export default function PrivacyPanel() {
  const [requests, setRequests] = useState<PrivacyRequestRow[]>([]);
  const [breaches, setBreaches] = useState<BreachRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    privacyApi.requests().then(setRequests).catch((err) => setError(extractErrorMessage(err, "Failed to load privacy requests")));
    privacyApi.breaches().then(setBreaches).catch(() => undefined);
  };
  useEffect(load, []);

  const now = Date.now();
  return (
    <Card sx={{ mt: 3 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>Privacy (DPDP)</Typography>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <Typography variant="subtitle1">Data principal requests</Typography>
        {requests.length === 0 ? (
          <Typography color="text.secondary">No open requests. People can raise one from the privacy notice link on the careers site.</Typography>
        ) : (
          <List dense>
            {requests.map((r) => {
              const overdue = new Date(r.due_at).getTime() < now && !["completed", "rejected"].includes(r.status);
              return (
                <ListItem key={r.id} secondaryAction={!r.identity_verified && r.status !== "completed" ? <Button size="small" onClick={() => privacyApi.verify(r.id).then(load)}>Mark identity verified</Button> : null}>
                  <ListItemText primary={`${r.type} · ${r.subject_email}`} secondary={`${r.status} · due ${new Date(r.due_at).toLocaleDateString()}`} />
                  {overdue && <Chip size="small" color="error" label="Overdue" sx={{ mr: 1 }} />}
                  {r.legal_hold && <Chip size="small" label="Legal hold" sx={{ mr: 1 }} />}
                </ListItem>
              );
            })}
          </List>
        )}
        <Typography variant="subtitle1" sx={{ mt: 2 }}>Breach register</Typography>
        {breaches.length === 0 ? (
          <Typography color="text.secondary">No incidents recorded.</Typography>
        ) : (
          <List dense>
            {breaches.map((b) => (
              <ListItem key={b.id}>
                <ListItemText primary={b.title} secondary={`${b.severity} · ${b.status} · detected ${new Date(b.detected_at).toLocaleString()}`} />
              </ListItem>
            ))}
          </List>
        )}
      </CardContent>
    </Card>
  );
}
