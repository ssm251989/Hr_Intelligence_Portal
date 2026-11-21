// Part 30.2f: Settings > Developers -- API keys (shown once), calls per day, webhooks (secret shown once), test ping,
// delivery log with Resend. Admin only (platform.api_keys.manage); the backend refuses everyone else.
import { useCallback, useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import Grid from "@mui/material/Grid";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { http } from "../../api/client";
import { useT } from "../../i18n";
import { PageHeader } from "../../ui-kit";
import { formatDateTime } from "../../utils/datetime";

type Overview = { mode: "live" | "test"; sandbox: boolean; scopes: string[]; events: string[]; base_url: string; docs_url: string };
type ApiKeyRow = { id: string; name: string; prefix: string; scopes: string[]; mode: string; created_at: string | null;
  last_used_at: string | null; expires_at: string | null; revoked_at: string | null };
type Hook = { id: string; url: string; events: string[]; scopes: string[]; active: boolean; created_at: string | null };
type Delivery = { id: string; event: string; status: "pending" | "delivered" | "failed"; attempts: number; last_status: number | null;
  last_error: string | null; created_at: string | null; next_at: string | null };
type UsageRow = { day: string; key_id: string | null; calls: number; errors: number };

const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const STATUS_COLOR = { pending: "warning", delivered: "success", failed: "error" } as const;

export default function DevelopersPage() {
  const t = useT();
  const theme = useTheme();
  const f = theme.palette.fresh;
  const [ov, setOv] = useState<Overview | null>(null);
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [hooks, setHooks] = useState<Hook[]>([]);
  const [usage, setUsage] = useState<UsageRow[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [shown, setShown] = useState<{ title: string; value: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [keyName, setKeyName] = useState("");
  const [keyScopes, setKeyScopes] = useState<string[]>([]);
  const [keyExpires, setKeyExpires] = useState("");
  const [hookUrl, setHookUrl] = useState("");
  const [hookEvents, setHookEvents] = useState<string[]>([]);
  const [hookSensitive, setHookSensitive] = useState(false);
  const [logOf, setLogOf] = useState<Hook | null>(null);
  const [log, setLog] = useState<Delivery[]>([]);
  const [table, setTable] = useState(false);

  const load = useCallback(() => {
    http.get<Overview>("/api/v1/ui/developers/overview").then(setOv).catch((e) => setMsg({ ok: false, text: (e as Error).message }));
    http.get<{ items: ApiKeyRow[] }>("/api/v1/ui/developers/keys").then((r) => setKeys(r.items)).catch(() => setKeys([]));
    http.get<{ items: Hook[] }>("/api/v1/ui/developers/webhooks").then((r) => setHooks(r.items)).catch(() => setHooks([]));
    http.get<{ items: UsageRow[] }>("/api/v1/ui/developers/usage?days=30").then((r) => setUsage(r.items)).catch(() => setUsage([]));
  }, []);
  useEffect(load, [load]);

  const fail = (e: unknown) => setMsg({ ok: false, text: (e as Error).message || t("dev.error") });
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  const createKey = async () => {
    try {
      const r = await http.post<ApiKeyRow & { key: string }>("/api/v1/ui/developers/keys", {
        name: keyName, scopes: keyScopes, expires_at: keyExpires ? new Date(`${keyExpires}T23:59:59`).toISOString() : null });
      setShown({ title: t("dev.new_key"), value: r.key });
      setKeyName(""); setKeyScopes([]); setKeyExpires("");
      load();
    } catch (e) { fail(e); }
  };
  const revoke = async (k: ApiKeyRow) => {
    if (!window.confirm(t("dev.revoke_confirm"))) return;
    try { await http.post(`/api/v1/ui/developers/keys/${k.id}/revoke`, {}); load(); } catch (e) { fail(e); }
  };
  const addHook = async () => {
    try {
      const r = await http.post<Hook & { secret: string }>("/api/v1/ui/developers/webhooks", {
        url: hookUrl, events: hookEvents, scopes: hookSensitive ? ["sensitive"] : [] });
      setShown({ title: t("dev.new_secret"), value: r.secret });
      setHookUrl(""); setHookEvents([]); setHookSensitive(false);
      load();
    } catch (e) { fail(e); }
  };
  const setActive = async (h: Hook, active: boolean) => {
    try { await http.patch(`/api/v1/ui/developers/webhooks/${h.id}`, { active }); load(); } catch (e) { fail(e); }
  };
  const openLog = (h: Hook) => {
    setLogOf(h);
    http.get<{ items: Delivery[] }>(`/api/v1/ui/developers/webhooks/${h.id}/deliveries`).then((r) => setLog(r.items)).catch(() => setLog([]));
  };
  const ping = async (h: Hook) => {
    try { await http.post(`/api/v1/ui/developers/webhooks/${h.id}/ping`, {}); openLog(h); } catch (e) { fail(e); }
  };
  const resend = async (d: Delivery) => {
    try { await http.post(`/api/v1/ui/developers/deliveries/${d.id}/resend`, {}); if (logOf) openLog(logOf); } catch (e) { fail(e); }
  };
  const copy = async (v: string) => {
    try { await navigator.clipboard.writeText(v); setCopied(true); } catch { /* the value stays selectable */ }
  };

  // calls per day, all keys together (one series: no legend; the tooltip and the table carry the numbers)
  const days = useMemo(() => {
    const by: Record<string, { calls: number; errors: number }> = {};
    for (const u of usage) {
      by[u.day] = by[u.day] ?? { calls: 0, errors: 0 };
      by[u.day].calls += u.calls;
      by[u.day].errors += u.errors;
    }
    return Object.entries(by).sort(([a], [b]) => a.localeCompare(b)).map(([day, v]) => ({ day, ...v }));
  }, [usage]);
  const peak = Math.max(1, ...days.map((d) => d.calls));

  const keyState = (k: ApiKeyRow) =>
    k.revoked_at ? <Chip size="small" label={t("dev.revoked")} /> : k.expires_at && new Date(k.expires_at) < new Date()
      ? <Chip size="small" color="warning" label={t("dev.expired")} /> : <Chip size="small" color="success" variant="outlined" label={t("dev.active")} />;

  return (
    <Box>
      <PageHeader emoji="technologist" title={t("dev.title")} purpose={t("dev.purpose")}
        primary={ov ? <Button component={Link} href={`${API_BASE}${ov.docs_url}`} target="_blank" rel="noopener" variant="outlined">{t("dev.docs")}</Button> : undefined} />
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)} sx={{ mb: 2 }}>{msg.text}</Alert>}
      {ov && <Alert severity={ov.mode === "test" ? "warning" : "info"} sx={{ mb: 2 }}>{t(ov.mode === "test" ? "dev.mode_test" : "dev.mode_live")}</Alert>}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Card sx={{ p: 2, mb: 2 }}>
            <Typography variant="h6">{t("dev.keys")}</Typography>
            <Typography variant="body2" sx={{ color: f.muted, mb: 1.5 }}>{t("dev.keys_help")}</Typography>
            <Stack spacing={1.5}>
              <TextField size="small" label={t("dev.name")} value={keyName} onChange={(e) => setKeyName(e.target.value)} inputProps={{ maxLength: 100 }} />
              <Box>
                <Typography variant="caption" sx={{ color: f.muted }}>{t("dev.scopes")}</Typography>
                <Stack direction="row" useFlexGap flexWrap="wrap">
                  {(ov?.scopes ?? []).map((s) => (
                    <FormControlLabel key={s} control={<Checkbox size="small" checked={keyScopes.includes(s)} onChange={() => setKeyScopes(toggle(keyScopes, s))} />}
                      label={t(`dev.scope.${s}`)} />
                  ))}
                </Stack>
              </Box>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
                <TextField size="small" type="date" label={t("dev.expires")} value={keyExpires} onChange={(e) => setKeyExpires(e.target.value)}
                  InputLabelProps={{ shrink: true }} sx={{ minWidth: 200 }} />
                <Button variant="contained" disabled={!keyName.trim() || keyScopes.length === 0} onClick={createKey}>{t("dev.create_key")}</Button>
              </Stack>
            </Stack>
            <Box sx={{ mt: 2 }}>
              {keys.length === 0 ? <Typography variant="body2" sx={{ color: f.muted }}>{t("dev.no_keys")}</Typography> : keys.map((k) => (
                <Stack key={k.id} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ py: 1, borderTop: `1px solid ${f.line}` }}>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Typography sx={{ fontWeight: 600 }}>{k.name}</Typography>{keyState(k)}
                    </Stack>
                    <Typography variant="body2" sx={{ fontFamily: "monospace", color: f.muted }}>{k.prefix}…</Typography>
                    <Typography variant="caption" sx={{ color: f.muted }}>
                      {k.scopes.map((s) => t(`dev.scope.${s}`)).join(", ")} · {t("dev.last_used")}: {k.last_used_at ? formatDateTime(k.last_used_at) : t("dev.never")}
                    </Typography>
                  </Box>
                  {!k.revoked_at && <Button size="small" color="error" variant="outlined" onClick={() => revoke(k)}>{t("dev.revoke")}</Button>}
                </Stack>
              ))}
            </Box>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 5 }}>
          <Card sx={{ p: 2, mb: 2 }}>
            <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="h6" sx={{ flex: 1 }}>{t("dev.usage")}</Typography>
              {days.length > 0 && <Button size="small" onClick={() => setTable(!table)}>{t(table ? "dev.hide_table" : "dev.show_table")}</Button>}
            </Stack>
            {days.length === 0 ? <Typography variant="body2" sx={{ color: f.muted }}>{t("dev.usage_empty")}</Typography> : (
              <>
                <Stack direction="row" alignItems="flex-end" spacing="2px" sx={{ height: 120, borderBottom: `1px solid ${f.line}` }} role="img"
                  aria-label={t("dev.usage")}>
                  {days.map((d) => (
                    <Tooltip key={d.day} title={`${d.day}: ${t("dev.calls", { n: d.calls, e: d.errors })}`} arrow>
                      <Box sx={{ flex: 1, minWidth: 4, maxWidth: 24, height: "100%", display: "flex", alignItems: "flex-end", cursor: "default" }}>
                        <Box sx={{ width: "100%", height: `${Math.max(2, (d.calls / peak) * 100)}%`, bgcolor: "primary.main", borderRadius: "4px 4px 0 0" }} />
                      </Box>
                    </Tooltip>
                  ))}
                </Stack>
                <Stack direction="row" justifyContent="space-between" sx={{ mt: 0.5 }}>
                  <Typography variant="caption" sx={{ color: f.muted }}>{days[0].day}</Typography>
                  <Typography variant="caption" sx={{ color: f.muted }}>{days[days.length - 1].day}</Typography>
                </Stack>
                {table && (
                  <Box component="table" sx={{ width: "100%", mt: 1, borderCollapse: "collapse", "& td, & th": { py: 0.5, textAlign: "left", fontSize: 13 } }}>
                    <thead><tr><th>{t("dev.day")}</th><th>{t("dev.calls_col")}</th><th>{t("dev.errors_col")}</th></tr></thead>
                    <tbody>{days.map((d) => <tr key={d.day}><td>{d.day}</td><td>{d.calls}</td><td>{d.errors}</td></tr>)}</tbody>
                  </Box>
                )}
              </>
            )}
          </Card>
        </Grid>

        <Grid size={{ xs: 12 }}>
          <Card sx={{ p: 2 }}>
            <Typography variant="h6">{t("dev.webhooks")}</Typography>
            <Typography variant="body2" sx={{ color: f.muted, mb: 1.5 }}>{t("dev.webhooks_help")}</Typography>
            <Stack spacing={1.5}>
              <TextField size="small" label={t("dev.url")} value={hookUrl} onChange={(e) => setHookUrl(e.target.value)} />
              <Box>
                <Typography variant="caption" sx={{ color: f.muted }}>{t("dev.events")}</Typography>
                <Stack direction="row" useFlexGap flexWrap="wrap">
                  {(ov?.events ?? []).map((ev) => (
                    <FormControlLabel key={ev} control={<Checkbox size="small" checked={hookEvents.includes(ev)} onChange={() => setHookEvents(toggle(hookEvents, ev))} />}
                      label={<Typography variant="body2" sx={{ fontFamily: "monospace" }}>{ev}</Typography>} />
                  ))}
                </Stack>
              </Box>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
                <FormControlLabel control={<Checkbox size="small" checked={hookSensitive} onChange={(e) => setHookSensitive(e.target.checked)} />} label={t("dev.scope.sensitive")} />
                <Button variant="contained" disabled={!hookUrl.trim() || hookEvents.length === 0} onClick={addHook}>{t("dev.add_webhook")}</Button>
              </Stack>
            </Stack>
            <Box sx={{ mt: 2 }}>
              {hooks.length === 0 ? <Typography variant="body2" sx={{ color: f.muted }}>{t("dev.no_webhooks")}</Typography> : hooks.map((h) => (
                <Stack key={h.id} direction={{ xs: "column", md: "row" }} spacing={1} alignItems={{ md: "center" }} sx={{ py: 1, borderTop: `1px solid ${f.line}` }}>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography sx={{ fontFamily: "monospace", wordBreak: "break-all" }}>{h.url}</Typography>
                    <Typography variant="caption" sx={{ color: f.muted }}>{h.events.join(", ")}{h.scopes.includes("sensitive") ? ` · ${t("dev.scope.sensitive")}` : ""}</Typography>
                  </Box>
                  <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                    <FormControlLabel control={<Switch size="small" checked={h.active} onChange={(e) => setActive(h, e.target.checked)} />} label={t("dev.on")} />
                    <Button size="small" onClick={() => ping(h)}>{t("dev.ping")}</Button>
                    <Button size="small" variant="outlined" onClick={() => openLog(h)}>{t("dev.log")}</Button>
                  </Stack>
                </Stack>
              ))}
            </Box>
          </Card>
        </Grid>
      </Grid>

      <Dialog open={!!shown} onClose={() => { setShown(null); setCopied(false); }} maxWidth="sm" fullWidth>
        <DialogTitle>{shown?.title}</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 1.5 }}>{t("dev.copy_once")}</Alert>
          <TextField fullWidth value={shown?.value ?? ""} InputProps={{ readOnly: true, sx: { fontFamily: "monospace" } }} onFocus={(e) => e.target.select()} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => shown && copy(shown.value)}>{copied ? t("dev.copied") : t("dev.copy")}</Button>
          <Button variant="contained" onClick={() => { setShown(null); setCopied(false); }}>{t("dev.done")}</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!logOf} onClose={() => setLogOf(null)} maxWidth="md" fullWidth>
        <DialogTitle>{t("dev.log")}</DialogTitle>
        <DialogContent>
          {log.length === 0 ? <Typography sx={{ color: f.muted }}>{t("dev.no_deliveries")}</Typography> : log.map((d) => (
            <Stack key={d.id} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ py: 0.75, borderBottom: `1px solid ${f.line}` }}>
              <Chip size="small" color={STATUS_COLOR[d.status]} label={t(`dev.status.${d.status}`)} />
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography variant="body2" sx={{ fontFamily: "monospace" }}>{d.event}</Typography>
                <Typography variant="caption" sx={{ color: f.muted }}>
                  {d.created_at ? formatDateTime(d.created_at) : ""} · {t("dev.attempts", { n: d.attempts })}{d.last_status ? ` · HTTP ${d.last_status}` : ""}
                  {d.last_error ? ` · ${d.last_error}` : ""}
                </Typography>
              </Box>
              {d.status !== "delivered" && <Button size="small" onClick={() => resend(d)}>{t("dev.resend")}</Button>}
            </Stack>
          ))}
        </DialogContent>
      </Dialog>
    </Box>
  );
}
