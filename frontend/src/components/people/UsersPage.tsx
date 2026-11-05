import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, http } from "../../api/client";
import { useT } from "../../i18n";
import ConfirmDialog from "../ConfirmDialog";

interface UserRow { id: string; email: string; full_name: string | null; role: string; roles: string[]; active: boolean; two_step: boolean; locked: boolean; is_me: boolean }
const ROLES = ["admin", "recruiter", "hiring_manager", "interviewer"];

// Part 18.22: Settings > People & access > Users -- invite, change role, switch off / on, send a
// password reset. (Extra roles per person stay in "Role assignments" below.)
export default function UsersPage() {
  const t = useT();
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [invite, setInvite] = useState({ email: "", full_name: "", role: "recruiter" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmOff, setConfirmOff] = useState<UserRow | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => { http.get<UserRow[]>("/api/v1/ui/users").then(setRows).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, t("users.err")) })); }, [t]);
  useEffect(load, [load]);

  const run = async (fn: () => Promise<unknown>, ok: string | ((r: unknown) => string)) => {
    setBusy(true); setMsg(null);
    try { const r = await fn(); setMsg({ ok: true, text: typeof ok === "string" ? ok : ok(r) }); load(); }
    catch (e) { setMsg({ ok: false, text: extractErrorMessage(e, t("users.err")) }); } finally { setBusy(false); }
  };
  const linkText = (r: unknown) => {
    const x = r as { email_sent: boolean; link: string | null };
    return x.email_sent ? t("users.link_sent") : t("users.link_share", { link: x.link ?? "" });
  };

  return (
    <Card>
      <CardContent>
        <Typography variant="h6">{t("users.title")}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{t("users.intro")}</Typography>
        {msg && <Alert severity={msg.ok ? "success" : "error"} sx={{ mb: 2 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}
        <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mb: 2 }}>
          <TextField size="small" type="email" label={t("users.email")} placeholder="name@yourcompany.com" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} sx={{ minWidth: 240 }} />
          <TextField size="small" label={t("users.name")} value={invite.full_name} onChange={(e) => setInvite({ ...invite, full_name: e.target.value })} />
          <TextField select size="small" label={t("users.role")} value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })} sx={{ minWidth: 170 }}>
            {ROLES.map((r) => <MenuItem key={r} value={r}>{t(`users.role.${r}`)}</MenuItem>)}
          </TextField>
          <Button variant="contained" disabled={busy || !/^\S+@\S+\.\S+$/.test(invite.email)}
            onClick={() => run(() => http.post("/api/v1/ui/users/invite", invite).then((r) => { setInvite({ email: "", full_name: "", role: "recruiter" }); return r; }), linkText)}>
            {t("users.invite")}
          </Button>
        </Stack>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("users.col.person")}</TableCell>
                <TableCell>{t("users.role")}</TableCell>
                <TableCell>{t("users.col.state")}</TableCell>
                <TableCell align="right" />
              </TableRow>
            </TableHead>
            <TableBody>
              {(rows ?? []).map((u) => (
                <TableRow key={u.id} sx={{ opacity: u.active ? 1 : 0.6 }}>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 700 }}>{u.full_name || u.email}{u.is_me ? ` (${t("users.you")})` : ""}</Typography>
                    <Typography variant="caption">{u.email}</Typography>
                  </TableCell>
                  <TableCell>
                    <TextField select size="small" value={u.role} disabled={busy} onChange={(e) => run(() => http.patch(`/api/v1/ui/users/${u.id}`, { role: e.target.value }), t("users.role_changed"))} sx={{ minWidth: 160 }}>
                      {ROLES.map((r) => <MenuItem key={r} value={r}>{t(`users.role.${r}`)}</MenuItem>)}
                    </TextField>
                    {u.roles.length > 0 && <Typography variant="caption" sx={{ display: "block" }}>{u.roles.join(", ")}</Typography>}
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5}>
                      <Chip size="small" color={u.active ? "success" : "default"} label={u.active ? t("users.active") : t("users.off")} />
                      {u.locked && <Chip size="small" color="warning" label={t("users.locked")} />}
                    </Stack>
                  </TableCell>
                  <TableCell align="right">
                    <Button size="small" disabled={busy} onClick={() => run(() => http.post(`/api/v1/ui/users/${u.id}/reset-password`, {}), linkText)}>{t("users.reset")}</Button>
                    {!u.is_me && (u.active
                      ? <Button size="small" color="error" disabled={busy} onClick={() => setConfirmOff(u)}>{t("users.deactivate")}</Button>
                      : <Button size="small" disabled={busy} onClick={() => run(() => http.post(`/api/v1/ui/users/${u.id}/reactivate`, {}), t("users.reactivated"))}>{t("users.reactivate")}</Button>)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        <ConfirmDialog open={confirmOff !== null} title={t("users.deactivate_title", { name: confirmOff?.full_name || confirmOff?.email || "" })}
          message={t("users.deactivate_body")} confirmLabel={t("users.deactivate")} destructive
          onConfirm={() => { const u = confirmOff; setConfirmOff(null); if (u) void run(() => http.post(`/api/v1/ui/users/${u.id}/deactivate`, {}), t("users.deactivated")); }}
          onCancel={() => setConfirmOff(null)} />
      </CardContent>
    </Card>
  );
}
