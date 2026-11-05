// Part 15.6 -- one ticket: conversation + reply for everyone; next step / assign / team for agents.
import { useCallback, useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

import { serviceDeskExtra, type AgentsInfo, type Ticket, type TicketComment, type TicketMeta } from "../../api/serviceDeskExtra";
import { useT } from "../../i18n";
import { Emoji, FriendlyError, StatusChip } from "../../ui-kit";
import RateTicket from "./RateTicket";
import { EscalationChip, PriorityChip, TicketClockChip, TicketStatusChip, useDateFmt, useNow } from "./shared";

const NEXT: Record<string, string[]> = {
  open: ["in_progress", "waiting_on_requester", "resolved", "cancelled"],
  in_progress: ["waiting_on_requester", "resolved", "cancelled"],
  waiting_on_requester: ["in_progress", "resolved", "cancelled"],
  resolved: ["closed", "in_progress"],
};

export default function TicketDetailDialog({
  ticketId, open, onClose, onChanged, agent, canEdit, categoryLabel, agents,
}: {
  ticketId: string | null;
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
  agent?: boolean;
  canEdit?: boolean;
  categoryLabel: (code?: string | null) => string;
  agents?: AgentsInfo | null;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fullScreen = useMediaQuery(useTheme().breakpoints.down("sm"));
  const fmt = useDateFmt();
  const now = useNow();
  const [ticket, setTicket] = useState<(Ticket & { comments: TicketComment[] }) | null>(null);
  const [meta, setMeta] = useState<TicketMeta | undefined>();
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [reply, setReply] = useState("");
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!ticketId) return;
    setError(null);
    serviceDeskExtra.ticket(ticketId).then(setTicket).catch(setError);
    serviceDeskExtra.ticketsMeta([ticketId]).then((m) => setMeta(m[ticketId])).catch(() => undefined);
  }, [ticketId]);

  useEffect(() => {
    if (open) {
      setTicket(null);
      setReply("");
      setInternal(false);
      setActionError(null);
      load();
    }
  }, [open, load]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      load();
      onChanged();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(false);
    }
  };

  const send = () => run(async () => {
    await serviceDeskExtra.comment(ticketId!, reply.trim(), agent && internal);
    setReply("");
  });

  const me = agents?.agents.find((a) => a.me);

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md" fullScreen={fullScreen} aria-labelledby="sd-ticket-title">
      <DialogTitle id="sd-ticket-title">
        {ticket ? t("helpdesk.detail.title", { number: ticket.number }) : t("helpdesk.common.loading")}
      </DialogTitle>
      <DialogContent dividers>
        {error ? <FriendlyError error={error} onRetry={load} compact /> : !ticket ? (
          <Box sx={{ display: "grid", placeItems: "center", py: 6 }}><CircularProgress aria-label={t("helpdesk.common.loading")} /></Box>
        ) : (
          <Stack spacing={2}>
            <Box>
              <Typography sx={{ fontWeight: 800, fontSize: 18 }}>{ticket.subject}</Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                <TicketStatusChip status={ticket.status} forEmployee={!agent} />
                <PriorityChip priority={ticket.priority} />
                <TicketClockChip ticket={ticket} meta={meta} now={now} withTip />
                <EscalationChip level={ticket.escalation_level} />
                {ticket.confidential && <StatusChip tone="muted" emoji="lock" label={t("helpdesk.detail.confidential")} />}
              </Stack>
            </Box>

            <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" }, gap: 1.5, bgcolor: f.surface2, borderRadius: "12px", p: 1.5 }}>
              {[
                [t("helpdesk.detail.topic"), categoryLabel(ticket.category_code)],
                [t("helpdesk.detail.created"), fmt.dateTime(ticket.created_at)],
                [t("helpdesk.detail.requester"), meta?.requester_name ?? "—"],
                [t("helpdesk.detail.assignee"), meta?.assignee_name ?? t("helpdesk.detail.unassigned")],
              ].map(([k, v]) => (
                <Box key={k}>
                  <Typography sx={{ fontSize: 12, color: f.muted }}>{k}</Typography>
                  <Typography sx={{ fontSize: 14, fontWeight: 600 }}>{v}</Typography>
                </Box>
              ))}
            </Box>

            {ticket.description && <Typography sx={{ whiteSpace: "pre-wrap", maxWidth: "75ch" }}>{ticket.description}</Typography>}

            {agent && canEdit && (
              <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "flex-start" }}>
                {NEXT[ticket.status] && (
                  <TextField select size="small" label={t("helpdesk.detail.status")} value="" sx={{ minWidth: 240 }}
                    onChange={(e) => run(() => serviceDeskExtra.setStatus(ticket.id, e.target.value))} disabled={busy}>
                    {NEXT[ticket.status].map((s) => (
                      <MenuItem key={s} value={s}>{t(ticket.status === "resolved" && s === "in_progress" ? "helpdesk.set.reopen" : `helpdesk.set.${s}`)}</MenuItem>
                    ))}
                  </TextField>
                )}
                <TextField select size="small" label={t("helpdesk.detail.assign")} helperText={t("helpdesk.detail.assign_hint")} sx={{ minWidth: 240 }}
                  value={ticket.assignee_user_id ?? ""} disabled={busy}
                  onChange={(e) => run(() => serviceDeskExtra.assign(ticket.id, e.target.value || null, ticket.queue_code))}>
                  <MenuItem value="">{t("helpdesk.detail.nobody")}</MenuItem>
                  {(agents?.agents ?? []).map((a) => <MenuItem key={a.id} value={a.id}>{a.me ? `${a.name} (${t("helpdesk.detail.you")})` : a.name}</MenuItem>)}
                </TextField>
                {(agents?.teams.length ?? 0) > 0 && (
                  <TextField select size="small" label={t("helpdesk.detail.move_team")} sx={{ minWidth: 200 }} value={ticket.queue_code ?? ""} disabled={busy}
                    onChange={(e) => run(() => serviceDeskExtra.assign(ticket.id, ticket.assignee_user_id, e.target.value))}>
                    {agents!.teams.map((q) => <MenuItem key={q.code} value={q.code}>{q.name}</MenuItem>)}
                  </TextField>
                )}
                {me && ticket.assignee_user_id !== me.id && (
                  <Button variant="outlined" disabled={busy} onClick={() => run(() => serviceDeskExtra.assign(ticket.id, me.id, ticket.queue_code))}>
                    {t("helpdesk.detail.assign_me")}
                  </Button>
                )}
              </Stack>
            )}

            {!agent && ["resolved", "closed"].includes(ticket.status) && (
              <RateTicket ticketId={ticket.id} score={ticket.csat_score} onRated={() => { load(); onChanged(); }} />
            )}

            {actionError ? <FriendlyError error={actionError} compact /> : null}

            <Box>
              <Typography component="h3" sx={{ fontWeight: 800, mb: 1 }}>{t("helpdesk.detail.conversation")}</Typography>
              {ticket.comments.length === 0 ? (
                <Typography sx={{ color: f.muted }}>{t("helpdesk.detail.no_comments")}</Typography>
              ) : (
                <Stack spacing={1} component="ol" sx={{ listStyle: "none", p: 0, m: 0 }}>
                  {ticket.comments.map((c, i) => (
                    <Box component="li" key={i} sx={{
                      p: 1.5, borderRadius: "12px", maxWidth: "80ch",
                      bgcolor: c.internal ? f.sunSoft : c.is_agent ? f.brandSoft : f.surface2,
                      alignSelf: c.is_agent ? "flex-start" : "flex-end",
                    }}>
                      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }} flexWrap="wrap" useFlexGap>
                        <Emoji name={c.is_agent ? "ring_buoy" : "speech"} size={14} />
                        <Typography sx={{ fontSize: 13, fontWeight: 700 }}>{c.is_agent && !agent ? t("helpdesk.detail.team_member") : c.author}</Typography>
                        <Typography sx={{ fontSize: 12, color: f.muted }}>{fmt.dateTime(c.at)}</Typography>
                        {c.internal && <StatusChip tone="sun" emoji="lock" label={t("helpdesk.detail.internal_badge")} />}
                      </Stack>
                      <Typography sx={{ whiteSpace: "pre-wrap", fontSize: 14 }}>{c.body}</Typography>
                    </Box>
                  ))}
                </Stack>
              )}
            </Box>

            {!["closed", "cancelled"].includes(ticket.status) && (
              <Box>
                <TextField label={t("helpdesk.detail.reply")} placeholder={t("helpdesk.detail.reply_ph")} value={reply} onChange={(e) => setReply(e.target.value)}
                  multiline minRows={2} fullWidth />
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                  {agent && (
                    <FormControlLabel control={<Checkbox checked={internal} onChange={(e) => setInternal(e.target.checked)} />} label={t("helpdesk.detail.internal")} />
                  )}
                  <Box sx={{ flex: 1 }} />
                  <Button variant="contained" onClick={send} disabled={busy || !reply.trim()}>{t("helpdesk.detail.send")}</Button>
                </Stack>
              </Box>
            )}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.close")}</Button>
      </DialogActions>
    </Dialog>
  );
}
