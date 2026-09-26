import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import InputAdornment from "@mui/material/InputAdornment";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { superAdminApi, type ConsoleTenantRow } from "../api/client";
import { t as tr, useT } from "../i18n";
import { EmptyState, Emoji, FriendlyError, humanise, Illustration, InfoTip, PageHeader, StatusChip } from "../ui-kit";

// Part 13 section B (docs/HRMS_COMPLETE_SPEC.txt): the Super-Admin console -- a separate
// route and a separate identity (platform admin + mandatory authenticator code), never a
// company session. The console token lives only in sessionStorage and is short-lived
// (server-side expiry). This page covers sign-in, the company list, suspend/resume and
// per-company health (Part 15.6 restyle: same behaviour, friendly look).

const TOKEN_KEY = "hrms.console.token";

function readToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

type Health = { ok: boolean; issues: number } | "checking";

function StatusOf({ status }: { status: string }) {
  const t = useT();
  if (status === "active") return <StatusChip status="active" label={t("console.status.active")} />;
  if (status === "suspended") return <StatusChip tone="sun" emoji="pause" label={t("console.status.suspended")} />;
  const key = `console.status.${status}`;
  const x = t(key);
  return <StatusChip tone="muted" emoji="label" label={x !== key ? x : humanise(status)} />;
}

export default function SuperAdminPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [token, setToken] = useState<string | null>(readToken);
  const [form, setForm] = useState({ email: "", password: "", totp: "" });
  const [tenants, setTenants] = useState<ConsoleTenantRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [health, setHealth] = useState<Record<string, Health>>({});
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [suspending, setSuspending] = useState<ConsoleTenantRow | null>(null);
  const [reason, setReason] = useState("");

  const signOut = () => {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
    setToken(null);
    setTenants([]);
    setLoaded(false);
  };

  const load = (tk: string) =>
    superAdminApi
      .tenants(tk)
      .then((rows) => {
        setTenants(rows);
        setLoaded(true);
      })
      .catch((err) => {
        setError(err);
        signOut();
      });

  useEffect(() => {
    if (token) load(token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const login = () => {
    setBusy(true);
    superAdminApi
      .login(form.email, form.password, form.totp)
      .then((r) => {
        try {
          sessionStorage.setItem(TOKEN_KEY, r.access_token);
        } catch {
          /* private mode: keep it in memory only */
        }
        setError(null);
        setForm({ email: form.email, password: "", totp: "" });
        setToken(r.access_token);
      })
      .catch(setError)
      .finally(() => setBusy(false));
  };

  const setStatus = (row: ConsoleTenantRow, status: string, why?: string) => {
    if (status === "suspended" && !why) return;
    superAdminApi.setStatus(token!, row.slug, status, why).then(() => load(token!)).catch(setError);
  };

  const checkHealth = (row: ConsoleTenantRow) => {
    setHealth((prev) => ({ ...prev, [row.slug]: "checking" }));
    superAdminApi
      .health(token!, row.slug)
      .then((h) => setHealth((prev) => ({ ...prev, [row.slug]: { ok: h.database.ok, issues: (h.connections ?? []).filter((c) => !c.ok).length } })))
      .catch((err) => {
        setHealth((prev) => {
          const next = { ...prev };
          delete next[row.slug];
          return next;
        });
        setError(err);
      });
  };

  const active = tenants.filter((r) => r.status === "active").length;
  const suspended = tenants.filter((r) => r.status === "suspended").length;

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: f.ground, px: { xs: 2, md: 3 }, py: { xs: 2, md: 3 } }}>
      <PageHeader
        emoji="shield"
        title={t("console.title")}
        purpose={token ? t("console.purpose_in", { count: tenants.length, active, suspended }) : t("console.purpose")}
        tourKey={token ? "console" : undefined}
        primary={token ? <Button variant="contained" onClick={signOut} startIcon={<Emoji name="door" size={16} />}>{t("console.sign_out")}</Button> : undefined}
      />

      {error !== null && <Box sx={{ mb: 2 }}><FriendlyError error={error} compact /></Box>}

      {!token ? (
        <Card sx={{ p: { xs: 2.5, md: 4 } }}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={4} alignItems="center">
            <Box sx={{ flex: 1, display: { xs: "none", md: "block" } }}>
              <Illustration name="secure-login" height={220} />
            </Box>
            <Stack spacing={2} component="form" sx={{ flex: 1, width: "100%", maxWidth: 440 }} onSubmit={(e) => { e.preventDefault(); login(); }}>
              <Typography component="h2" sx={{ fontWeight: 800, fontSize: 18 }}>{t("console.sign_in_title")}</Typography>
              <TextField label={t("console.email")} type="email" autoComplete="username" required value={form.email} placeholder="platform-admin@yourcompany.com"
                onChange={(e) => setForm({ ...form, email: e.target.value })} helperText={t("console.email_hint")} />
              <TextField label={t("console.password")} type="password" autoComplete="current-password" required value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })} />
              <TextField label={t("console.code")} inputMode="numeric" autoComplete="one-time-code" required value={form.totp} placeholder="482913"
                onChange={(e) => setForm({ ...form, totp: e.target.value.replace(/\D/g, "").slice(0, 8) })}
                helperText={t("console.code_hint")}
                slotProps={{ input: { startAdornment: <InputAdornment position="start"><Emoji name="lock" size={16} /></InputAdornment> } }} />
              <Button type="submit" variant="contained" size="large" disabled={busy}>{busy ? t("console.signing_in") : t("console.sign_in")}</Button>
              <Typography variant="caption" color="text.secondary">{t("console.two_step")}</Typography>
            </Stack>
          </Stack>
        </Card>
      ) : !loaded ? null : tenants.length === 0 ? (
        <Card><EmptyState illustration="void" title={tr("superadmin.empty")} /></Card>
      ) : (
        <Card sx={{ p: 0 }}>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>{tr("superadmin.company")}</TableCell>
                  <TableCell>{t("console.col.status")}</TableCell>
                  <TableCell>{t("console.col.isolation")}<InfoTip text={t("console.isolation_help")} /></TableCell>
                  <TableCell>{t("console.col.region")}</TableCell>
                  <TableCell>{t("console.col.domains")}</TableCell>
                  <TableCell>{t("console.col.health")}</TableCell>
                  <TableCell align="right">{t("console.col.actions")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {tenants.map((row) => {
                  const h = health[row.slug];
                  const isoKey = `console.iso.${row.isolation}`;
                  const iso = t(isoKey);
                  return (
                    <TableRow key={row.id} hover>
                      <TableCell>
                        <Typography sx={{ fontWeight: 700 }}>{row.name}</Typography>
                        <Typography variant="caption" color="text.secondary">{row.slug}{row.plan ? ` · ${t("console.plan", { plan: humanise(row.plan) })}` : ""}</Typography>
                      </TableCell>
                      <TableCell><StatusOf status={row.status} /></TableCell>
                      <TableCell>{iso !== isoKey ? iso : humanise(row.isolation)}</TableCell>
                      <TableCell>{row.region ?? "—"}</TableCell>
                      <TableCell>{row.domains.join(", ") || "—"}</TableCell>
                      <TableCell>
                        {!h ? <Typography variant="caption" color="text.secondary">{t("console.health_unknown")}</Typography>
                          : h === "checking" ? <StatusChip tone="muted" emoji="hourglass" label={t("console.checking")} />
                          : !h.ok ? <StatusChip tone="coral" emoji="fire" label={t("console.db_down")} />
                          : h.issues ? <StatusChip tone="sun" emoji="warning" label={t("console.issues", { count: h.issues })} />
                          : <StatusChip status="done" label={t("console.all_ok")} />}
                      </TableCell>
                      <TableCell align="right">
                        <Stack direction="row" spacing={1} justifyContent="flex-end">
                          <Button size="small" variant="outlined" onClick={() => checkHealth(row)}>{t("console.check")}</Button>
                          {row.status === "active" && <Button size="small" color="warning" variant="outlined" onClick={() => { setReason(""); setSuspending(row); }}>{t("console.suspend")}</Button>}
                          {row.status === "suspended" && <Button size="small" variant="contained" onClick={() => setStatus(row, "active")}>{t("console.resume")}</Button>}
                        </Stack>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}

      <Dialog open={Boolean(suspending)} onClose={() => setSuspending(null)} maxWidth="sm" fullWidth aria-labelledby="suspend-title">
        <DialogTitle id="suspend-title">{t("console.suspend_title", { name: suspending?.name ?? "" })}</DialogTitle>
        <DialogContent>
          <Typography sx={{ color: "text.secondary", mb: 1.5 }}>{t("console.suspend_body")}</Typography>
          <TextField autoFocus fullWidth multiline minRows={2} label={t("console.reason")} value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder={t("console.reason_eg")} helperText={t("console.reason_hint")} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSuspending(null)}>{t("action.cancel")}</Button>
          <Button variant="contained" color="warning" disabled={!reason.trim()}
            onClick={() => { if (suspending) setStatus(suspending, "suspended", reason.trim()); setSuspending(null); }}>
            {t("console.suspend")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
