import { useCallback, useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, superAdminApi } from "../../api/client";
import type { ActivationEventRow, ApproverRow, ConsoleActivationRequest, ConsoleActivationState, MailboxIn } from "../../api/modulesApi";
import { useT } from "../../i18n";
import { StatusChip } from "../../ui-kit";

// Part 19.2 / 19.2b / 19.2c (CTD Techs console): activation requests from every installation,
// the approver priority list, the platform mailbox and the platform settings. Requests whose
// email didn't get through (or that nobody actioned) are on top in red.
type Msg = { tone: "success" | "error" | "info"; text: string } | null;

export default function ActivationConsole({ token }: { token: string }) {
  const t = useT();
  const [state, setState] = useState<ConsoleActivationState | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState(false);
  const mailboxRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(() => {
    superAdminApi.activationRequests(token).then(setState).catch((err) => setMsg({ tone: "error", text: extractErrorMessage(err, t("act.err")) }));
  }, [token, t]);
  useEffect(load, [load]);
  useEffect(() => {
    const id = window.setInterval(load, 30000);
    return () => window.clearInterval(id);
  }, [load]);

  const run = async (fn: () => Promise<Msg>) => {
    setBusy(true);
    setMsg(null);
    try {
      setMsg(await fn());
      load();
    } catch (err) {
      setMsg({ tone: "error", text: extractErrorMessage(err, t("act.err")) });
    } finally {
      setBusy(false);
    }
  };

  if (!state) return msg ? <Alert severity="error" sx={{ mt: 3 }}>{msg.text}</Alert> : null;

  return (
    <Stack spacing={3} sx={{ mt: 3 }}>
      {!state.mailbox.ok && (
        <Alert severity="error" action={<Button color="inherit" size="small" onClick={() => mailboxRef.current?.scrollIntoView({ behavior: "smooth" })}>{t("act.fix_mailbox")}</Button>}>
          {t("act.mail_down", { reason: state.mailbox.reason ?? "" })}
        </Alert>
      )}
      {msg && <Alert severity={msg.tone} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      <RequestsCard token={token} rows={state.requests} approvers={state.approvers} busy={busy} run={run} />
      <ApproversCard token={token} rows={state.approvers} busy={busy} run={run} />
      <div ref={mailboxRef}><MailboxCard token={token} health={state.mailbox} busy={busy} run={run} /></div>
      <SettingsCard token={token} values={state.settings} busy={busy} run={run} />
    </Stack>
  );
}

type Run = (fn: () => Promise<Msg>) => Promise<void>;

function RequestsCard({ token, rows, approvers, busy, run }: { token: string; rows: ConsoleActivationRequest[]; approvers: ApproverRow[]; busy: boolean; run: Run }) {
  const t = useT();
  const [menu, setMenu] = useState<{ el: HTMLElement; row: ConsoleActivationRequest } | null>(null);
  const [historyOf, setHistoryOf] = useState<ConsoleActivationRequest | null>(null);
  const [events, setEvents] = useState<ActivationEventRow[] | null>(null);
  const [shown, setShown] = useState<{ number: string; code: string } | null>(null);

  const openHistory = (row: ConsoleActivationRequest) => {
    setHistoryOf(row);
    setEvents(null);
    superAdminApi.activationHistory(token, row.id).then(setEvents).catch(() => setEvents([]));
  };

  const status = (r: ConsoleActivationRequest) => {
    if (r.status !== "pending") return r.status === "activated" ? <StatusChip status="done" label={t("act.status.activated")} /> : <StatusChip tone="muted" label={t(`act.status.${r.status}`)} />;
    if (r.delivery_raw === "failed") return <StatusChip tone="coral" emoji="fire" label={t("act.delivery.failed")} />;
    if (r.delivery_raw === "not_actioned") return <StatusChip tone="coral" emoji="warning" label={t("act.delivery.not_actioned")} />;
    if (r.delivery_raw === "retrying" || r.delivery_raw === "sending") return <StatusChip tone="sun" emoji="hourglass" label={t("act.delivery.retrying", { count: r.retry_count })} />;
    return <StatusChip tone="sun" emoji="hourglass" label={t("act.delivery.sent_to", { priority: r.current_priority ?? 1 })} />;
  };

  const act = (fn: () => Promise<Msg>) => { setMenu(null); void run(fn); };

  return (
    <Card sx={{ p: 0 }}>
      <Box sx={{ p: 2.5, pb: 1 }}>
        <Typography variant="h6">{t("act.title")}</Typography>
        <Typography variant="body2" color="text.secondary">{t("act.intro2")}</Typography>
      </Box>
      {rows.length === 0 ? <Typography sx={{ p: 2.5 }} color="text.secondary">{t("act.empty")}</Typography> : (
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("act.col.number")}</TableCell>
                <TableCell>{t("act.col.company")}</TableCell>
                <TableCell>{t("act.col.modules")}</TableCell>
                <TableCell>{t("act.col.by")}</TableCell>
                <TableCell>{t("act.col.status")}</TableCell>
                <TableCell align="right">{t("console.col.actions")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id} hover sx={r.attention && (r.delivery_raw === "failed" || r.delivery_raw === "not_actioned") ? { bgcolor: "error.light", "& td": { color: "error.contrastText" } } : undefined}>
                  <TableCell sx={{ fontWeight: 700, whiteSpace: "nowrap" }}>{r.number}</TableCell>
                  <TableCell>
                    <Typography sx={{ fontWeight: 700 }}>{r.company ?? r.tenant}</Typography>
                    <Typography variant="caption">{r.installation}</Typography>
                  </TableCell>
                  <TableCell>{r.module_names}</TableCell>
                  <TableCell>
                    <Typography variant="body2">{r.requested_by_name || r.requested_by}</Typography>
                    <Typography variant="caption">{r.requested_at ? new Date(r.requested_at).toLocaleString() : ""}</Typography>
                  </TableCell>
                  <TableCell>
                    {status(r)}
                    {r.status === "pending" && r.email_error && <Typography variant="caption" sx={{ display: "block", maxWidth: 260 }}>{r.email_error}</Typography>}
                  </TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={1} justifyContent="flex-end">
                      <Button size="small" onClick={() => openHistory(r)}>{t("act.history")}</Button>
                      {(r.status === "pending" || r.status === "expired") && (
                        <Button size="small" variant="outlined" disabled={busy} onClick={(e) => setMenu({ el: e.currentTarget, row: r })}>{t("act.actions")}</Button>
                      )}
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Menu anchorEl={menu?.el} open={Boolean(menu)} onClose={() => setMenu(null)}>
        {menu && menu.row.status === "pending" && approvers.filter((a) => a.active).map((a) => (
          <MenuItem key={a.priority} onClick={() => act(async () => {
            const r = await superAdminApi.activationResend(token, menu.row.id, { priority: a.priority });
            return r.sent ? { tone: "success", text: t("act.resent_to", { who: a.email }) } : { tone: "error", text: t("act.email_failed", { reason: r.email_error ?? "" }) };
          })}>{t("act.resend_to", { priority: a.priority, who: a.email })}</MenuItem>
        ))}
        {menu && menu.row.status === "pending" && (
          <MenuItem onClick={() => act(async () => {
            const r = await superAdminApi.activationResend(token, menu.row.id, { all: true });
            return r.sent ? { tone: "success", text: t("act.resent_all") } : { tone: "error", text: t("act.email_failed", { reason: r.email_error ?? "" }) };
          })}>{t("act.resend_all")}</MenuItem>
        )}
        {menu && (
          <MenuItem onClick={() => act(async () => {
            const r = await superAdminApi.activationNewCode(token, menu.row.id);
            return r.sent ? { tone: "success", text: t("act.new_code_sent") } : { tone: "error", text: t("act.email_failed", { reason: r.email_error ?? "" }) };
          })}>{t("act.new_code")}</MenuItem>
        )}
        {menu && menu.row.status === "pending" && (
          <MenuItem onClick={() => act(async () => {
            const r = await superAdminApi.activationShowCode(token, menu.row.id);
            setShown({ number: r.number, code: r.code });
            return null;
          })}>{t("act.show_code")}</MenuItem>
        )}
        {menu && menu.row.status === "pending" && (
          <MenuItem sx={{ color: "warning.main" }} onClick={() => act(async () => {
            await superAdminApi.activationCancel(token, menu.row.id);
            return { tone: "success", text: t("act.cancelled") };
          })}>{t("act.cancel")}</MenuItem>
        )}
      </Menu>

      <Dialog open={Boolean(historyOf)} onClose={() => setHistoryOf(null)} maxWidth="md" fullWidth>
        <DialogTitle>{t("act.history_title", { number: historyOf?.number ?? "" })}</DialogTitle>
        <DialogContent>
          {events === null ? <Typography>…</Typography> : events.length === 0 ? <Typography color="text.secondary">{t("act.history_empty")}</Typography> : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t("act.h.time")}</TableCell><TableCell>{t("act.h.what")}</TableCell><TableCell>{t("act.h.to")}</TableCell>
                  <TableCell>{t("act.h.by")}</TableCell><TableCell>{t("act.h.status")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {events.map((e, i) => (
                  <TableRow key={i}>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{e.at ? new Date(e.at).toLocaleString() : ""}</TableCell>
                    <TableCell>{t(`act.kind.${e.kind}`)}</TableCell>
                    <TableCell>{e.sent_to.join(", ") || "—"}</TableCell>
                    <TableCell>{e.by}</TableCell>
                    <TableCell>
                      {e.status === "failed" ? <StatusChip tone="coral" label={t("act.h.failed")} /> : e.status === "sent" ? <StatusChip status="done" label={t("act.h.sent")} /> : <StatusChip tone="muted" label={t("act.h.done")} />}
                      {e.reason && <Typography variant="caption" sx={{ display: "block" }}>{e.reason}</Typography>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </DialogContent>
        <DialogActions><Button onClick={() => setHistoryOf(null)}>{t("act.close")}</Button></DialogActions>
      </Dialog>

      <Dialog open={Boolean(shown)} onClose={() => setShown(null)} maxWidth="xs" fullWidth>
        <DialogTitle>{t("act.code_for", { number: shown?.number ?? "" })}</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: 32, fontWeight: 800, letterSpacing: 4, textAlign: "center", my: 2 }}>{shown?.code}</Typography>
          <Typography variant="body2" color="text.secondary">{t("act.code_shown_note")}</Typography>
        </DialogContent>
        <DialogActions><Button onClick={() => setShown(null)}>{t("act.close")}</Button></DialogActions>
      </Dialog>
    </Card>
  );
}

function ApproversCard({ token, rows, busy, run }: { token: string; rows: ApproverRow[]; busy: boolean; run: Run }) {
  const t = useT();
  const nextPriority = rows.length ? Math.max(...rows.map((r) => r.priority)) + 1 : 1;
  const [form, setForm] = useState<{ priority: number; name: string; email: string; active: boolean } | null>(null);

  const move = (i: number, dir: -1 | 1) => {
    const order = rows.map((r) => r.email);
    [order[i], order[i + dir]] = [order[i + dir], order[i]];
    void run(async () => { await superAdminApi.approverReorder(token, order); return { tone: "success", text: t("act.ap.reordered") }; });
  };

  return (
    <Card sx={{ p: 2.5 }}>
      <Typography variant="h6">{t("act.ap.title")}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t("act.ap.intro")}</Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>{t("act.ap.priority")}</TableCell><TableCell>{t("act.ap.name")}</TableCell><TableCell>{t("act.ap.email")}</TableCell>
            <TableCell>{t("act.ap.active")}</TableCell><TableCell align="right">{t("console.col.actions")}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r, i) => (
            <TableRow key={r.email}>
              <TableCell sx={{ fontWeight: 700 }}>P{r.priority}</TableCell>
              <TableCell>{r.name || "—"}</TableCell>
              <TableCell>{r.email}</TableCell>
              <TableCell>{r.active ? t("act.ap.yes") : t("act.ap.no")}</TableCell>
              <TableCell align="right">
                <IconButton size="small" aria-label={t("act.ap.up")} disabled={busy || i === 0} onClick={() => move(i, -1)}>↑</IconButton>
                <IconButton size="small" aria-label={t("act.ap.down")} disabled={busy || i === rows.length - 1} onClick={() => move(i, 1)}>↓</IconButton>
                <Button size="small" onClick={() => setForm({ priority: r.priority, name: r.name ?? "", email: r.email, active: r.active })}>{t("act.ap.edit")}</Button>
                <Button size="small" color="warning" disabled={busy}
                  onClick={() => void run(async () => { await superAdminApi.approverRemove(token, r.priority); return { tone: "success", text: t("act.ap.removed") }; })}>{t("act.ap.remove")}</Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {[2, 3].filter((p) => !rows.some((r) => r.priority === p)).map((p) => (
        <Typography key={p} variant="body2" color="text.secondary" sx={{ mt: 1 }}>{t("act.ap.empty_priority", { priority: p })}</Typography>
      ))}
      <Button sx={{ mt: 1.5 }} variant="outlined" onClick={() => setForm({ priority: nextPriority, name: "", email: "", active: true })}>{t("act.ap.add")}</Button>

      <Dialog open={Boolean(form)} onClose={() => setForm(null)} maxWidth="xs" fullWidth>
        <DialogTitle>{t("act.ap.form_title", { priority: form?.priority ?? "" })}</DialogTitle>
        {form && (
          <DialogContent>
            <Stack spacing={2} sx={{ mt: 1 }}>
              <TextField label={t("act.ap.priority")} type="number" value={form.priority} onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })} inputProps={{ min: 1, max: 20 }} />
              <TextField label={t("act.ap.name")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              <TextField label={t("act.ap.email")} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="name@ctdtechs.com" helperText={t("act.ap.email_hint")} />
              <FormControlLabel control={<Switch checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />} label={t("act.ap.active")} />
            </Stack>
          </DialogContent>
        )}
        <DialogActions>
          <Button onClick={() => setForm(null)}>{t("act.cancel_btn")}</Button>
          <Button variant="contained" disabled={busy || !form?.email} onClick={() => {
            const f = form!;
            setForm(null);
            void run(async () => { await superAdminApi.approverSet(token, f.priority, { email: f.email, name: f.name, active: f.active }); return { tone: "success", text: t("act.ap.saved") }; });
          }}>{t("act.save")}</Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}

function MailboxCard({ token, health, busy, run }: { token: string; health: ConsoleActivationState["mailbox"]; busy: boolean; run: Run }) {
  const t = useT();
  const m = health.mailbox;
  const [form, setForm] = useState<MailboxIn>({ host: m.host || "", port: m.port ?? 587, user: m.user ?? "", starttls: m.starttls ?? true,
    from_name: m.from_name ?? "CTD Techs HRMS", from_address: m.from_address ?? "", password: null });
  const [to, setTo] = useState("kg@ctdtechs.com");

  return (
    <Card sx={{ p: 2.5 }}>
      <Typography variant="h6">{t("act.mb.title")}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        {t("act.mb.intro")} {m.source === "env" ? t("act.mb.from_env") : ""}
      </Typography>
      {health.last && <Alert severity={health.last.ok ? "success" : "error"} sx={{ mb: 1.5 }}>
        {health.last.ok ? t("act.mb.last_ok", { at: new Date(health.last.at).toLocaleString() }) : t("act.mb.last_failed", { at: new Date(health.last.at).toLocaleString(), reason: health.last.reason ?? "" })}
      </Alert>}
      {m.source === "hr_admin" && (
        <Alert severity="info" sx={{ mb: 1.5 }}>{t("act.mb.hr_admin", { connection: m.connection ?? "", from: m.from_address ?? "" })}</Alert>
      )}
      {m.source !== "hr_admin" && <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", md: "2fr 1fr 2fr" } }}>
        <TextField label={t("act.mb.host")} value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} placeholder="smtp.office365.com" />
        <TextField label={t("act.mb.port")} type="number" value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })} />
        <TextField label={t("act.mb.user")} value={form.user} onChange={(e) => setForm({ ...form, user: e.target.value })} />
        <TextField label={t("act.mb.from_name")} value={form.from_name} onChange={(e) => setForm({ ...form, from_name: e.target.value })} />
        <TextField label={t("act.mb.from_address")} value={form.from_address} onChange={(e) => setForm({ ...form, from_address: e.target.value })} placeholder="hrms@ctdtechs.com" />
        <TextField label={t("act.mb.password")} type="password" autoComplete="new-password" value={form.password ?? ""} onChange={(e) => setForm({ ...form, password: e.target.value || null })}
          helperText={m.password_set ? t("act.mb.password_kept") : t("act.mb.password_none")} />
      </Box>}
      {m.source !== "hr_admin" && <FormControlLabel sx={{ mt: 1 }} control={<Switch checked={form.starttls} onChange={(e) => setForm({ ...form, starttls: e.target.checked })} />} label={t("act.mb.starttls")} />}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ mt: 1.5 }} alignItems={{ sm: "center" }}>
        {m.source !== "hr_admin" && <Button variant="contained" disabled={busy || !form.host || !form.from_address}
          onClick={() => void run(async () => { await superAdminApi.mailboxSet(token, form); setForm({ ...form, password: null }); return { tone: "success", text: t("act.mb.saved") }; })}>{t("act.save")}</Button>}
        <TextField size="small" label={t("act.mb.test_to")} value={to} onChange={(e) => setTo(e.target.value)} />
        <Button variant="outlined" disabled={busy || !to}
          onClick={() => void run(async () => {
            const r = await superAdminApi.mailboxTest(token, to);
            return r.ok ? { tone: "success", text: t("act.mb.test_ok", { to }) } : { tone: "error", text: t("act.mb.test_failed", { reason: r.reason ?? "" }) };
          })}>{t("act.mb.test")}</Button>
      </Stack>
    </Card>
  );
}

function SettingsCard({ token, values, busy, run }: { token: string; values: Record<string, string | number | boolean>; busy: boolean; run: Run }) {
  const t = useT();
  const [v, setV] = useState(values);
  const num = (key: string) => (
    <TextField key={key} type="number" label={t(`act.set.${key}`)} value={Number(v[key] ?? 0)} onChange={(e) => setV({ ...v, [key]: Number(e.target.value) })} />
  );
  const text = (key: string) => (
    <TextField key={key} label={t(`act.set.${key}`)} value={String(v[key] ?? "")} onChange={(e) => setV({ ...v, [key]: e.target.value })} />
  );
  return (
    <Card sx={{ p: 2.5 }}>
      <Typography variant="h6">{t("act.set.title")}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t("act.set.intro")}</Typography>
      <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", md: "repeat(3, 1fr)" } }}>
        {num("activation.escalation_minutes")}
        {num("activation.resend_cooldown_minutes")}
        {num("activation.resend_max_per_day")}
        {text("support.phone")}
        {text("support.email")}
        {text("support.hours")}
      </Box>
      <FormControlLabel sx={{ mt: 1 }} control={<Switch checked={Boolean(v["activation.send_all"])} onChange={(e) => setV({ ...v, "activation.send_all": e.target.checked })} />}
        label={t("act.set.activation.send_all")} />
      <Box sx={{ mt: 1.5 }}>
        <Button variant="contained" disabled={busy} onClick={() => void run(async () => { await superAdminApi.platformSettingsSet(token, v); return { tone: "success", text: t("act.set.saved") }; })}>{t("act.save")}</Button>
      </Box>
    </Card>
  );
}
