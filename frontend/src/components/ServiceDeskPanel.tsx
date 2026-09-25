import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, serviceDeskApi, type AssetRow, type SeparationSummary, type TicketRow } from "../api/client";

// Part 11 (docs/HRMS_COMPLETE_SPEC.txt): helpdesk queue with SLA state, asset register,
// open separations with clearance progress. Ticket detail/agent workspace, asset
// allocation dialogs and the clearance board have complete backend APIs but no screens
// yet (see docs/build_log.md Part 11).

function TicketsTab() {
  const [rows, setRows] = useState<TicketRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    serviceDeskApi.tickets().then((r) => setRows(r.items)).catch((err) => setError(extractErrorMessage(err, "Failed to load tickets")));
  }, []);
  if (error) return <Alert severity="error">{error}</Alert>;
  if (rows.length === 0) return <Typography color="text.secondary">No tickets. Add ticket categories under Masters and an SLA policy to start the helpdesk.</Typography>;
  return (
    <List dense>
      {rows.map((t) => (
        <ListItem key={t.id}>
          <ListItemText primary={`${t.number} · ${t.subject}`} secondary={`${t.category_code} · ${t.priority} · ${t.status}`} />
          <Stack direction="row" spacing={1}>
            {t.confidential && <Chip size="small" label="Confidential" />}
            {t.sla?.has_sla && (
              <Chip size="small" color={t.sla.resolution_breached ? "error" : (t.sla.resolution_elapsed_pct ?? 0) >= 80 ? "warning" : "default"}
                label={t.sla.resolution_breached ? "SLA breached" : `${Math.round(t.sla.resolution_elapsed_pct ?? 0)}% of SLA`} />
            )}
          </Stack>
        </ListItem>
      ))}
    </List>
  );
}

function AssetsTab() {
  const [rows, setRows] = useState<AssetRow[]>([]);
  useEffect(() => {
    serviceDeskApi.assets().then((r) => setRows(r.items)).catch(() => undefined);
  }, []);
  if (rows.length === 0) return <Typography color="text.secondary">No assets registered. Add asset categories under Masters, then register assets.</Typography>;
  return (
    <List dense>
      {rows.map((a) => (
        <ListItem key={a.id}>
          <ListItemText primary={`${a.asset_tag} · ${a.name}`} secondary={`${a.category_code}${a.book_value != null ? ` · book value ${a.book_value}` : ""}`} />
          <Chip size="small" label={a.status.replace("_", " ")} color={a.status === "allocated" ? "primary" : "default"} />
        </ListItem>
      ))}
    </List>
  );
}

function SeparationsTab() {
  const [rows, setRows] = useState<SeparationSummary[]>([]);
  useEffect(() => {
    serviceDeskApi.separations().then(setRows).catch(() => undefined);
  }, []);
  if (rows.length === 0) return <Typography color="text.secondary">No separations in progress.</Typography>;
  return (
    <List dense>
      {rows.map((s) => (
        <ListItem key={s.separation_id}>
          <ListItemText primary={`${s.type} · ${s.status}`} secondary={`LWD ${s.last_working_day ?? "not approved"} · ${s.clearance_pending} clearance item(s) pending`} />
          {s.assets_pending > 0 && <Chip size="small" color="warning" label={`${s.assets_pending} asset(s) to recover`} />}
        </ListItem>
      ))}
    </List>
  );
}

export default function ServiceDeskPanel() {
  const [tab, setTab] = useState(0);
  return (
    <Card sx={{ mt: 3 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>Helpdesk, assets & exits</Typography>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
          <Tab label="Tickets" />
          <Tab label="Assets" />
          <Tab label="Separations" />
        </Tabs>
        {tab === 0 && <TicketsTab />}
        {tab === 1 && <AssetsTab />}
        {tab === 2 && <SeparationsTab />}
      </CardContent>
    </Card>
  );
}
