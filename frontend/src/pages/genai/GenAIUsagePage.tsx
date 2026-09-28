import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Grid from "@mui/material/Grid";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { http } from "../../api/client";
import { useT } from "../../i18n";
import { PageHeader, StatTile } from "../../ui-kit";

interface Row { key: string; label: string; requests: number; errors: number; tokens_in: number; tokens_out: number; tokens: number; cost: number }
interface Usage {
  currency: string; total: Row & { tokens: number }; by_module: Row[]; by_feature: Row[]; by_user: Row[]; by_model: Row[]; by_day: Row[];
  top_candidates: Row[]; avg_cost_per_candidate: number; priced: boolean;
  limits: { scope: string; key: string; limit: number; used: number; pct: number; mode: string }[];
}
type Period = "day" | "week" | "month" | "quarter";

// Part 18.24: GenAI usage -- like the Claude usage page: tokens in/out, cost, requests, errors,
// by module / feature / person / model / day, top consumers, cost per candidate, export.
export default function GenAIUsagePage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [period, setPeriod] = useState<Period>("month");
  const [data, setData] = useState<Usage | null>(null);
  const [view, setView] = useState<"by_module" | "by_feature" | "by_user" | "by_model">("by_module");

  useEffect(() => { http.get<Usage>(`/api/v1/ui/genai/usage?period=${period}`).then(setData).catch(() => setData(null)); }, [period]);
  const money = (v: number) => `${data?.currency ?? ""} ${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  const exportCsv = async () => {
    const blob = await http.fetchBlob(`/api/v1/ui/genai/usage/export?period=${period}`);
    if (!blob) return;
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "genai-usage.csv"; a.click(); URL.revokeObjectURL(a.href);
  };

  return (
    <Box>
      <PageHeader emoji="robot" title={t("usage.title")} purpose={t("usage.purpose")}
        extra={<Stack direction="row" spacing={1}>
          <Button component={RouterLink} to="/settings/integrations/ai">{t("usage.settings")}</Button>
          <Button variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={exportCsv}>{t("usage.export")}</Button>
        </Stack>} />
      <Tabs value={period} onChange={(_e, v: Period) => setPeriod(v)} sx={{ mb: 2 }}>
        {(["day", "week", "month", "quarter"] as Period[]).map((p) => <Tab key={p} value={p} label={t(`usage.period.${p}`)} />)}
      </Tabs>
      {!data ? null : (
        <Stack spacing={2.5}>
          {!data.priced && <Alert severity="info" action={<Button component={RouterLink} to="/settings/integrations/ai">{t("usage.set_prices")}</Button>}>{t("usage.no_prices")}</Alert>}
          {data.limits.filter((l) => l.pct >= 80).map((l) => (
            <Alert key={`${l.scope}-${l.key}`} severity={l.pct >= 100 ? "error" : "warning"}>{t("genai.limit_line", { what: l.scope === "company" ? t("genai.company") : l.key, used: l.used.toLocaleString(), limit: l.limit.toLocaleString(), pct: l.pct })}</Alert>
          ))}
          <Grid container spacing={2}>
            {([["usage.tokens_in", data.total.tokens_in.toLocaleString(), "sparkles", "sky"], ["usage.tokens_out", data.total.tokens_out.toLocaleString(), "writing_hand", "brand"],
              ["usage.cost", money(data.total.cost), "money", "sun"], ["usage.requests", data.total.requests.toLocaleString(), "robot", "ok"],
              ["usage.errors", data.total.errors.toLocaleString(), "warning", "coral"]] as const).map(([k, v, e, tone]) => (
              <Grid key={k} size={{ xs: 6, md: 2.4 }}><StatTile emoji={e} value={v} label={t(k)} tone={tone} /></Grid>
            ))}
          </Grid>
          <Card sx={{ p: 2 }}>
            <Typography sx={{ fontWeight: 800, mb: 1 }}>{t("usage.by_day")}</Typography>
            {data.by_day.length === 0 ? <Typography variant="body2" color="text.secondary">{t("usage.none")}</Typography> : (
              <Box sx={{ height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={data.by_day}>
                    <CartesianGrid strokeDasharray="3 3" stroke={f.line} />
                    <XAxis dataKey="key" stroke={f.muted} fontSize={12} />
                    <YAxis stroke={f.muted} fontSize={12} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="tokens_in" stackId="a" name={t("usage.tokens_in")} fill={f.sky} />
                    <Bar dataKey="tokens_out" stackId="a" name={t("usage.tokens_out")} fill={f.violet} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </Box>
            )}
          </Card>
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, md: 7 }}>
              <Card sx={{ p: 2 }}>
                <Tabs value={view} onChange={(_e, v) => setView(v)} sx={{ mb: 1 }}>
                  {(["by_module", "by_feature", "by_user", "by_model"] as const).map((v) => <Tab key={v} value={v} label={t(`usage.${v}`)} />)}
                </Tabs>
                <Table size="small">
                  <TableHead><TableRow><TableCell />
                    <TableCell align="right">{t("usage.requests")}</TableCell><TableCell align="right">{t("usage.tokens")}</TableCell>
                    <TableCell align="right">{t("usage.cost")}</TableCell><TableCell align="right">{t("usage.errors")}</TableCell></TableRow></TableHead>
                  <TableBody>
                    {data[view].map((r) => {
                      const share = data.total.tokens ? (100 * r.tokens) / data.total.tokens : 0;
                      return (
                        <TableRow key={r.key}>
                          <TableCell sx={{ minWidth: 180 }}>
                            <Typography variant="body2" sx={{ fontWeight: 700 }}>{r.label}</Typography>
                            <LinearProgress variant="determinate" value={share} sx={{ height: 6, mt: 0.5 }} />
                          </TableCell>
                          <TableCell align="right">{r.requests}</TableCell>
                          <TableCell align="right">{r.tokens.toLocaleString()}</TableCell>
                          <TableCell align="right">{money(r.cost)}</TableCell>
                          <TableCell align="right">{r.errors}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </Card>
            </Grid>
            <Grid size={{ xs: 12, md: 5 }}>
              <Card sx={{ p: 2 }}>
                <Typography sx={{ fontWeight: 800 }}>{t("usage.per_candidate")}</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{t("usage.avg", { cost: money(data.avg_cost_per_candidate) })}</Typography>
                {data.top_candidates.length === 0 ? <Typography variant="body2" color="text.secondary">{t("usage.none")}</Typography> : (
                  <Table size="small"><TableBody>
                    {data.top_candidates.map((c) => (
                      <TableRow key={c.key}><TableCell>{c.label}</TableCell><TableCell align="right">{c.tokens.toLocaleString()}</TableCell><TableCell align="right">{money(c.cost)}</TableCell></TableRow>
                    ))}
                  </TableBody></Table>
                )}
              </Card>
            </Grid>
          </Grid>
        </Stack>
      )}
    </Box>
  );
}
