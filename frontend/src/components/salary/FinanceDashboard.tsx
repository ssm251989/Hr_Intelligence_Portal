import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Tooltip2 from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { budgetsApi, type FinanceData } from "../../api/budgetsApi";
import { useT } from "../../i18n";
import { StatTile } from "../../ui-kit";
import { lakh } from "./SalaryPanel";

// Part 18.15: Salary > Finance -- per department allocated / reserved / committed / remaining
// (coloured bars), month trend, top roles by cost, alerts, Excel export.
export default function FinanceDashboard() {
  const t = useT();
  const theme = useTheme();
  const f = theme.palette.fresh;
  const [fy, setFy] = useState("");
  const [years, setYears] = useState<string[]>([]);
  const [data, setData] = useState<FinanceData | null>(null);

  useEffect(() => { budgetsApi.list().then((r) => { setYears(r.fiscal_years); setFy(r.fiscal_year); }).catch(() => undefined); }, []);
  useEffect(() => { if (fy) budgetsApi.dashboard(fy).then(setData).catch(() => setData(null)); }, [fy]);

  const exportXlsx = async () => {
    const blob = await budgetsApi.exportXlsx(fy);
    if (!blob) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `hiring-budgets-${fy}.xlsx`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if (!data) return null;
  const withBudget = data.departments.filter((d) => d.allocated != null);
  return (
    <Stack spacing={2.5}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
        <TextField select size="small" label={t("budget.fy")} value={fy} onChange={(e) => setFy(e.target.value)} sx={{ minWidth: 140 }}>
          {years.map((y) => <MenuItem key={y} value={y}>{y}</MenuItem>)}
        </TextField>
        <Box sx={{ flex: 1 }} />
        <Button component={RouterLink} to="/settings/hiring/budgets">{t("finance.edit_budgets")}</Button>
        <Button variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={exportXlsx}>{t("finance.export")}</Button>
      </Stack>
      {data.alerts.map((a) => (
        <Alert key={a.department} severity={a.kind === "exceeded" ? "error" : "warning"}>
          {a.kind === "exceeded" ? t("finance.alert.exceeded", { dept: a.department, amount: lakh(Math.abs(a.remaining ?? 0)) })
            : t("finance.alert.near", { dept: a.department, pct: a.used_pct ?? 0 })}
        </Alert>
      ))}
      <Grid container spacing={2}>
        {([["finance.allocated", data.totals.allocated, "bank", "sky"], ["finance.reserved", data.totals.reserved, "hourglass", "sun"],
          ["finance.committed", data.totals.committed, "handshake", "coral"], ["finance.remaining", data.totals.remaining, "money", "ok"]] as const).map(([k, v, e, tone]) => (
          <Grid key={k} size={{ xs: 6, md: 3 }}><StatTile emoji={e} value={lakh(v)} label={t(k)} tone={tone} /></Grid>
        ))}
      </Grid>
      {withBudget.length === 0 ? (
        <Alert severity="info" action={<Button component={RouterLink} to="/settings/hiring/budgets">{t("finance.set_budgets")}</Button>}>{t("finance.no_budgets")}</Alert>
      ) : (
        <Card sx={{ p: 2 }}>
          <Typography sx={{ fontWeight: 800, mb: 1.5 }}>{t("finance.by_department")}</Typography>
          <Stack spacing={1.75}>
            {withBudget.map((d) => {
              const total = d.allocated || 1;
              const pct = (x: number) => `${Math.min(100, (100 * x) / total)}%`;
              return (
                <Box key={d.department}>
                  <Stack direction="row" justifyContent="space-between">
                    <Typography sx={{ fontWeight: 700 }}>{d.department}</Typography>
                    <Typography variant="body2" sx={{ color: d.exceeded ? f.coral : f.muted, fontWeight: 700 }}>
                      {t("finance.bar_text", { used: lakh(d.reserved + d.committed), total: lakh(d.allocated), left: lakh(d.remaining) })}
                    </Typography>
                  </Stack>
                  <Tooltip2 title={`${t("finance.committed")} ${lakh(d.committed)} · ${t("finance.reserved")} ${lakh(d.reserved)} · ${t("finance.remaining")} ${lakh(d.remaining)}`}>
                    <Box sx={{ display: "flex", height: 16, borderRadius: 8, overflow: "hidden", bgcolor: f.okSoft, mt: 0.5, boxShadow: d.alert ? `0 0 0 2px ${f.sun}` : "none" }}>
                      <Box sx={{ width: pct(d.committed), bgcolor: f.coral }} />
                      <Box sx={{ width: pct(d.reserved), bgcolor: f.sun }} />
                    </Box>
                  </Tooltip2>
                </Box>
              );
            })}
          </Stack>
          <Stack direction="row" spacing={2} sx={{ mt: 1.5 }}>
            {[["finance.committed", f.coral], ["finance.reserved", f.sun], ["finance.remaining", f.okSoft]].map(([k, c]) => (
              <Stack key={k} direction="row" spacing={0.75} alignItems="center"><Box sx={{ width: 12, height: 12, borderRadius: 3, bgcolor: c }} /><Typography variant="caption">{t(k)}</Typography></Stack>
            ))}
          </Stack>
        </Card>
      )}
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Card sx={{ p: 2, height: "100%" }}>
            <Typography sx={{ fontWeight: 800, mb: 1 }}>{t("finance.trend")}</Typography>
            {data.trend.length === 0 ? <Typography variant="body2" color="text.secondary">{t("finance.none")}</Typography> : (
              <Box sx={{ height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={data.trend}>
                    <CartesianGrid strokeDasharray="3 3" stroke={f.line} />
                    <XAxis dataKey="month" stroke={f.muted} fontSize={12} />
                    <YAxis stroke={f.muted} fontSize={12} tickFormatter={(v: number) => lakh(v)} />
                    <Tooltip formatter={(v) => lakh(Number(v))} />
                    <Legend />
                    <Bar dataKey="committed" stackId="a" name={t("finance.committed")} fill={f.coral} radius={[0, 0, 4, 4]} />
                    <Bar dataKey="reserved" stackId="a" name={t("finance.reserved")} fill={f.sun} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </Box>
            )}
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 5 }}>
          <Card sx={{ p: 2, height: "100%" }}>
            <Typography sx={{ fontWeight: 800, mb: 1 }}>{t("finance.top_roles")}</Typography>
            {data.top_roles.length === 0 ? <Typography variant="body2" color="text.secondary">{t("finance.none")}</Typography> : (
              <Table size="small">
                <TableHead><TableRow><TableCell>{t("stage.col.job")}</TableCell><TableCell align="right">{t("finance.cost")}</TableCell><TableCell align="right">{t("finance.hires")}</TableCell></TableRow></TableHead>
                <TableBody>
                  {data.top_roles.map((r) => (
                    <TableRow key={`${r.job_title}-${r.department}`}>
                      <TableCell><Typography variant="body2" sx={{ fontWeight: 700 }}>{r.job_title}</Typography><Typography variant="caption">{r.department}</Typography></TableCell>
                      <TableCell align="right">{lakh(r.amount)}</TableCell>
                      <TableCell align="right">{r.hires}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Card>
        </Grid>
      </Grid>
      {/* Part 21.7: money that came back to the budgets (exits pro-rata / full, drop-outs) */}
      <Card sx={{ p: 2 }} data-testid="budget-history">
        <Typography sx={{ fontWeight: 800, mb: 1 }}>{t("budget21.history")}</Typography>
        {(data.history ?? []).length === 0 ? <Typography variant="body2" color="text.secondary">{t("budget21.history_none")}</Typography> : (
          <Stack spacing={0.75}>
            {(data.history ?? []).map((h, i) => (
              <Stack key={i} direction="row" spacing={1.5} alignItems="baseline">
                <Typography sx={{ fontWeight: 800, color: "success.main", minWidth: 90 }}>+{lakh(h.amount)}</Typography>
                <Typography variant="body2" sx={{ flex: 1 }}>{t("budget21.released")} - {h.reason ?? h.job_title} <Typography component="span" variant="caption" color="text.secondary">({h.department})</Typography></Typography>
                <Typography variant="caption" color="text.secondary">{new Date(h.on).toLocaleDateString()}</Typography>
              </Stack>
            ))}
          </Stack>
        )}
      </Card>
    </Stack>
  );
}
