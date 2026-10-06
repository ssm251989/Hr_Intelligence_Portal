// Part 20.2b: Settings > Integrations > Test email provider. Dummy company mailboxes (no real mailbox anywhere):
// switch on/off, every test mailbox with its inbox (emails the app sent to it), and "Move test mailboxes to
// real provider" -- dry run first, never automatic. Backend: app/employees/test_provider.py + test_inbox.py.
import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { employeesApi, type MoveToRealResult, type TestMailboxRow, type TestMessage, type TestProviderStatus } from "../../api/employeesApi";
import { useT } from "../../i18n";
import { StatusChip } from "../../ui-kit";
import { useDateFmt } from "../servicedesk/shared";

function Inbox({ box, onClose }: { box: TestMailboxRow; onClose: () => void }) {
  const t = useT();
  const fmt = useDateFmt();
  const [msgs, setMsgs] = useState<TestMessage[] | null>(null);
  const [open, setOpen] = useState<TestMessage | null>(null);
  useEffect(() => { employeesApi.testMailboxMessages(box.id).then(setMsgs).catch(() => setMsgs([])); }, [box.id]);
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="md" aria-labelledby="tp-inbox-title">
      <DialogTitle id="tp-inbox-title">{t("tp.inbox.title", { address: box.address })}</DialogTitle>
      <DialogContent dividers sx={{ minHeight: 320 }}>
        {msgs === null ? <Skeleton variant="rounded" height={200} /> : msgs.length === 0 ? <Typography color="text.secondary">{t("tp.inbox.empty")}</Typography> : (
          <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
            <List dense sx={{ width: { md: 300 }, flexShrink: 0, maxHeight: 460, overflow: "auto" }} data-testid="tp-inbox-list">
              {msgs.map((m) => (
                <ListItemButton key={m.id} selected={open?.id === m.id} onClick={() => setOpen(m)}>
                  <ListItemText primary={m.subject} secondary={`${fmt.dateTime(m.received_at)} · ${m.from ?? ""}`} primaryTypographyProps={{ fontWeight: 700, fontSize: 14 }} />
                </ListItemButton>
              ))}
            </List>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              {open ? (
                <Stack spacing={1}>
                  <Typography sx={{ fontWeight: 800 }}>{open.subject}</Typography>
                  <Typography sx={{ fontSize: 12, color: "text.secondary" }}>{t("tp.inbox.from_to", { from: open.from ?? "-", to: open.to })}</Typography>
                  {open.html
                    ? <Box component="iframe" title={open.subject} sandbox="" srcDoc={open.html} sx={{ width: "100%", height: 420, border: "1px solid", borderColor: "divider", borderRadius: 1, bgcolor: "#fff" }} />
                    : <Typography sx={{ whiteSpace: "pre-wrap", fontSize: 14 }}>{open.text}</Typography>}
                </Stack>
              ) : <Typography color="text.secondary">{t("tp.inbox.pick")}</Typography>}
            </Box>
          </Stack>
        )}
      </DialogContent>
      <DialogActions><Button variant="contained" onClick={onClose}>{t("action.close")}</Button></DialogActions>
    </Dialog>
  );
}

export default function TestEmailProviderPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const [s, setS] = useState<TestProviderStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [box, setBox] = useState<TestMailboxRow | null>(null);
  const [move, setMove] = useState<MoveToRealResult | null>(null);

  const load = useCallback(() => { employeesApi.testProvider().then(setS).catch((e) => setError(extractErrorMessage(e, ""))); }, []);
  useEffect(load, [load]);
  const run = async <T,>(fn: () => Promise<T>, after?: (r: T) => void) => {
    setBusy(true);
    setError(null);
    try {
      const r = await fn();
      after?.(r);
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(false);
    }
  };

  if (!s) return error ? <Alert severity="error">{error}</Alert> : <Skeleton variant="rounded" height={300} />;
  const on = s.active;
  return (
    <Stack spacing={2} data-testid="test-provider-page" sx={{ minWidth: 0, maxWidth: "100%" }}>
      <Typography color="text.secondary" sx={{ maxWidth: "80ch" }}>{t("tp.intro")}</Typography>
      {s.production && on && <Alert severity="error">{t("tp.production")}</Alert>}
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      <Card variant="outlined" sx={{ p: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
          <FormControlLabel control={<Switch checked={on} disabled={busy} onChange={(e) => run(() => employeesApi.testProviderSwitch(e.target.checked), setS)} />}
            label={<Typography sx={{ fontWeight: 800 }}>{t(on ? "tp.on" : "tp.off")}</Typography>} />
          <Box sx={{ flex: 1 }} />
          <Typography sx={{ fontSize: 13, color: f.muted }}>{t("tp.domain", { domain: s.domain })}</Typography>
        </Stack>
        <Typography sx={{ fontSize: 13, color: f.muted, mt: 1 }}>{t(on ? "tp.on_hint" : "tp.off_hint")}</Typography>
        {s.dev_capture && <Typography sx={{ fontSize: 13, color: f.muted, mt: 0.5 }}>{t("tp.dev_capture")}</Typography>}
      </Card>

      <Box>
        <Typography component="h3" sx={{ fontWeight: 800, mb: 1 }}>{t("tp.mailboxes", { n: s.mailboxes.length })}</Typography>
        {s.mailboxes.length === 0 ? <Typography color="text.secondary">{t("tp.none")}</Typography> : (
          <TableContainer sx={{ overflowX: "auto", maxWidth: "100%" }}>
            <Table size="small" aria-label={t("tp.mailboxes", { n: s.mailboxes.length })}>
              <TableHead>
                <TableRow>
                  <TableCell>{t("tp.col.address")}</TableCell>
                  <TableCell>{t("tp.col.person")}</TableCell>
                  <TableCell>{t("tp.col.status")}</TableCell>
                  <TableCell align="right">{t("tp.col.inbox")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {s.mailboxes.map((m) => (
                  <TableRow key={m.id} hover>
                    <TableCell>
                      <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Typography sx={{ fontSize: 14, fontWeight: 700, wordBreak: "break-all" }}>{m.address}</Typography>
                        <StatusChip tone="muted" emoji="label" label="TEST" />
                      </Stack>
                    </TableCell>
                    <TableCell>{m.display_name ?? "-"}<Typography sx={{ fontSize: 12, color: f.muted }}>{[m.employee_code, t("tp.created_on", { date: fmt.date(m.created_at) })].filter(Boolean).join(" · ")}</Typography></TableCell>
                    <TableCell><StatusChip tone={m.status === "active" ? "ok" : "sun"} emoji={m.status === "active" ? "check" : "pause"} label={t(`tp.status.${m.status}`) === `tp.status.${m.status}` ? m.status : t(`tp.status.${m.status}`)} /></TableCell>
                    <TableCell align="right" sx={{ whiteSpace: "nowrap" }}><Button size="small" onClick={() => setBox(m)}>{t("tp.open_inbox", { n: m.messages })}</Button></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
        {s.mailboxes.length > 0 && <Typography sx={{ fontSize: 13, color: f.muted, mt: 1 }}>{t("tp.quota_note", { quota: s.mailboxes[0].quota ?? "-" })} {t("tp.password_note")}</Typography>}
      </Box>

      <Card variant="outlined" sx={{ p: 2 }}>
        <Typography component="h3" sx={{ fontWeight: 800 }}>{t("tp.move.title")}</Typography>
        <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("tp.move.hint")}</Typography>
        <Button variant="outlined" disabled={busy} onClick={() => run(() => employeesApi.moveToReal(false), setMove)}>{t("tp.move.dry")}</Button>
        {move?.dry_run && (
          <Stack spacing={1} sx={{ mt: 1.5 }}>
            <Typography sx={{ fontSize: 14 }}>{move.real_provider ? t("tp.move.would", { n: move.would_move?.length ?? 0, provider: move.real_provider }) : t("tp.move.would_none", { n: move.would_move?.length ?? 0 })}</Typography>
            {(move.would_move ?? []).slice(0, 50).map((w) => <Typography key={w.employee_id} sx={{ fontSize: 13 }}>• {w.code} {w.name} - {w.address}</Typography>)}
            {move.blocked ? <Alert severity="warning">{move.blocked}</Alert> : (
              <Box><Button variant="contained" color="warning" disabled={busy || !(move.would_move?.length)} onClick={() => run(() => employeesApi.moveToReal(true), (r) => { setMove(r); load(); })}>{t("tp.move.apply")}</Button></Box>
            )}
          </Stack>
        )}
        {move && !move.dry_run && (
          <Stack spacing={0.5} sx={{ mt: 1.5 }}>
            <Alert severity="info">{t("tp.move.once")}</Alert>
            {(move.results ?? []).map((r) => (
              <Typography key={r.code} sx={{ fontSize: 13, color: r.ok ? undefined : "error.main" }}>
                {r.ok ? "✓" : "✗"} {r.code} {r.address}{r.one_time_password ? ` - ${t("tp.move.password", { pw: r.one_time_password })}` : ""}{r.error ? ` - ${r.error}` : ""}
              </Typography>
            ))}
          </Stack>
        )}
      </Card>
      {box && <Inbox box={box} onClose={() => { setBox(null); load(); }} />}
    </Stack>
  );
}
