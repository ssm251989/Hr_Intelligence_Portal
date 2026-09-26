import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import DragIndicatorIcon from "@mui/icons-material/DragIndicator";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import LinearProgress from "@mui/material/LinearProgress";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { experienceApi, reportsApi, type InboxItem } from "../../api/client";
import { homeApi, type FeedbackDue, type GoalRow, type HiringFlow, type HomeAlert, type MyAsset, type MyTicket, type Office, type TeamMember } from "../../api/homeApi";
import type { CandidatesDashboardStatsResponse, InterviewsDashboardStatsResponse, JobsDashboardStatsResponse } from "../../api/types";
import { useT } from "../../i18n";
import { EmptyState, Emoji, StatTile, StatusChip, UserAvatar } from "../../ui-kit";
import AdminHomeChecklist from "../AdminHomeChecklist";

// Part 15.5: the boxes on the role-based home pages. Each widget loads its own data so one
// slow or forbidden source never blanks the whole page.

const HiringSankey = lazy(() => import("./HiringSankey"));
const OfficeMap = lazy(() => import("./OfficeMap"));

/** Load once; `null` = still loading, `false` = failed/forbidden. */
function useLoad<T>(fn: () => Promise<T>): T | null | false {
  const [data, setData] = useState<T | null | false>(null);
  useEffect(() => {
    let live = true;
    fn().then((d) => live && setData(d)).catch(() => live && setData(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return data;
}

export function WidgetCard({ title, sub, emoji, editing, children, action }: {
  title: string; sub?: string; emoji?: string; editing?: boolean; children: ReactNode; action?: ReactNode;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  return (
    <Card component="section" sx={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden", outline: editing ? `2px dashed ${f.line}` : "none" }}>
      <Stack direction="row" alignItems="center" spacing={1} className={editing ? "widget-drag" : undefined}
        sx={{ px: 2.25, pt: 2, pb: 1, cursor: editing ? "grab" : "default", userSelect: editing ? "none" : "auto" }}>
        {editing && <DragIndicatorIcon fontSize="small" sx={{ color: f.muted }} aria-label={t("home.drag")} />}
        {emoji && <Emoji name={emoji} size={18} />}
        <Typography component="h2" sx={{ fontWeight: 800, fontSize: 16, flex: 1, minWidth: 0 }} noWrap>
          {title} {sub && <Box component="em" sx={{ fontStyle: "normal", color: f.muted, fontWeight: 500, fontSize: 13, ml: 0.5 }}>{sub}</Box>}
        </Typography>
        {action}
      </Stack>
      <Box sx={{ px: 2.25, pb: 2, flex: 1, minHeight: 0, overflow: "auto" }}>{children}</Box>
    </Card>
  );
}

function Loading() {
  return (
    <Stack spacing={1}>
      <Skeleton variant="rounded" height={36} />
      <Skeleton variant="rounded" height={36} />
      <Skeleton variant="rounded" height={36} />
    </Stack>
  );
}

function Failed() {
  const t = useT();
  return <Typography sx={{ color: "text.secondary", py: 2 }}>{t("home.load_failed")}</Typography>;
}

function Row({ emoji, title, sub, right, to }: { emoji: string; title: ReactNode; sub?: ReactNode; right?: ReactNode; to?: string }) {
  const f = useTheme().palette.fresh;
  return (
    <Box component={to ? RouterLink : "div"} {...(to ? { to } : {})}
      sx={{ display: "flex", alignItems: "center", gap: 1.5, p: "10px 12px", borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}`,
        textDecoration: "none", color: "inherit", ...(to ? { "&:hover": { borderColor: f.brand }, "&:focus-visible": { outline: `2px solid ${f.brand}` } } : {}) }}>
      <Emoji name={emoji} size={20} />
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography sx={{ fontWeight: 700, fontSize: 14 }} noWrap>{title}</Typography>
        {sub && <Typography sx={{ color: f.muted, fontSize: 12.5 }} noWrap>{sub}</Typography>}
      </Box>
      {right}
    </Box>
  );
}

// ---------- HR ----------

export function StatsWidget() {
  const t = useT();
  const jobs = useLoad<JobsDashboardStatsResponse>(() => reportsApi.jobsDashboardStats());
  const cands = useLoad<CandidatesDashboardStatsResponse>(() => reportsApi.candidatesDashboardStats());
  const ints = useLoad<InterviewsDashboardStatsResponse>(() => reportsApi.interviewsDashboardStats());
  const val = <T,>(d: T | null | false, pick: (x: T) => number) => (d ? pick(d) : d === false ? "–" : 0);
  return (
    <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" }, height: "100%" }}>
      <StatTile emoji="briefcase" tone="sky" label={t("home.stat.open_jobs")} loading={jobs === null} to="/jobs"
        value={val(jobs, (j) => j.active_jobs)} trend={jobs ? t("home.stat.positions", { count: jobs.open_positions }) : undefined} trendDirection="flat" />
      <StatTile emoji="technologist" tone="brand" label={t("home.stat.in_progress")} loading={cands === null} to="/candidates/list"
        value={val(cands, (c) => c.active_candidates)} trend={cands ? t("home.stat.new", { count: cands.new_this_month }) : undefined} />
      <StatTile emoji="calendar" tone="sun" label={t("home.stat.interviews")} loading={ints === null} to="/interviews/dashboard"
        value={val(ints, (i) => i.total_interviews_scheduled_this_month)} trend={ints ? t("home.stat.upcoming", { count: ints.upcoming }) : undefined} trendDirection="flat" />
      <StatTile emoji="party" tone="coral" label={t("home.stat.joining")} loading={jobs === null} to="/offers"
        value={val(jobs, (j) => j.hires_this_month)} />
    </Box>
  );
}

export function HiringFlowWidget({ editing }: { editing?: boolean }) {
  const t = useT();
  const flow = useLoad<HiringFlow>(() => homeApi.hiringFlow());
  return (
    <WidgetCard title={t("home.w.flow")} sub={t("home.w.flow_sub")} emoji="chart_up" editing={editing}>
      {flow === null ? <Loading /> : flow === false ? <Failed /> : flow.total === 0 ? (
        <EmptyState compact illustration="hiring" title={t("home.flow.empty")} />
      ) : (
        <Suspense fallback={<Loading />}><HiringSankey flow={flow} /></Suspense>
      )}
    </WidgetCard>
  );
}

const KIND_EMOJI: Record<string, string> = { approval: "writing_hand", ai_suggestion: "robot", review: "memo", clearance: "door" };

function dueChip(dueAt: string | null, t: ReturnType<typeof useT>) {
  if (!dueAt) return <StatusChip status="new" />;
  const ms = new Date(dueAt).getTime() - Date.now();
  if (ms < 0) return <StatusChip status="overdue" label={t("home.todo.late")} />;
  const hours = Math.round(ms / 3_600_000);
  if (hours < 24) return <StatusChip status="due_soon" label={t("home.todo.due_in", { when: hours <= 1 ? "1h" : `${hours}h` })} />;
  return <StatusChip tone="sky" emoji="calendar" label={new Date(dueAt).toLocaleDateString(undefined, { day: "numeric", month: "short" })} />;
}

export function TodoWidget({ editing }: { editing?: boolean }) {
  const t = useT();
  const items = useLoad<InboxItem[]>(() => experienceApi.inbox());
  const sorted = items ? [...items].sort((a, b) => (a.due_at ? new Date(a.due_at).getTime() : Infinity) - (b.due_at ? new Date(b.due_at).getTime() : Infinity)) : [];
  return (
    <WidgetCard title={t("home.w.todo")} sub={t("home.w.todo_sub")} emoji="clipboard" editing={editing}
      action={items && items.length > 6 ? <Button size="small" component={RouterLink} to="/approvals">{t("home.todo.more", { count: items.length })}</Button> : undefined}>
      {items === null ? <Loading /> : items === false ? <Failed /> : sorted.length === 0 ? (
        <EmptyState compact illustration="completed-tasks" title={t("home.todo.empty")} />
      ) : (
        <Stack spacing={1}>
          {sorted.slice(0, 6).map((i) => (
            <Row key={`${i.kind}-${i.id}`} emoji={KIND_EMOJI[i.kind] ?? "clipboard"} title={i.title} to={i.path || "/approvals"}
              sub={i.subtitle ? i.subtitle.replace(/_/g, " ") : undefined} right={dueChip(i.due_at, t)} />
          ))}
        </Stack>
      )}
    </WidgetCard>
  );
}

export function AlertsWidget({ editing }: { editing?: boolean }) {
  const t = useT();
  const data = useLoad<{ alerts: HomeAlert[] }>(() => homeApi.alerts());
  return (
    <WidgetCard title={t("home.w.alerts")} sub={t("home.w.alerts_sub")} emoji="bell" editing={editing}>
      {data === null ? <Loading /> : data === false ? <Failed /> : data.alerts.length === 0 ? (
        <EmptyState compact illustration="done" title={t("home.alert.none")} />
      ) : (
        <Stack spacing={1}>
          {data.alerts.map((a) => (
            <Row key={a.key} emoji={a.emoji} title={t(`home.alert.${a.key}`, { count: a.count })} to={a.path}
              right={<StatusChip tone={a.tone} emoji={a.tone === "coral" ? "fire" : "alarm_clock"} label={t("home.alert.open")} />} />
          ))}
        </Stack>
      )}
    </WidgetCard>
  );
}

export function OfficesWidget({ editing }: { editing?: boolean }) {
  const t = useT();
  const data = useLoad<{ offices: Office[] }>(() => homeApi.offices());
  return (
    <WidgetCard title={t("home.w.offices")} sub={t("home.w.offices_sub")} emoji="world_map" editing={editing}>
      {data === null ? <Loading /> : data === false ? <Failed /> : data.offices.length === 0 ? (
        <EmptyState compact illustration="map" title={t("home.offices.empty")}
          action={<Button variant="outlined" component={RouterLink} to="/settings#core-hr">{t("home.offices.add")}</Button>} />
      ) : (
        <Suspense fallback={<Loading />}><OfficeMap offices={data.offices} /></Suspense>
      )}
    </WidgetCard>
  );
}

export function SetupWidget() {
  return <AdminHomeChecklist />;
}

// ---------- Manager ----------

export function TeamWidget({ editing }: { editing?: boolean }) {
  const t = useT();
  const data = useLoad<{ people: TeamMember[] }>(() => homeApi.myTeam());
  return (
    <WidgetCard title={t("home.w.team")} emoji="people" editing={editing}>
      {data === null ? <Loading /> : data === false ? <Failed /> : data.people.length === 0 ? (
        <EmptyState compact illustration="team-spirit" title={t("home.team.empty")} />
      ) : (
        <Stack spacing={1}>
          {data.people.map((p) => (
            <Stack key={p.id} direction="row" spacing={1.5} alignItems="center" component={RouterLink} to={`/employees/${p.id}`}
              sx={{ textDecoration: "none", color: "inherit", p: 0.75, borderRadius: "10px", "&:hover": { bgcolor: "action.hover" } }}>
              <UserAvatar name={p.name} size={34} />
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography sx={{ fontWeight: 700, fontSize: 14 }} noWrap>{p.name}</Typography>
                {p.designation && <Typography variant="caption" noWrap component="div">{p.designation}</Typography>}
              </Box>
              <StatusChip status={p.status} />
            </Stack>
          ))}
        </Stack>
      )}
    </WidgetCard>
  );
}

export function FeedbackWidget({ editing }: { editing?: boolean }) {
  const t = useT();
  const data = useLoad<{ items: FeedbackDue[] }>(() => homeApi.myFeedback());
  return (
    <WidgetCard title={t("home.w.feedback")} emoji="speaking_head" editing={editing}>
      {data === null ? <Loading /> : data === false ? <Failed /> : data.items.length === 0 ? (
        <EmptyState compact illustration="done" title={t("home.feedback.empty")} />
      ) : (
        <Stack spacing={1}>
          {data.items.map((i) => (
            <Row key={i.id} emoji={i.past ? "writing_hand" : "calendar"} title={i.candidate ?? "—"}
              sub={new Date(i.scheduled_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
              right={i.past ? (
                <Button size="small" variant="contained" component={RouterLink} to="/interviews/my">{t("home.feedback.give")}</Button>
              ) : i.meeting_link ? (
                <Button size="small" variant="outlined" href={i.meeting_link} target="_blank" rel="noopener">{t("home.feedback.join")}</Button>
              ) : undefined} />
          ))}
        </Stack>
      )}
    </WidgetCard>
  );
}

function GoalList({ goals }: { goals: GoalRow[] }) {
  return (
    <Stack spacing={1.5}>
      {goals.map((g) => (
        <Box key={g.id}>
          <Stack direction="row" justifyContent="space-between" spacing={1}>
            <Typography sx={{ fontWeight: 600, fontSize: 14 }} noWrap>{g.title}</Typography>
            <Typography sx={{ fontWeight: 700, fontSize: 13, fontVariantNumeric: "tabular-nums" }}>{Math.round(g.progress_pct)}%</Typography>
          </Stack>
          <LinearProgress variant="determinate" value={Math.min(100, g.progress_pct)} sx={{ mt: 0.5 }} aria-label={`${g.title}: ${Math.round(g.progress_pct)}%`} />
        </Box>
      ))}
    </Stack>
  );
}

export function GoalsWidget({ editing, team }: { editing?: boolean; team?: boolean }) {
  const t = useT();
  const data = useLoad<{ mine: GoalRow[]; team: GoalRow[] }>(() => homeApi.myGoals());
  const goals = data ? (team ? data.team : data.mine) : [];
  return (
    <WidgetCard title={team ? t("home.w.goals") : t("home.w.my_goals")} emoji="target" editing={editing}>
      {data === null ? <Loading /> : data === false ? <Failed /> : goals.length === 0 ? (
        <EmptyState compact illustration="goals" title={t("home.goals.empty")}
          action={<Button variant="outlined" component={RouterLink} to="/performance">{t("home.goals.add")}</Button>} />
      ) : <GoalList goals={goals.slice(0, 8)} />}
    </WidgetCard>
  );
}

// ---------- Employee ----------

export function TicketsWidget({ editing }: { editing?: boolean }) {
  const t = useT();
  const data = useLoad<MyTicket[]>(() => homeApi.myTickets());
  return (
    <WidgetCard title={t("home.w.tickets")} emoji="ring_buoy" editing={editing}
      action={<Button size="small" component={RouterLink} to="/helpdesk">{t("home.tickets.raise")}</Button>}>
      {data === null ? <Loading /> : data === false ? <Failed /> : data.length === 0 ? (
        <EmptyState compact illustration="helpful-sign" title={t("home.tickets.empty")} />
      ) : (
        <Stack spacing={1}>
          {data.slice(0, 6).map((tk) => <Row key={tk.id} emoji="ring_buoy" title={tk.subject} sub={tk.number} to="/helpdesk" right={<StatusChip status={tk.status} />} />)}
        </Stack>
      )}
    </WidgetCard>
  );
}

export function AssetsWidget({ editing }: { editing?: boolean }) {
  const t = useT();
  const data = useLoad<MyAsset[]>(() => homeApi.myAssets());
  return (
    <WidgetCard title={t("home.w.assets")} emoji="laptop" editing={editing}>
      {data === null ? <Loading /> : data === false ? <Failed /> : data.length === 0 ? (
        <EmptyState compact illustration="devices" title={t("home.assets.empty")} />
      ) : (
        <Stack spacing={1}>
          {data.map((a) => (
            <Row key={a.allocation_id} emoji="laptop" title={a.name ?? a.asset_tag ?? "—"} sub={a.acknowledged ? a.category : t("home.assets.ack_needed")} to="/assets"
              right={a.acknowledged ? <StatusChip status="done" /> : <StatusChip status="due_soon" />} />
          ))}
        </Stack>
      )}
    </WidgetCard>
  );
}

export function LettersWidget({ editing }: { editing?: boolean }) {
  const t = useT();
  const data = useLoad(() => experienceApi.myLetters());
  const [open, setOpen] = useState<string | null>(null);
  return (
    <WidgetCard title={t("home.w.letters")} emoji="page" editing={editing}>
      {data === null ? <Loading /> : data === false ? <Failed /> : data.length === 0 ? (
        <EmptyState compact illustration="signed-document" title={t("home.letters.empty")} />
      ) : (
        <Stack spacing={1}>
          {data.map((l) => (
            <Box key={l.id}>
              <Row emoji="page" title={l.template_key.replace(/[._]/g, " ")}
                right={<Button size="small" onClick={() => setOpen(open === l.id ? null : l.id)}>{t("home.letters.open")}</Button>} />
              {open === l.id && (
                // Sandboxed (no scripts, no same-origin): the letter's HTML never runs inside the app.
                <Box component="iframe" title={l.template_key} sandbox="" srcDoc={l.html}
                  sx={{ mt: 1, width: "100%", height: 320, border: 1, borderColor: "divider", borderRadius: "12px", bgcolor: "common.white" }} />
              )}
            </Box>
          ))}
        </Stack>
      )}
    </WidgetCard>
  );
}
