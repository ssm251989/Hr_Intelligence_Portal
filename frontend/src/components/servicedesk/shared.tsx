// Part 15.6 -- small pieces shared by the Helpdesk, Assets and Exits pages.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { serviceDeskExtra, type Category, type Ticket, type TicketMeta } from "../../api/serviceDeskExtra";
import { useI18n, useT, type TFunction } from "../../i18n";
import { Emoji, InfoTip, StatusChip, type Tone } from "../../ui-kit";

/** Re-renders every `ms` so countdown chips stay current (text only -- no motion). */
export function useNow(ms = 30000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}

export function formatSpan(t: TFunction, minutes: number): string {
  const m = Math.max(0, Math.round(Math.abs(minutes)));
  if (m >= 24 * 60) return t("helpdesk.time.d", { d: Math.floor(m / 1440), h: Math.floor((m % 1440) / 60) });
  if (m >= 60) return t("helpdesk.time.h", { h: Math.floor(m / 60), m: m % 60 });
  return t("helpdesk.time.m", { m });
}

export function useDateFmt() {
  const { locale } = useI18n();
  const tag = locale === "en" ? "en-IN" : `${locale}-IN`;
  return useMemo(() => {
    const d = new Intl.DateTimeFormat(tag, { day: "numeric", month: "short", year: "numeric" });
    const dt = new Intl.DateTimeFormat(tag, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
    return {
      date: (iso?: string | null) => (iso ? d.format(new Date(iso.length === 10 ? `${iso}T00:00:00` : iso)) : "—"),
      dateTime: (iso?: string | null) => (iso ? dt.format(new Date(iso)) : "—"),
      money: (n?: number | null) => (n == null ? "—" : new Intl.NumberFormat(tag, { maximumFractionDigits: 0 }).format(n)),
    };
  }, [tag]);
}

/** Friendly category names for ticket topics / asset types / exit reasons. */
export function useCategories(kind: "ticket" | "asset" | "exit_reason") {
  const { locale } = useI18n();
  const [list, setList] = useState<Category[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => {
    setError(null);
    serviceDeskExtra.categories(kind, locale).then(setList).catch((e) => { setError(e); setList([]); });
  }, [kind, locale]);
  useEffect(load, [load]);
  const byCode = useMemo(() => Object.fromEntries((list ?? []).map((c) => [c.code, c.label])), [list]);
  const label = useCallback((code?: string | null) => (code ? byCode[code] ?? code.replace(/[_-]+/g, " ") : "—"), [byCode]);
  return { list, error, label, reload: load };
}

/** One toast per page: const [toast, show] = useToast(); show("Saved."). */
export function useToast(): [ReactNode, (msg: string, severity?: "success" | "info" | "warning" | "error") => void] {
  const [state, setState] = useState<{ msg: string; severity: "success" | "info" | "warning" | "error" } | null>(null);
  const node = (
    <Snackbar open={Boolean(state)} autoHideDuration={5000} onClose={() => setState(null)} anchorOrigin={{ vertical: "bottom", horizontal: "center" }}>
      {state ? <Alert severity={state.severity} onClose={() => setState(null)} variant="filled">{state.msg}</Alert> : undefined}
    </Snackbar>
  );
  return [node, useCallback((msg, severity = "success") => setState({ msg, severity }), [])];
}

/** Card with an emoji + title row; fills its grid cell. */
export function Section({ emoji, title, action, children, id, hint }: { emoji: string; title: ReactNode; action?: ReactNode; children: ReactNode; id?: string; hint?: ReactNode }) {
  const f = useTheme().palette.fresh;
  return (
    <Card id={id} component="section" sx={{ p: { xs: 2, md: 2.5 }, height: "100%", display: "flex", flexDirection: "column" }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: hint ? 0.5 : 1.5 }} flexWrap="wrap" useFlexGap>
        <Emoji name={emoji} size={20} />
        <Typography component="h2" sx={{ fontWeight: 800, fontSize: 17, flex: 1, minWidth: 0 }}>{title}</Typography>
        {action}
      </Stack>
      {hint && <Typography sx={{ color: f.muted, fontSize: 14, mb: 1.5 }}>{hint}</Typography>}
      <Box sx={{ flex: 1, minWidth: 0 }}>{children}</Box>
    </Card>
  );
}

// ---- status chips (colour + emoji + word) ----

export function TicketStatusChip({ status, forEmployee }: { status: string; forEmployee?: boolean }) {
  const t = useT();
  if (status === "waiting_on_requester") {
    return <StatusChip tone="sun" emoji="speech" label={t(forEmployee ? "helpdesk.status.waiting_you" : "helpdesk.status.waiting_on_requester")} />;
  }
  if (status === "closed") return <StatusChip tone="muted" emoji="lock" label={t("helpdesk.status.closed")} />;
  return <StatusChip status={status} />;
}

const PRIORITY: Record<string, { tone: Tone; emoji: string }> = {
  low: { tone: "muted", emoji: "seedling" },
  medium: { tone: "sky", emoji: "label" },
  high: { tone: "sun", emoji: "alarm_clock" },
  urgent: { tone: "coral", emoji: "fire" },
};

export function PriorityChip({ priority }: { priority: string }) {
  const t = useT();
  const p = PRIORITY[priority] ?? PRIORITY.medium;
  const key = `helpdesk.priority.${priority}`;
  const label = t(key);
  return <StatusChip tone={p.tone} emoji={p.emoji} label={label === key ? priority : label} />;
}

const ASSET: Record<string, { tone: Tone; emoji: string }> = {
  in_stock: { tone: "ok", emoji: "package" },
  allocated: { tone: "sky", emoji: "handshake" },
  in_repair: { tone: "sun", emoji: "tools" },
  lost: { tone: "coral", emoji: "warning" },
  retired: { tone: "muted", emoji: "pause" },
  disposed: { tone: "muted", emoji: "cross" },
};

export function AssetStatusChip({ status }: { status: string }) {
  const t = useT();
  const s = ASSET[status] ?? { tone: "muted" as Tone, emoji: "label" };
  const key = `assets.status.${status}`;
  const label = t(key);
  return <StatusChip tone={s.tone} emoji={s.emoji} label={label === key ? status.replace(/_/g, " ") : label} />;
}

const REQUEST: Record<string, { tone: Tone; emoji: string }> = {
  requested: { tone: "sun", emoji: "hourglass" },
  approved: { tone: "sky", emoji: "thumbs_up" },
  rejected: { tone: "coral", emoji: "cross" },
  fulfilled: { tone: "ok", emoji: "check" },
};

export function RequestStatusChip({ status }: { status: string }) {
  const t = useT();
  const s = REQUEST[status] ?? { tone: "muted" as Tone, emoji: "label" };
  const key = `assets.reqstatus.${status}`;
  const label = t(key);
  return <StatusChip tone={s.tone} emoji={s.emoji} label={label === key ? status : label} />;
}

const SEPARATION: Record<string, { tone: Tone; emoji: string }> = {
  submitted: { tone: "sky", emoji: "envelope" },
  retention: { tone: "sun", emoji: "speech" },
  approved: { tone: "brand", emoji: "calendar" },
  clearance: { tone: "sun", emoji: "clipboard" },
  completed: { tone: "ok", emoji: "check" },
  withdrawn: { tone: "muted", emoji: "pause" },
};

export function SeparationStatusChip({ status }: { status: string }) {
  const t = useT();
  const s = SEPARATION[status] ?? { tone: "muted" as Tone, emoji: "label" };
  const key = `exits.sepstatus.${status}`;
  const label = t(key);
  return <StatusChip tone={s.tone} emoji={s.emoji} label={label === key ? status : label} />;
}

export function ItemStatusChip({ status }: { status: string }) {
  const t = useT();
  // feat 2026-10-06: actionable exit checklist statuses (done / not_applicable replace cleared / waived)
  if (status === "done" || status === "cleared") return <StatusChip tone="ok" emoji="check" label={t("exits.item.cleared")} />;
  if (status === "not_applicable" || status === "waived") return <StatusChip tone="muted" emoji="pause" label={t("exits.item.waived")} />;
  if (status === "requested") return <StatusChip tone="sky" emoji="envelope" label={t("xc.status.requested")} />;
  if (status === "waiting_confirmation") return <StatusChip tone="brand" emoji="eyes" label={t("xc.status.waiting_confirmation")} />;
  if (status === "blocked") return <StatusChip tone="coral" emoji="lock" label={t("xc.status.blocked")} />;
  return <StatusChip tone="sun" emoji="hourglass" label={t("exits.item.pending")} />;
}

export function typeLabel(t: TFunction, type: string): string {
  const key = `exits.type.${type}`;
  const v = t(key);
  return v === key ? type.replace(/_/g, " ") : v;
}

// ---- T2: response-time countdown chip ----

export interface ClockState {
  kind: "late" | "soon" | "left" | "paused" | "done" | "none";
  label: string;
  minutes: number;
}

export function ticketClock(t: TFunction, ticket: Ticket, meta: TicketMeta | undefined, now: number): ClockState {
  if (["resolved", "closed", "cancelled"].includes(ticket.status)) return { kind: "done", label: t("helpdesk.clock.done"), minutes: 0 };
  if (ticket.status === "waiting_on_requester" || ticket.sla?.paused) return { kind: "paused", label: t("helpdesk.clock.paused"), minutes: 0 };
  const responseDue = meta?.response_due_at ?? ticket.sla?.response_due_at ?? null;
  const resolutionDue = meta?.resolution_due_at ?? ticket.sla?.resolution_due_at ?? null;
  const replying = !meta?.first_responded_at && responseDue;
  const due = replying ? responseDue : resolutionDue;
  if (!due) return { kind: "none", label: t("helpdesk.clock.none"), minutes: 0 };
  const minutes = (new Date(due).getTime() - now) / 60000;
  const time = formatSpan(t, minutes);
  if (minutes < 0) return { kind: "late", label: t(replying ? "helpdesk.clock.reply_late" : "helpdesk.clock.fix_late", { time }), minutes };
  return { kind: minutes <= 60 ? "soon" : "left", label: t(replying ? "helpdesk.clock.reply_left" : "helpdesk.clock.fix_left", { time }), minutes };
}

const CLOCK_STYLE: Record<ClockState["kind"], { tone: Tone; emoji: string }> = {
  late: { tone: "coral", emoji: "fire" },
  soon: { tone: "sun", emoji: "alarm_clock" },
  left: { tone: "sky", emoji: "hourglass" },
  paused: { tone: "muted", emoji: "pause" },
  done: { tone: "ok", emoji: "check" },
  none: { tone: "muted", emoji: "label" },
};

export function TicketClockChip({ ticket, meta, now, withTip }: { ticket: Ticket; meta?: TicketMeta; now: number; withTip?: boolean }) {
  const t = useT();
  const c = ticketClock(t, ticket, meta, now);
  const s = CLOCK_STYLE[c.kind];
  return (
    <Box component="span" sx={{ display: "inline-flex", alignItems: "center" }}>
      <StatusChip tone={s.tone} emoji={s.emoji} label={c.label} />
      {withTip && <InfoTip text={t("helpdesk.clock.tip")} />}
    </Box>
  );
}

/** T3: shown only when the ticket was escalated. */
export function EscalationChip({ level }: { level: number }) {
  const t = useT();
  if (!level) return null;
  return (
    <Box component="span" sx={{ display: "inline-flex", alignItems: "center" }}>
      <StatusChip tone="coral" emoji="warning" label={t("helpdesk.escalated", { level })} />
      <InfoTip text={t("helpdesk.escalated_tip")} />
    </Box>
  );
}
