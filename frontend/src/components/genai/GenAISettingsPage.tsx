import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, http, platformSettingsApi } from "../../api/client";
import { useT } from "../../i18n";
import ConfirmDialog from "../ConfirmDialog";

interface Feature { code: string; module: string; label: string; enabled: boolean; switched_off: boolean; model_key: string | null; model: string | null }
interface LimitRow { scope: string; key: string; limit: number; used: number; pct: number; mode: string }
interface GenAI {
  enabled: boolean; provider: string; key: { source: string; masked: string | null; last_tested_at: string | null; last_test_ok: boolean | null };
  available_models: string[]; default_model: string; fallback_model: string; max_tokens_per_request: number; temperature: string; currency: string;
  pricing: Record<string, { input_per_mtok?: number; output_per_mtok?: number }>; features: Feature[]; modules: string[];
  limits: { module_monthly_tokens: Record<string, number>; user_daily_tokens: number; company_monthly_tokens: number; on_limit: Record<string, string>; warn_pct: number; reset_day: number; status: LimitRow[] };
}

// Part 18.23 + 18.25: Settings > Integrations > GenAI -- what is in use today and every knob:
// provider + key (masked, test, disconnect), models (default / fallback / per feature), max
// tokens, temperature, on/off per feature, prices, and the usage limits.
export default function GenAISettingsPage() {
  const t = useT();
  const [d, setD] = useState<GenAI | null>(null);
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmOff, setConfirmOff] = useState(false);
  const [newModel, setNewModel] = useState("");

  const load = useCallback(() => { http.get<GenAI>("/api/v1/ui/genai/settings").then(setD).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, t("genai.err")) })); }, [t]);
  useEffect(load, [load]);
  const save = async (k: string, v: unknown) => {
    try { await platformSettingsApi.update(k, v); setMsg({ ok: true, text: t("genai.saved") }); load(); } catch (e) { setMsg({ ok: false, text: extractErrorMessage(e, t("genai.err")) }); }
  };
  const run = async (fn: () => Promise<unknown>, ok: (r: unknown) => string) => {
    setBusy(true); setMsg(null);
    try { const r = await fn(); setMsg({ ok: true, text: ok(r) }); load(); } catch (e) { setMsg({ ok: false, text: extractErrorMessage(e, t("genai.err")) }); } finally { setBusy(false); }
  };
  if (!d) return msg ? <Alert severity="error">{msg.text}</Alert> : null;
  const models = d.available_models;
  const disabledList = d.features.filter((f) => f.switched_off).map((f) => f.code);

  return (
    <Stack spacing={2}>
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      <Card><CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Typography variant="h6">{t("genai.provider_title")}</Typography>
          <Chip color={d.enabled ? "success" : "default"} label={d.enabled ? t("genai.on") : t("genai.off")} />
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ my: 1 }}>
          {t("genai.in_use", { provider: "Anthropic Claude", source: t(`genai.source.${d.key.source}`), masked: d.key.masked ?? "—" })}
          {d.key.last_tested_at && ` · ${d.key.last_test_ok ? t("conn.last_ok") : t("conn.last_failed")} ${new Date(d.key.last_tested_at).toLocaleString()}`}
        </Typography>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1} alignItems={{ md: "center" }}>
          <TextField select size="small" label={t("genai.provider")} value={d.provider} sx={{ minWidth: 200 }} disabled>
            <MenuItem value="anthropic">Anthropic Claude</MenuItem>
          </TextField>
          <TextField size="small" type="password" autoComplete="new-password" label={t("genai.key")} placeholder="sk-ant-api03-…" value={key}
            onChange={(e) => setKey(e.target.value)} helperText={t("genai.key_hint")} sx={{ minWidth: 280 }} />
          <Button variant="contained" disabled={busy || !key} onClick={() => run(() => http.put("/api/v1/ui/genai/key", { api_key: key }).then((r) => { setKey(""); return r; }), () => t("genai.key_saved"))}>{t("lock.save")}</Button>
          <Button disabled={busy} onClick={() => run(() => http.post<{ ok: boolean; error: string | null; model: string | null }>("/api/v1/ui/genai/test", {}),
            (r) => { const x = r as { ok: boolean; error: string | null; model: string | null }; return x.ok ? t("genai.test_ok", { model: x.model ?? "" }) : t("genai.test_bad", { error: x.error ?? "" }); })}>{t("conn.test")}</Button>
          {d.key.source === "company" && <Button disabled={busy} onClick={() => run(() => http.put("/api/v1/ui/genai/key", { api_key: "" }), () => t("genai.key_removed"))}>{t("genai.use_server_key")}</Button>}
          {d.enabled
            ? <Button color="error" onClick={() => setConfirmOff(true)}>{t("conn.disconnect")}</Button>
            : <Button variant="outlined" onClick={() => save("ai.enabled", true)}>{t("genai.switch_on")}</Button>}
        </Stack>
      </CardContent></Card>

      <Card><CardContent>
        <Typography variant="h6" sx={{ mb: 1 }}>{t("genai.models_title")}</Typography>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} flexWrap="wrap" useFlexGap>
          <TextField select size="small" label={t("genai.default_model")} value={d.default_model} onChange={(e) => save("ai.default_model", e.target.value)} sx={{ minWidth: 200 }}>
            {models.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
          </TextField>
          <TextField select size="small" label={t("genai.fallback_model")} value={d.fallback_model} onChange={(e) => save("ai.fallback_model", e.target.value)} sx={{ minWidth: 200 }}>
            {models.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
          </TextField>
          <TextField size="small" type="number" label={t("genai.max_tokens")} defaultValue={d.max_tokens_per_request} sx={{ width: 170 }}
            onBlur={(e) => Number(e.target.value) !== d.max_tokens_per_request && save("ai.max_tokens_per_request", Number(e.target.value))} />
          <TextField size="small" label={t("genai.temperature")} placeholder={t("genai.temperature_eg")} defaultValue={d.temperature} sx={{ width: 170 }}
            onBlur={(e) => e.target.value !== d.temperature && save("ai.temperature", e.target.value)} />
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mt: 1.5 }}>
          <Typography variant="body2">{t("genai.available")}</Typography>
          {models.map((m) => <Chip key={m} size="small" label={m} onDelete={models.length > 1 ? () => save("ai.available_models", models.filter((x) => x !== m)) : undefined} />)}
          <TextField size="small" placeholder={t("genai.add_model")} value={newModel} onChange={(e) => setNewModel(e.target.value)} sx={{ width: 200 }} />
          <Button size="small" disabled={!newModel.trim()} onClick={() => { void save("ai.available_models", [...models, newModel.trim()]); setNewModel(""); }}>{t("genai.add")}</Button>
        </Stack>
      </CardContent></Card>

      <Card><CardContent>
        <Typography variant="h6" sx={{ mb: 1 }}>{t("genai.features_title")}</Typography>
        <Table size="small">
          <TableHead><TableRow><TableCell>{t("genai.feature")}</TableCell><TableCell>{t("genai.module")}</TableCell><TableCell>{t("genai.model")}</TableCell><TableCell>{t("genai.onoff")}</TableCell></TableRow></TableHead>
          <TableBody>
            {d.features.filter((f) => f.code !== "platform.genai_test").map((f) => (
              <TableRow key={f.code}>
                <TableCell>{f.label}</TableCell>
                <TableCell>{f.module}</TableCell>
                <TableCell>
                  {f.model_key ? (
                    <TextField select size="small" value={f.model ?? ""} onChange={(e) => save(`ai.models.${f.model_key}`, e.target.value)} sx={{ minWidth: 180 }}>
                      {Array.from(new Set([...models, f.model ?? ""])).filter(Boolean).map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
                    </TextField>
                  ) : <Typography variant="caption">{t("genai.default_used")}</Typography>}
                </TableCell>
                <TableCell>
                  <Switch checked={!f.switched_off} onChange={(e) => save("ai.features.disabled", e.target.checked ? disabledList.filter((c) => c !== f.code) : [...disabledList, f.code])} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent></Card>

      <Card><CardContent>
        <Typography variant="h6">{t("genai.prices_title")}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{t("genai.prices_intro", { currency: d.currency })}</Typography>
        <Stack spacing={1}>
          <TextField size="small" label={t("genai.currency")} defaultValue={d.currency} sx={{ width: 140 }} onBlur={(e) => e.target.value !== d.currency && save("ai.currency", e.target.value)} />
          {models.map((m) => {
            const p = d.pricing[m] ?? {};
            const per1k = (v?: number) => (v != null ? String(v / 1000) : "");
            const put = (field: "input_per_mtok" | "output_per_mtok", v: string) => save("ai.pricing", { ...d.pricing, [m]: { ...p, [field]: Number(v) * 1000 } });
            return (
              <Stack key={m} direction="row" spacing={1} alignItems="center">
                <Typography sx={{ width: 180 }}>{m}</Typography>
                <TextField size="small" type="number" label={t("genai.price_in")} defaultValue={per1k(p.input_per_mtok)} sx={{ width: 160 }} onBlur={(e) => e.target.value && put("input_per_mtok", e.target.value)} />
                <TextField size="small" type="number" label={t("genai.price_out")} defaultValue={per1k(p.output_per_mtok)} sx={{ width: 160 }} onBlur={(e) => e.target.value && put("output_per_mtok", e.target.value)} />
              </Stack>
            );
          })}
        </Stack>
      </CardContent></Card>

      <Card><CardContent>
        <Typography variant="h6">{t("genai.limits_title")}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t("genai.limits_intro")}</Typography>
        <Stack spacing={1}>
          {d.modules.filter((m) => m !== "platform").map((m) => (
            <Stack key={m} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
              <Typography sx={{ width: 160, fontWeight: 600 }}>{m}</Typography>
              <TextField size="small" type="number" label={t("genai.module_limit")} placeholder={t("genai.no_limit")} defaultValue={d.limits.module_monthly_tokens[m] ?? ""} sx={{ width: 220 }}
                onBlur={(e) => { const v = e.target.value; const next = { ...d.limits.module_monthly_tokens }; if (v) next[m] = Number(v); else delete next[m]; void save("ai.limits.module_monthly_tokens", next); }} />
              <TextField select size="small" label={t("genai.at_100")} value={d.limits.on_limit[m] ?? "block"} sx={{ width: 220 }}
                onChange={(e) => save("ai.limits.on_limit", { ...d.limits.on_limit, [m]: e.target.value })}>
                <MenuItem value="block">{t("genai.mode.block")}</MenuItem>
                <MenuItem value="warn">{t("genai.mode.warn")}</MenuItem>
              </TextField>
            </Stack>
          ))}
          <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ pt: 1 }}>
            <TextField size="small" type="number" label={t("genai.company_limit")} placeholder={t("genai.no_limit")} defaultValue={d.limits.company_monthly_tokens || ""} sx={{ width: 230 }}
              onBlur={(e) => save("ai.limits.company_monthly_tokens", Number(e.target.value || 0))} />
            <TextField size="small" type="number" label={t("genai.user_limit")} placeholder={t("genai.no_limit")} defaultValue={d.limits.user_daily_tokens || ""} sx={{ width: 230 }}
              onBlur={(e) => save("ai.limits.user_daily_tokens", Number(e.target.value || 0))} />
            <TextField size="small" type="number" label={t("genai.warn_pct")} defaultValue={d.limits.warn_pct} sx={{ width: 150 }} onBlur={(e) => save("ai.limits.warn_pct", Number(e.target.value || 80))} />
            <TextField size="small" type="number" label={t("genai.reset_day")} defaultValue={d.limits.reset_day} sx={{ width: 150 }} onBlur={(e) => save("ai.limits.reset_day", Number(e.target.value || 1))} />
          </Stack>
          {d.limits.status.map((s) => (
            <Box key={`${s.scope}-${s.key}`}>
              <Typography variant="body2">{t("genai.limit_line", { what: s.scope === "company" ? t("genai.company") : s.key, used: s.used.toLocaleString(), limit: s.limit.toLocaleString(), pct: s.pct })}</Typography>
              <LinearProgress variant="determinate" value={Math.min(100, s.pct)} color={s.pct >= 100 ? "error" : s.pct >= d.limits.warn_pct ? "warning" : "primary"} />
            </Box>
          ))}
        </Stack>
      </CardContent></Card>
      <ConfirmDialog open={confirmOff} title={t("genai.off_title")} message={t("genai.off_body")} confirmLabel={t("conn.disconnect")} destructive
        onConfirm={() => { setConfirmOff(false); void run(() => http.post("/api/v1/ui/genai/disconnect", {}), () => t("genai.off_done")); }} onCancel={() => setConfirmOff(false)} />
    </Stack>
  );
}
