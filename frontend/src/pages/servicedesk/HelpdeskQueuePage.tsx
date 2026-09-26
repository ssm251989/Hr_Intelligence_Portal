// Part 15.6 -- /helpdesk/queue (L T2, T3): the agents' table -- 25 rows, ListToolbar,
// response-time countdown chips in words ("Reply in 2h 10m" / "Late by 30m"), assign,
// next step and the conversation in the ticket dialog.
import { useCallback, useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import FormControlLabel from "@mui/material/FormControlLabel";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { serviceDeskExtra, type AgentsInfo, type Ticket, type TicketMeta } from "../../api/serviceDeskExtra";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import ListToolbar, { type ListColumn, type ListViewState } from "../../components/ListToolbar";
import TicketDetailDialog from "../../components/servicedesk/TicketDetailDialog";
import { EscalationChip, PriorityChip, TicketClockChip, TicketStatusChip, ticketClock, useCategories, useNow, useToast } from "../../components/servicedesk/shared";
import { useT } from "../../i18n";
import { Cell, EmptyState, Emoji, explainError, FriendlyError, InfoTip, PageGrid, PageHeader, StatTile, StatusChip } from "../../ui-kit";

const STATUS_TABS = [
  { value: "open", key: "helpdesk.filter.open" },
  { value: "in_progress", key: "helpdesk.filter.in_progress" },
  { value: "waiting_on_requester", key: "helpdesk.filter.waiting" },
  { value: "resolved", key: "helpdesk.filter.resolved" },
  { value: "", key: "helpdesk.filter.all" },
];

export default function HelpdeskQueuePage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { can } = useMeBootstrap();
  const canView = can("helpdesk.ticket.view");
  const canEdit = can("helpdesk.ticket.edit");
  const cats = useCategories("ticket");
  const now = useNow();
  const [toast, show] = useToast();

  const [status, setStatus] = useState("open");
  const [team, setTeam] = useState("");
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<Ticket[]>([]);
  const [total, setTotal] = useState(0);
  const [meta, setMeta] = useState<Record<string, TicketMeta>>({});
  const [agents, setAgents] = useState<AgentsInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [taking, setTaking] = useState(false);

  const columns: ListColumn[] = useMemo(() => [
    { key: "number", label: t("helpdesk.col.number") },
    { key: "subject", label: t("helpdesk.col.subject") },
    { key: "category", label: t("helpdesk.col.category") },
    { key: "priority", label: t("helpdesk.col.priority") },
    { key: "requester", label: t("helpdesk.col.requester") },
    { key: "assignee", label: t("helpdesk.col.assignee") },
    { key: "team", label: t("helpdesk.col.team") },
    { key: "status", label: t("helpdesk.col.status") },
    { key: "clock", label: t("helpdesk.col.clock") },
  ], [t]);
  const [view, setView] = useState<ListViewState>({ columns: ["number", "subject", "category", "priority", "requester", "assignee", "status", "clock"], filters: {} });
  const show_ = (k: string) => view.columns.includes(k);

  const load = useCallback(() => {
    if (!canView) return;
    setLoading(true);
    setError(null);
    serviceDeskExtra.queue({ status: status || undefined, team: team || undefined, mine, page: page + 1 })
      .then((res) => {
        setRows(res.items);
        setTotal(res.total);
        if (res.items.length) return serviceDeskExtra.ticketsMeta(res.items.map((x) => x.id)).then(setMeta);
        setMeta({});
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [canView, status, team, mine, page]);
  useEffect(load, [load]);
  useEffect(() => {
    if (canView) serviceDeskExtra.agents().then(setAgents).catch(() => undefined);
  }, [canView]);

  const clocks = rows.map((r) => ticketClock(t, r, meta[r.id], now));
  const late = clocks.filter((c) => c.kind === "late").length;
  const soon = clocks.filter((c) => c.kind === "soon").length;
  const unassigned = rows.filter((r) => !r.assignee_user_id && !["resolved", "closed", "cancelled"].includes(r.status)).length;

  const me = agents?.agents.find((a) => a.me);
  const takeNext = async () => {
    setTaking(true);
    try {
      const res = await serviceDeskExtra.queue({ status: "open", team: team || undefined, page: 1 });
      // oldest first, then the one closest to its response time
      const free = res.items.filter((x) => !x.assignee_user_id).sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
      if (!free.length || !me) {
        show(t("helpdesk.queue.nothing_next"), "info");
        return;
      }
      const tk = await serviceDeskExtra.assign(free[0].id, me.id, free[0].queue_code);
      show(t("helpdesk.queue.took", { number: tk.number }));
      setOpenId(tk.id);
      load();
    } catch (e) {
      show(explainError(e).what, "error");
    } finally {
      setTaking(false);
    }
  };

  const exportRows = rows.map((r, i) => ({
    number: r.number, subject: r.subject, category: cats.label(r.category_code), priority: t(`helpdesk.priority.${r.priority}`),
    requester: meta[r.id]?.requester_name ?? "", assignee: meta[r.id]?.assignee_name ?? "", team: meta[r.id]?.team_name ?? "",
    status: r.status, clock: clocks[i]?.label ?? "",
  }));

  if (!canView) {
    return (
      <Box>
        <PageHeader emoji="ring_buoy" title={t("helpdesk.queue.title")} purpose={t("helpdesk.queue.purpose")} />
        <FriendlyError what={t("error.no_access")} fix={t("error.no_access_fix")} actionLabel={t("helpdesk.queue.my_tickets")} actionTo="/helpdesk" />
      </Box>
    );
  }

  return (
    <Box>
      <PageHeader
        emoji="ring_buoy"
        title={t("helpdesk.queue.title")}
        purpose={t("helpdesk.queue.purpose")}
        tourKey="helpdesk_queue"
        primary={canEdit ? (
          <Button variant="contained" onClick={takeNext} disabled={taking || !me} startIcon={<Emoji name="thumbs_up" size={16} />}>{t("helpdesk.queue.take_next")}</Button>
        ) : undefined}
        extra={<Button component={RouterLink} to="/helpdesk">{t("helpdesk.queue.my_tickets")}</Button>}
      />

      <PageGrid sx={{ mb: 2.25 }}>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="inbox" value={total} label={t("helpdesk.stat.total", { count: total })} tone="sky" loading={loading} /></Cell>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="fire" value={late} label={t("helpdesk.stat.late", { count: late })} tone="coral" loading={loading} /></Cell>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="alarm_clock" value={soon} label={t("helpdesk.stat.soon")} tone="sun" loading={loading} /></Cell>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="question" value={unassigned} label={t("helpdesk.stat.unassigned")} tone="muted" loading={loading} /></Cell>
      </PageGrid>

      <Card sx={{ p: { xs: 1.5, md: 2 } }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }} sx={{ mb: 1 }}>
          <Tabs value={status} onChange={(_, v) => { setStatus(v); setPage(0); }} variant="scrollable" allowScrollButtonsMobile aria-label={t("helpdesk.filter.status")}>
            {STATUS_TABS.map((s) => <Tab key={s.value || "all"} value={s.value} label={t(s.key)} />)}
          </Tabs>
          <Box sx={{ flex: 1 }} />
          {(agents?.teams.length ?? 0) > 0 && (
            <TextField select size="small" label={t("helpdesk.filter.team")} value={team} onChange={(e) => { setTeam(e.target.value); setPage(0); }} sx={{ minWidth: 180 }}>
              <MenuItem value="">{t("helpdesk.filter.any_team")}</MenuItem>
              {agents!.teams.map((q) => <MenuItem key={q.code} value={q.code}>{q.name}</MenuItem>)}
            </TextField>
          )}
          <FormControlLabel control={<Switch checked={mine} onChange={(e) => { setMine(e.target.checked); setPage(0); }} />} label={t("helpdesk.filter.mine")} />
        </Stack>

        <ListToolbar listKey="helpdesk.queue" columns={columns} state={view} onStateChange={setView} rows={exportRows} loading={loading} onRefresh={load} />
        {loading && <LinearProgress aria-label={t("helpdesk.common.loading")} sx={{ mb: 1 }} />}

        {error ? <FriendlyError error={error} onRetry={load} compact /> : rows.length === 0 && !loading ? (
          <EmptyState illustration="done" title={t("helpdesk.queue.empty")} hint={t("helpdesk.queue.empty_hint")} compact />
        ) : (
          <TableContainer>
            <Table size="small" aria-label={t("helpdesk.queue.title")}>
              <TableHead>
                <TableRow>
                  {show_("number") && <TableCell>{t("helpdesk.col.number")}</TableCell>}
                  {show_("subject") && <TableCell>{t("helpdesk.col.subject")}</TableCell>}
                  {show_("category") && <TableCell>{t("helpdesk.col.category")}</TableCell>}
                  {show_("priority") && <TableCell>{t("helpdesk.col.priority")}</TableCell>}
                  {show_("requester") && <TableCell>{t("helpdesk.col.requester")}</TableCell>}
                  {show_("assignee") && <TableCell>{t("helpdesk.col.assignee")}</TableCell>}
                  {show_("team") && <TableCell>{t("helpdesk.col.team")}</TableCell>}
                  {show_("status") && <TableCell>{t("helpdesk.col.status")}</TableCell>}
                  {show_("clock") && <TableCell>{t("helpdesk.col.clock")}<InfoTip text={t("helpdesk.clock.tip")} /></TableCell>}
                  <TableCell align="right"><Box component="span" sx={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>{t("helpdesk.common.more")}</Box></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((r) => {
                  const m = meta[r.id];
                  return (
                    <TableRow key={r.id} hover sx={{ cursor: "pointer" }} onClick={() => setOpenId(r.id)}>
                      {show_("number") && <TableCell sx={{ fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{r.number}</TableCell>}
                      {show_("subject") && (
                        <TableCell sx={{ maxWidth: 360 }}>
                          <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                            {r.confidential && <Emoji name="lock" size={14} label={t("helpdesk.detail.confidential")} />}
                            <Typography sx={{ fontWeight: 600, fontSize: 14 }} noWrap>{r.subject}</Typography>
                            <EscalationChip level={r.escalation_level} />
                          </Stack>
                        </TableCell>
                      )}
                      {show_("category") && <TableCell>{cats.label(r.category_code)}</TableCell>}
                      {show_("priority") && <TableCell><PriorityChip priority={r.priority} /></TableCell>}
                      {show_("requester") && <TableCell>{m?.requester_name ?? "—"}</TableCell>}
                      {show_("assignee") && (
                        <TableCell>{m?.assignee_name ?? <StatusChip tone="muted" emoji="question" label={t("helpdesk.detail.unassigned")} />}</TableCell>
                      )}
                      {show_("team") && <TableCell>{m?.team_name ?? "—"}</TableCell>}
                      {show_("status") && <TableCell><TicketStatusChip status={r.status} /></TableCell>}
                      {show_("clock") && <TableCell><TicketClockChip ticket={r} meta={m} now={now} /></TableCell>}
                      <TableCell align="right">
                        <Button size="small" onClick={(e) => { e.stopPropagation(); setOpenId(r.id); }}>{t("helpdesk.common.open")}</Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
        <TablePagination component="div" count={total} page={page} onPageChange={(_, p) => setPage(p)} rowsPerPage={25} rowsPerPageOptions={[25]}
          labelDisplayedRows={({ from, to, count }) => t("helpdesk.common.rows", { from, to, count })} />
        <Typography sx={{ fontSize: 12, color: f.muted }}>{t("helpdesk.clock.tip")}</Typography>
      </Card>

      <TicketDetailDialog ticketId={openId} open={Boolean(openId)} onClose={() => setOpenId(null)} onChanged={load} agent canEdit={canEdit}
        categoryLabel={cats.label} agents={agents} />
      {toast}
    </Box>
  );
}
