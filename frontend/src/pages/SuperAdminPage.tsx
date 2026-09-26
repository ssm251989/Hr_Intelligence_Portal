import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, superAdminApi, type ConsoleTenantRow } from "../api/client";
import { t as tr } from "../i18n";

// Part 13 section B (docs/HRMS_COMPLETE_SPEC.txt): the Super-Admin console -- a separate
// route and a separate identity (platform admin + mandatory TOTP), never a tenant session.
// The console token lives only in sessionStorage and is short-lived (server-side expiry).
// Impersonation, plans and usage have full APIs; this page covers sign-in, the tenant list,
// suspend/resume and per-tenant health.

const TOKEN_KEY = "hrms.console.token";

function readToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export default function SuperAdminPage() {
  const [token, setToken] = useState<string | null>(readToken);
  const [form, setForm] = useState({ email: "", password: "", totp: "" });
  const [tenants, setTenants] = useState<ConsoleTenantRow[]>([]);
  const [health, setHealth] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const signOut = () => {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
    setToken(null);
  };

  const load = (t: string) =>
    superAdminApi
      .tenants(t)
      .then(setTenants)
      .catch((err) => {
        setError(extractErrorMessage(err, "Session expired"));
        signOut();
      });

  useEffect(() => {
    if (token) load(token);
  }, [token]);

  const login = () =>
    superAdminApi
      .login(form.email, form.password, form.totp)
      .then((r) => {
        try {
          sessionStorage.setItem(TOKEN_KEY, r.access_token);
        } catch {
          /* private mode: keep it in memory only */
        }
        setError(null);
        setToken(r.access_token);
      })
      .catch((err) => setError(extractErrorMessage(err, "Sign-in failed")));

  const setStatus = (row: ConsoleTenantRow, status: string) => {
    const reason = status === "suspended" ? window.prompt("Reason shown to the client's users:") ?? undefined : undefined;
    if (status === "suspended" && !reason) return;
    superAdminApi.setStatus(token!, row.slug, status, reason).then(() => load(token!)).catch((err) => setError(extractErrorMessage(err, "Failed")));
  };

  const checkHealth = (row: ConsoleTenantRow) =>
    superAdminApi
      .health(token!, row.slug)
      .then((h) => setHealth((prev) => ({ ...prev, [row.slug]: h.database.ok ? `DB ok · ${(h.connections ?? []).filter((c) => !c.ok).length} connection issue(s)` : "DB unreachable" })));

  return (
    <Box sx={{ maxWidth: 1100, mx: "auto", p: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h5" component="h1">Platform console</Typography>
        {token && <Button onClick={signOut}>Sign out</Button>}
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {!token ? (
        <Card sx={{ maxWidth: 420 }}>
          <CardContent>
            <Stack spacing={2} component="form" onSubmit={(e) => { e.preventDefault(); login(); }}>
              <TextField label="Email" type="email" autoComplete="username" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              <TextField label="Password" type="password" autoComplete="current-password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              <TextField label="Authenticator code" inputMode="numeric" autoComplete="one-time-code" required value={form.totp} onChange={(e) => setForm({ ...form, totp: e.target.value })} />
              <Button type="submit" variant="contained">Sign in</Button>
              <Typography variant="caption" color="text.secondary">Two-factor authentication is mandatory for the console.</Typography>
            </Stack>
          </CardContent>
        </Card>
      ) : tenants.length === 0 ? (
        <Typography color="text.secondary">{tr("superadmin.empty")}</Typography>
      ) : (
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{tr("superadmin.company")}</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Isolation</TableCell>
                <TableCell>Region</TableCell>
                <TableCell>Domains</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {tenants.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{row.name}<br /><Typography variant="caption" color="text.secondary">{row.slug}{row.plan ? ` · ${row.plan}` : ""}</Typography></TableCell>
                  <TableCell><Chip size="small" label={row.status} color={row.status === "active" ? "success" : row.status === "suspended" ? "warning" : "default"} /></TableCell>
                  <TableCell>{row.isolation}</TableCell>
                  <TableCell>{row.region ?? "—"}</TableCell>
                  <TableCell>{row.domains.join(", ") || "—"}</TableCell>
                  <TableCell align="right">
                    <Button size="small" onClick={() => checkHealth(row)}>Health</Button>
                    {row.status === "active" && <Button size="small" color="warning" onClick={() => setStatus(row, "suspended")}>Suspend</Button>}
                    {row.status === "suspended" && <Button size="small" onClick={() => setStatus(row, "active")}>Resume</Button>}
                    {health[row.slug] && <Typography variant="caption" display="block">{health[row.slug]}</Typography>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </Box>
  );
}
