import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { http } from "../../api/client";
import { useT } from "../../i18n";
import { PageHeader, StatTile } from "../../ui-kit";
import EmptyState from "../../ui-kit/EmptyState";

// Part 26: HR Autopilot -- automatic agents that work without anyone asking. Shows what they did
// (with the company rule that allowed each decision), their switches and decision rules, and Run now.

type Outcome = "done" | "decided" | "proposed" | "escalated" | "skipped" | "failed";
interface AgentRow { key: string; enabled: boolean; last_7_days: Partial<Record<Outcome, number>> }
interface Overview {
  enabled: boolean; agents: AgentRow[]; rules: Record<string, number | boolean>; options: Record<string, number | boolean>;
  jobs: Record<string, { last_run?: string; ok?: boolean }>; can_configure: boolean;
}
interface Item {
  id: string; agent: string; trigger: string; event?: string | null; action: string; outcome: Outcome; rule?: string | null;
  summary: string; at?: string | null; link?: string | null; details?: { text?: string };
}

const OUTCOME_COLOR: Record<Outcome, "default" | "success" | "warning" | "info" | "error" | "primary"> = {
  done: "success", decided: "primary", proposed: "info", escalated: "warning", skipped: "default", failed: "error",
};
const NUMBER_RULES = ["shortlist_min_score", "salary_max_over_band_pct", "joining_dates_after_days"];
const RUNNABLE = ["watchdog", "sourcing", "onboarding", "exit", "briefing"];

export default function AutopilotPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [params] = useSearchParams();
  const [ov, setOv] = useState<Overview | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [agent, setAgent] = useState("");
  const [outcome, setOutcome] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [open, setOpen] = useState<Item | null>(null);

  const load = useCallback(() => {
    http.get<Overview>("/api/v1/ui/autopilot/overview").then(setOv).catch(() => setOv(null));
    const q = new URLSearchParams({ limit: "100", ...(agent ? { agent } : {}), ...(outcome ? { outcome } : {}) });
    http.get<{ items: Item[] }>(`/api/v1/ui/autopilot/activity?${q}`).then((r) => setItems(r.items)).catch(() => setItems([]));
  }, [agent, outcome]);
  useEffect(load, [load]);

  // a briefing link from the bell: /autopilot?briefing=<id>
  useEffect(() => {
    const id = params.get("briefing");
    if (id) http.get<Item>(`/api/v1/ui/autopilot/activity/${id}`).then(setOpen).catch(() => undefined);
  }, [params]);

  const save = async (key: string, value: unknown) => {
    try {
      await http.put(`/api/v1/ui/autopilot/settings/${key}`, { value });
      setMsg({ ok: true, text: t("autopilot.saved") });
      load();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message || t("autopilot.error") });
    }
  };
  const runNow = async (what: string) => {
    try {
      await http.post(`/api/v1/ui/autopilot/run/${what}`, {});
      setMsg({ ok: true, text: t("autopilot.ran", { agent: t(`autopilot.agent.${what}`) }) });
      load();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message || t("autopilot.error") });
    }
  };

  const total = (o: Outcome) => (ov?.agents ?? []).reduce((s, a) => s + (a.last_7_days[o] ?? 0), 0);
  const can = !!ov?.can_configure;

  return (
    <Box>
      <PageHeader emoji="robot" title={t("autopilot.title")} purpose={t("autopilot.purpose")}
        primary={ov && can ? (
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography sx={{ fontWeight: 600 }}>{t(ov.enabled ? "autopilot.on" : "autopilot.off")}</Typography>
            <Switch checked={ov.enabled} onChange={(e) => save("autopilot.enabled", e.target.checked)} inputProps={{ "aria-label": t("autopilot.master") }} />
          </Stack>
        ) : undefined} />
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)} sx={{ mb: 2 }}>{msg.text}</Alert>}
      {ov && !ov.enabled && <Alert severity="info" sx={{ mb: 2 }}>{t("autopilot.is_off")}</Alert>}

      <Grid container spacing={2} sx={{ mb: 2 }}>
        {(["done", "decided", "proposed", "escalated"] as Outcome[]).map((o) => (
          <Grid key={o} size={{ xs: 6, md: 3 }}><StatTile emoji={{ done: "check", decided: "magic", proposed: "inbox", escalated: "bell" }[o]} value={total(o)} label={t(`autopilot.kpi.${o}`)} /></Grid>
        ))}
      </Grid>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 5 }}>
          <Card sx={{ p: 2, mb: 2 }}>
            <Typography variant="h6" sx={{ mb: 1 }}>{t("autopilot.agents")}</Typography>
            {(ov?.agents ?? []).map((a) => (
              <Stack key={a.key} direction="row" alignItems="center" spacing={1} sx={{ py: 0.75, borderBottom: `1px solid ${f.line}` }}>
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography sx={{ fontWeight: 600 }}>{t(`autopilot.agent.${a.key}`)}</Typography>
                  <Typography variant="body2" sx={{ color: f.muted }}>{t(`autopilot.agent_help.${a.key}`)}</Typography>
                </Box>
                {can && RUNNABLE.includes(a.key) && <Button size="small" disabled={!ov?.enabled} onClick={() => runNow(a.key)}>{t("autopilot.run_now")}</Button>}
                <Switch size="small" checked={a.enabled} disabled={!can} onChange={(e) => save(`autopilot.${a.key}.enabled`, e.target.checked)}
                  inputProps={{ "aria-label": t(`autopilot.agent.${a.key}`) }} />
              </Stack>
            ))}
          </Card>
          <Card sx={{ p: 2 }}>
            <Typography variant="h6">{t("autopilot.rules")}</Typography>
            <Typography variant="body2" sx={{ color: f.muted, mb: 1 }}>{t("autopilot.rules_help")}</Typography>
            {ov && Object.entries(ov.rules).map(([key, value]) => (
              <Stack key={key} direction="row" alignItems="center" spacing={1} sx={{ py: 0.75 }}>
                <Typography variant="body2" sx={{ flex: 1 }}>{t(`autopilot.rule.${key}`)}</Typography>
                {NUMBER_RULES.includes(key) ? (
                  <TextField size="small" type="number" defaultValue={Number(value) || 0} disabled={!can} sx={{ width: 90 }}
                    onBlur={(e) => Number(e.target.value) !== Number(value) && save(`autopilot.rules.${key}`, Number(e.target.value))}
                    inputProps={{ min: 0, "aria-label": t(`autopilot.rule.${key}`) }} />
                ) : (
                  <Switch size="small" checked={!!value} disabled={!can} onChange={(e) => save(`autopilot.rules.${key}`, e.target.checked)}
                    inputProps={{ "aria-label": t(`autopilot.rule.${key}`) }} />
                )}
              </Stack>
            ))}
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 7 }}>
          <Card sx={{ p: 2 }}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} sx={{ mb: 1 }}>
              <Typography variant="h6" sx={{ flex: 1 }}>{t("autopilot.activity")}</Typography>
              <TextField select size="small" label={t("autopilot.filter_agent")} value={agent} onChange={(e) => setAgent(e.target.value)} sx={{ minWidth: 150 }}>
                <MenuItem value="">{t("autopilot.all")}</MenuItem>
                {(ov?.agents ?? []).map((a) => <MenuItem key={a.key} value={a.key}>{t(`autopilot.agent.${a.key}`)}</MenuItem>)}
              </TextField>
              <TextField select size="small" label={t("autopilot.filter_outcome")} value={outcome} onChange={(e) => setOutcome(e.target.value)} sx={{ minWidth: 150 }}>
                <MenuItem value="">{t("autopilot.all")}</MenuItem>
                {(Object.keys(OUTCOME_COLOR) as Outcome[]).map((o) => <MenuItem key={o} value={o}>{t(`autopilot.outcome.${o}`)}</MenuItem>)}
              </TextField>
            </Stack>
            {items.length === 0 ? (
              <EmptyState compact title={t("autopilot.empty")} hint={t("autopilot.empty_hint")} />
            ) : items.map((it) => (
              <Stack key={it.id} direction="row" spacing={1.5} sx={{ py: 1, borderBottom: `1px solid ${f.line}` }}>
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.25, flexWrap: "wrap" }}>
                    <Chip size="small" color={OUTCOME_COLOR[it.outcome]} label={t(`autopilot.outcome.${it.outcome}`)} />
                    <Typography variant="caption" sx={{ color: f.muted }}>
                      {t(`autopilot.agent.${it.agent}`)} · {t(`autopilot.trigger.${it.trigger}`)} · {it.at ? new Date(it.at).toLocaleString() : ""}
                    </Typography>
                  </Stack>
                  <Typography variant="body2">{it.summary}</Typography>
                  {it.rule && <Typography variant="caption" sx={{ color: f.muted }}>{t("autopilot.by_rule", { rule: t(`autopilot.rule.${it.rule.replace("autopilot.rules.", "")}`) })}</Typography>}
                </Box>
                <Stack spacing={0.5} alignItems="flex-end">
                  {it.agent === "briefing" && <Button size="small" onClick={() => http.get<Item>(`/api/v1/ui/autopilot/activity/${it.id}`).then(setOpen)}>{t("autopilot.read")}</Button>}
                  {it.link && <Button size="small" component={RouterLink} to={it.link}>{t("autopilot.open")}</Button>}
                </Stack>
              </Stack>
            ))}
          </Card>
        </Grid>
      </Grid>

      <Dialog open={!!open} onClose={() => setOpen(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{t("autopilot.briefing_title")}</DialogTitle>
        <DialogContent><Typography sx={{ whiteSpace: "pre-wrap" }}>{open?.details?.text ?? open?.summary}</Typography></DialogContent>
      </Dialog>
    </Box>
  );
}
