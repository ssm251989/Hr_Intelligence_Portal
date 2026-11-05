import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useT } from "../../i18n";
import { StatusChip, statusStyle, useReducedMotion } from "../../ui-kit";
import ExportBar from "./ExportBar";
import { downloadCsv, fileSlug } from "./reportExport";

export interface StatusCount {
  status: string;
  count: number;
}

export function useStatusLabel(): (status: string) => string {
  const t = useT();
  return (status) => {
    const key = `status.${status}`;
    const translated = t(key);
    return translated !== key ? translated : statusStyle(status).label;
  };
}

// Part 15.4 Reports: "where applications are" as a brand-coloured bar chart (R3: the
// series colour is theme.palette.chart[0], contrast-checked against cards) + the same
// figures as a table with status chips, so the numbers never depend on the chart alone.
export default function StatusBreakdown({ total, byStatus, exportName }: { total: number; byStatus: StatusCount[]; exportName: string }) {
  const theme = useTheme();
  const f = theme.palette.fresh;
  const series = theme.palette.chart[0] ?? f.brand;
  const t = useT();
  const label = useStatusLabel();
  const reduced = useReducedMotion();
  const pct = (n: number) => (total > 0 ? Math.round((n / total) * 100) : 0);
  const data = byStatus.map((r) => ({ name: label(r.status), count: r.count }));
  const chartHeight = Math.max(160, data.length * 34 + 40);

  const exportCsv = () =>
    downloadCsv(fileSlug(exportName), [t("reports.col.stage"), t("reports.col.count"), t("reports.col.share")], byStatus.map((r) => [label(r.status), r.count, `${pct(r.count)}%`]));

  return (
    <Stack spacing={2}>
      <Card variant="outlined" sx={{ p: 2, boxShadow: "none" }}>
        <Typography component="h3" sx={{ fontWeight: 700, mb: 1 }}>{t("reports.chart.where_title")}</Typography>
        <Box role="img" aria-label={t("reports.chart.where_aria", { count: total })} sx={{ width: "100%", height: chartHeight }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
              <CartesianGrid horizontal={false} stroke={f.line} />
              <XAxis type="number" allowDecimals={false} tick={{ fill: f.muted, fontSize: 12 }} stroke={f.line} />
              <YAxis type="category" dataKey="name" width={150} tick={{ fill: f.ink, fontSize: 12 }} stroke={f.line} />
              <Tooltip
                cursor={{ fill: f.surface2 }}
                contentStyle={{ background: f.surface, border: `1px solid ${f.line}`, borderRadius: 10, color: f.ink }}
                formatter={(value) => [t("count.candidates", { count: Number(value) }), ""]}
              />
              <Bar dataKey="count" fill={series} radius={[0, 6, 6, 0]} isAnimationActive={!reduced} />
            </BarChart>
          </ResponsiveContainer>
        </Box>
      </Card>

      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t("reports.col.stage")}</TableCell>
              <TableCell align="right">{t("reports.col.count")}</TableCell>
              <TableCell>{t("reports.col.share")}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {byStatus.map((row) => (
              <TableRow key={row.status}>
                <TableCell><StatusChip status={row.status} /></TableCell>
                <TableCell align="right" sx={{ fontVariantNumeric: "tabular-nums", fontWeight: 700 }}>{row.count.toLocaleString()}</TableCell>
                <TableCell sx={{ width: "40%" }}>
                  <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                    <Box sx={{ flex: 1, height: 8, borderRadius: 4, bgcolor: f.line, overflow: "hidden" }}>
                      <Box sx={{ height: "100%", borderRadius: 4, bgcolor: series, width: `${pct(row.count)}%`, minWidth: row.count > 0 ? 4 : 0 }} />
                    </Box>
                    <Typography variant="caption" sx={{ color: f.muted, minWidth: 36, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{pct(row.count)}%</Typography>
                  </Box>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <ExportBar onCsv={exportCsv} disabled={byStatus.length === 0} />
    </Stack>
  );
}
