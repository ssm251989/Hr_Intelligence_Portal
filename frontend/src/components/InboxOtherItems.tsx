import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { experienceApi, extractErrorMessage, intelligenceApi, type InboxItem } from "../api/client";

// Part 14 section 4 (docs/HRMS_COMPLETE_SPEC.txt): the Unified Inbox also carries every
// non-workflow item waiting on the caller -- AI agent suggestions (approve / reject; nothing
// happens until you do), reviews to write, clearance items. Workflow approvals stay in the
// table above (unchanged behaviour, still approvable from email).

const KIND_LABEL: Record<string, string> = { ai_suggestion: "AI suggestion", review: "Review", clearance: "Clearance" };

export default function InboxOtherItems() {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    experienceApi
      .inbox()
      .then((rows) => setItems(rows.filter((r) => r.kind !== "approval")))
      .catch((err) => setError(extractErrorMessage(err, "Failed to load your other tasks")));
  useEffect(() => {
    load();
  }, []);

  const decide = (item: InboxItem, action: "approve" | "reject") =>
    intelligenceApi.decideSuggestion(item.id, action).then(load).catch((err) => setError(extractErrorMessage(err, "Decision failed")));

  return (
    <Paper variant="outlined" sx={{ mt: 3, p: 2 }}>
      <Typography variant="h6" gutterBottom>Also waiting on you</Typography>
      {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
      {items.length === 0 ? (
        <Typography variant="body2" color="text.secondary">Nothing else right now. AI suggestions, reviews to write and exit clearance items appear here.</Typography>
      ) : (
        <List dense>
          {items.map((item) => (
            <ListItem key={`${item.kind}-${item.id}`}
              secondaryAction={
                item.kind === "ai_suggestion" ? (
                  <Stack direction="row" spacing={1}>
                    <Button size="small" color="success" onClick={() => decide(item, "approve")}>Approve</Button>
                    <Button size="small" color="error" onClick={() => decide(item, "reject")}>Reject</Button>
                  </Stack>
                ) : (
                  <Button size="small" component={RouterLink} to={item.path}>Open</Button>
                )
              }>
              <Chip size="small" label={KIND_LABEL[item.kind] ?? item.kind} sx={{ mr: 1 }} />
              <ListItemText primary={item.title} secondary={item.subtitle} />
            </ListItem>
          ))}
        </List>
      )}
    </Paper>
  );
}
