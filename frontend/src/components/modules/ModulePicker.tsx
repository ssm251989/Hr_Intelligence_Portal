import { useCallback, useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { moduleErrorDetail, modulesApi19, type ModuleCard, type ModulesState } from "../../api/modulesApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";
import { celebrate, Emoji } from "../../ui-kit";

// Part 19.1 / 19.2: "Choose what you use" -- one card per module with what you get and an
// on/off switch (Setup checklist and Settings > Company > Modules). Switching ON waits for an
// activation code that CTD Techs receives by email; switching OFF is immediate. Dependencies
// come from the server registry and are asked about, never hidden.

type Ask =
  | { kind: "needs"; key: string; needs: string[] }
  | { kind: "off"; keys: string[] }
  | { kind: "dependents"; keys: string[]; dependents: string[] };

/** XXXX-XXXX as the user types; only the letters/digits a code can have. */
function formatCode(raw: string): string {
  const clean = raw.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
  return clean.length > 4 ? `${clean.slice(0, 4)}-${clean.slice(4)}` : clean;
}

export default function ModulePicker({ variant = "settings", onChange }: { variant?: "setup" | "settings"; onChange?: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { reload } = useMeBootstrap();
  const [state, setState] = useState<ModulesState | null>(null);
  const [draft, setDraft] = useState<Set<string>>(new Set());
  const [ask, setAsk] = useState<Ask | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "success" | "error" | "warning" | "info"; text: string } | null>(null);

  // the server's English text unless this language has its own
  const tx = useCallback((key: string, fallback: string, vars?: Record<string, string | number>) => {
    const v = t(key, vars);
    return v === key ? fallback : v;
  }, [t]);
  const name = useCallback((m: ModuleCard) => tx(`mod19.m.${m.key}.name`, m.name), [tx]);

  const load = useCallback(() => {
    modulesApi19.list().then(setState).catch((err) => setMsg({ tone: "error", text: extractErrorMessage(err, t("mod19.err")) }));
  }, [t]);
  useEffect(load, [load]);

  const byKey = useMemo(() => Object.fromEntries((state?.modules ?? []).map((m) => [m.key, m])), [state]);
  const names = (keys: string[]) => keys.map((k) => (byKey[k] ? name(byKey[k]) : k)).join(", ");
  const isOn = (m: ModuleCard) => m.status !== "off" || draft.has(m.key);
  const canManage = Boolean(state?.can_manage);
  const req = state?.request ?? null;
  const reqExpired = req?.status === "expired";

  const after = (next: ModulesState) => {
    setState(next);
    reload();
    onChange?.();
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const toggle = (m: ModuleCard, checked: boolean) => {
    if (checked) {
      const on = new Set([...(state?.modules ?? []).filter((x) => x.status !== "off").map((x) => x.key), ...draft]);
      const missing = m.needs.filter((n) => !on.has(n));
      if (missing.length) setAsk({ kind: "needs", key: m.key, needs: missing });
      else setDraft((d) => new Set([...d, m.key]));
      return;
    }
    if (draft.has(m.key)) {
      // also drop drafts that needed it
      setDraft((d) => new Set([...d].filter((k) => k !== m.key && !(byKey[k]?.needs ?? []).includes(m.key))));
      return;
    }
    setAsk({ kind: "off", keys: [m.key] });
  };

  const switchOff = (keys: string[], withDependents: boolean) => run(async () => {
    setAsk(null);
    try {
      const next = await modulesApi19.off(keys, withDependents);
      after(next);
      setMsg({ tone: "success", text: t("mod19.off_done", { names: names(next.switched_off) }) });
    } catch (err) {
      const d = moduleErrorDetail(err);
      if (d?.code === "MODULE_NEEDED" && d.dependents?.length) setAsk({ kind: "dependents", keys, dependents: d.dependents });
      else setMsg({ tone: "error", text: extractErrorMessage(err, t("mod19.err")) });
    }
  });

  const requestActivation = (keys: string[]) => run(async () => {
    try {
      const next = await modulesApi19.request(keys, true);
      setDraft(new Set());
      after(next);
      setMsg(next.requested.email_sent
        ? { tone: "info", text: t("mod19.requested") }
        : { tone: "warning", text: t("mod19.requested_no_email") });
    } catch (err) {
      setMsg({ tone: "error", text: extractErrorMessage(err, t("mod19.err")) });
    }
  });

  const activate = () => run(async () => {
    try {
      const next = await modulesApi19.activate(code);
      setCode("");
      after(next);
      void celebrate(`modules.activated:${req?.id ?? next.activated.join(",")}`);
      setMsg({ tone: "success", text: t("mod19.activated", { names: names(next.activated) }) });
    } catch (err) {
      setMsg({ tone: "error", text: extractErrorMessage(err, t("mod19.err")) });
      load();
    }
  });

  if (!state) {
    return msg ? <Alert severity="error">{msg.text}</Alert> : <Skeleton variant="rounded" height={320} />;
  }

  const chip = (m: ModuleCard) => {
    if (m.included) return <Chip size="small" label={m.status === "active" ? t("mod19.status.included_on") : t("mod19.status.included")} sx={{ bgcolor: f.skySoft, color: f.sky }} />;
    if (m.status === "active") return <Chip size="small" label={t("mod19.status.active")} sx={{ bgcolor: f.brandSoft, color: f.brand, fontWeight: 700 }} />;
    if (m.status === "pending") return <Chip size="small" label={t("mod19.status.pending")} sx={{ bgcolor: f.sunSoft, color: f.sunInk, fontWeight: 700 }} />;
    if (draft.has(m.key)) return <Chip size="small" label={t("mod19.status.chosen")} sx={{ bgcolor: f.sunSoft, color: f.sunInk }} />;
    return <Chip size="small" label={t("mod19.status.off")} variant="outlined" />;
  };

  return (
    <Stack spacing={2}>
      {variant === "settings" && (
        <Box>
          <Typography variant="h6">{t("mod19.title")}</Typography>
          <Typography variant="body2" sx={{ color: f.muted }}>{t("mod19.intro")}</Typography>
        </Box>
      )}

      {req && (req.status === "pending" || reqExpired) && (
        <Card sx={{ p: 2.5, border: `1px solid ${reqExpired ? f.coral : f.sun}`, bgcolor: reqExpired ? f.coralSoft : f.sunSoft }}>
          <Stack spacing={1.5}>
            <Stack direction="row" spacing={1.5} alignItems="center">
              <Emoji name={reqExpired ? "hourglass" : "envelope"} size={28} />
              <Box>
                <Typography sx={{ fontWeight: 700 }}>{reqExpired ? t("mod19.expired_title") : t("mod19.waiting_title")}</Typography>
                <Typography variant="body2">{reqExpired ? t("mod19.expired_body") : t("mod19.waiting_body")}</Typography>
              </Box>
            </Stack>
            <Typography variant="body2" sx={{ color: f.muted }}>
              {t("mod19.waiting_for", { names: names(req.modules) })}
              {!reqExpired && ` · ${t("mod19.valid_until", { date: new Date(req.expires_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) })}`}
            </Typography>
            {!req.email_sent && !reqExpired && <Alert severity="warning">{t("mod19.requested_no_email")}</Alert>}
            {canManage && !reqExpired && (
              <Stack component="form" direction={{ xs: "column", sm: "row" }} spacing={1.5}
                onSubmit={(e) => { e.preventDefault(); if (code.replace("-", "").length === 8) void activate(); }}>
                <TextField label={t("mod19.code")} placeholder="ABCD-EF23" value={code} onChange={(e) => setCode(formatCode(e.target.value))}
                  autoComplete="off" inputProps={{ "aria-label": t("mod19.code"), style: { letterSpacing: 3, fontWeight: 700 } }} sx={{ minWidth: 220 }}
                  disabled={Boolean(req.locked_until)} helperText={req.locked_until ? t("mod19.locked", { time: new Date(req.locked_until).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) }) : " "} />
                <Button type="submit" variant="contained" size="large" disabled={busy || code.replace("-", "").length !== 8 || Boolean(req.locked_until)} sx={{ alignSelf: { sm: "flex-start" } }}>
                  {t("mod19.activate")}
                </Button>
              </Stack>
            )}
            {canManage && reqExpired && (
              <Button variant="contained" disabled={busy} onClick={() => void requestActivation(req.modules)} sx={{ alignSelf: "flex-start" }}>{t("mod19.request_again")}</Button>
            )}
          </Stack>
        </Card>
      )}

      {msg && <Alert severity={msg.tone} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      {!canManage && <Alert severity="info">{t("mod19.admin_only")}</Alert>}

      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)", lg: "repeat(3, 1fr)" } }}>
        {state.modules.map((m) => (
          <Card key={m.key} sx={{ p: 2.25, display: "flex", flexDirection: "column", gap: 1, opacity: isOn(m) ? 1 : 0.92,
            outline: isOn(m) ? `2px solid ${m.status === "active" ? f.brand : f.sun}` : "none" }}>
            <Stack direction="row" spacing={1.25} alignItems="flex-start">
              <Box sx={{ width: 44, height: 44, borderRadius: "14px", bgcolor: f.brandSoft, display: "grid", placeItems: "center", flexShrink: 0 }}>
                <Emoji name={m.emoji} size={26} />
              </Box>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography sx={{ fontWeight: 700, lineHeight: 1.3 }}>{name(m)}</Typography>
                <Box sx={{ mt: 0.5 }}>{chip(m)}</Box>
              </Box>
              <Switch checked={isOn(m)} disabled={!canManage || busy || m.included} onChange={(e) => toggle(m, e.target.checked)}
                inputProps={{ "aria-label": t("mod19.switch", { name: name(m) }) }} />
            </Stack>
            <Typography variant="body2">{tx(`mod19.m.${m.key}.line`, m.line)}</Typography>
            <Box>
              <Typography variant="caption" sx={{ color: f.muted, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4 }}>{t("mod19.you_get")}</Typography>
              <Box component="ul" sx={{ m: 0, pl: 2.25, color: f.ink, "& li": { fontSize: 14, lineHeight: 1.6 } }}>
                {m.gets.map((g, i) => <li key={g}>{tx(`mod19.m.${m.key}.get${i}`, g)}</li>)}
              </Box>
            </Box>
            {m.needs.length > 0 && <Typography variant="body2" sx={{ color: f.muted, mt: "auto" }}>{t("mod19.needs", { names: names(m.needs) })}</Typography>}
            {m.included && <Typography variant="body2" sx={{ color: f.muted, mt: "auto" }}>{t("mod19.included_note")}</Typography>}
          </Card>
        ))}
      </Box>

      {canManage && (
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
          <Button variant="contained" size="large" disabled={busy || draft.size === 0} onClick={() => void requestActivation([...draft])}>
            {draft.size ? t("mod19.request_n", { count: draft.size }) : t("mod19.request")}
          </Button>
          <Typography variant="body2" sx={{ color: f.muted }}>{draft.size ? t("mod19.request_hint", { names: names([...draft]) }) : t("mod19.pick_hint")}</Typography>
        </Stack>
      )}

      <Dialog open={ask !== null} onClose={() => setAsk(null)} maxWidth="xs" fullWidth>
        {ask?.kind === "needs" && (
          <>
            <DialogTitle>{t("mod19.ask_needs_title", { names: names(ask.needs) })}</DialogTitle>
            <DialogContent><Typography>{t("mod19.ask_needs_body", { name: names([ask.key]), needs: names(ask.needs) })}</Typography></DialogContent>
            <DialogActions>
              <Button onClick={() => setAsk(null)}>{t("mod19.cancel")}</Button>
              <Button variant="contained" onClick={() => { setDraft((d) => new Set([...d, ask.key, ...ask.needs])); setAsk(null); }}>{t("mod19.yes_both")}</Button>
            </DialogActions>
          </>
        )}
        {ask?.kind === "off" && (
          <>
            <DialogTitle>{t("mod19.ask_off_title", { names: names(ask.keys) })}</DialogTitle>
            <DialogContent><Typography>{t("mod19.ask_off_body")}</Typography></DialogContent>
            <DialogActions>
              <Button onClick={() => setAsk(null)}>{t("mod19.cancel")}</Button>
              <Button color="error" variant="contained" disabled={busy} onClick={() => void switchOff(ask.keys, false)}>{t("mod19.switch_off")}</Button>
            </DialogActions>
          </>
        )}
        {ask?.kind === "dependents" && (
          <>
            <DialogTitle>{t("mod19.ask_dep_title", { names: names(ask.dependents) })}</DialogTitle>
            <DialogContent><Typography>{t("mod19.ask_dep_body", { name: names(ask.keys), deps: names(ask.dependents) })}</Typography></DialogContent>
            <DialogActions>
              <Button onClick={() => setAsk(null)}>{t("mod19.cancel")}</Button>
              <Button color="error" variant="contained" disabled={busy} onClick={() => void switchOff(ask.keys, true)}>{t("mod19.switch_off_all")}</Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </Stack>
  );
}
