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
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, serviceDeskApi, type AssetRow, type SeparationSummary, type TicketRow } from "../api/client";
import { t as tr } from "../i18n";
import ListToolbar, { type ListColumn, type ListViewState } from "./ListToolbar";

// Part 11 (docs/HRMS_COMPLETE_SPEC.txt): helpdesk queue with SLA state, asset register,
// open separations with clearance progress. Ticket detail/agent workspace, asset
// allocation dialogs and the clearance board have complete backend APIs but no screens
// yet (see docs/build_log.md Part 11).

const TICKET_COLUMNS: ListColumn[] = [
  { key: "number", label: "Ticket" }, { key: "subject", label: "Subject" }, { key: "category_code", label: "Category" },
  { key: "priority", label: "Priority" }, { key: "status", label: "Status" }, { key: "sla", label: tr("helpdesk.response_time") },
];

function SlaChip({ t }: { t: TicketRow }) {
  if (!t.sla?.has_sla) return null;
  return (
    <Chip size="small" color={t.sla.resolution_breached ? "error" : (t.sla.resolution_elapsed_pct ?? 0) >= 80 ? "warning" : "default"}
      label={t.sla.resolution_breached ? tr("helpdesk.response_missed") : tr("helpdesk.response_used", { pct: Math.round(t.sla.resolution_elapsed_pct ?? 0) })} />
  );
}

// Reference implementation of the Part 14 list standard: ListToolbar (saved views, column
// chooser, export, RefreshButton), table view by default (L-N4), empty state that says what to do.
function TicketsTab() {
  const [rows, setRows] = useState<TicketRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ListViewState>({ columns: TICKET_COLUMNS.map((c) => c.key), filters: {} });
  const load = () => {
    setLoading(true);
    serviceDeskApi.tickets().then((r) => setRows(r.items)).catch((err) => setError(extractErrorMessage(err, "Failed to load tickets"))).finally(() => setLoading(false));
  };
  useEffect(load, []);
  if (error) return <Alert severity="error">{error}</Alert>;
  const shown = TICKET_COLUMNS.filter((c) => view.columns.includes(c.key));
  return (
    <>
      <ListToolbar listKey="helpdesk.tickets" columns={TICKET_COLUMNS} state={view} onStateChange={setView}
        rows={rows as unknown as Record<string, unknown>[]} loading={loading} onRefresh={load} />
      {rows.length === 0 && !loading ? (
        <Typography color="text.secondary">{tr("settings.helpdesk.empty")}</Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>{shown.map((c) => <TableCell key={c.key}>{c.label}</TableCell>)}</TableRow>
          </TableHead>
          <TableBody>
            {rows.map((t) => (
              <TableRow key={t.id} hover>
                {shown.map((c) => (
                  <TableCell key={c.key}>
                    {c.key === "sla" ? <SlaChip t={t} /> : c.key === "subject" ? (
                      <Stack direction="row" spacing={1} alignItems="center">
                        <span>{t.subject}</span>
                        {t.confidential && <Chip size="small" label="Confidential" />}
                      </Stack>
                    ) : String((t as unknown as Record<string, unknown>)[c.key] ?? "")}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </>
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
