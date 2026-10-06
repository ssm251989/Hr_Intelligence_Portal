import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import { extractErrorMessage } from "../../api/client";
import { exitInterviewApi, type ExitReport, type ExitReportBucket } from "../../api/exitInterviewApi";
import { useT } from "../../i18n";
import { StatTile } from "../../ui-kit";

// fix 2026-10-06: Reports > Exit interviews -- reasons and ratings in totals by department, manager and
// tenure band. Never an individual's answers (HR-only endpoint; managers don't get this tab).

const pct = (b?: Record<string, number>, k = "yes") => {
  if (!b) return "—";
  const n = (b.yes ?? 0) + (b.maybe ?? 0) + (b.no ?? 0);
  return n ? `${Math.round((100 * (b[k] ?? 0)) / n)}%` : "—";
};

function GroupTable({ title, data }: { title: string; data: Record<string, ExitReportBucket> }) {
  const t = useT();
  const rows = Object.entries(data).sort((a, b) => b[1].count - a[1].count);
  return (
    <Box>
      <Typography component="h3" sx={{ fontWeight: 800, mb: 1 }}>{title}</Typography>
      {rows.length === 0 ? <Typography color="text.secondary">{t("exitq.rep.none")}</Typography> : (
        <Table size="small">
          <TableHead><TableRow>
            <TableCell>{t("exitq.rep.group")}</TableCell><TableCell align="right">{t("exitq.rep.count")}</TableCell>
            <TableCell align="right">{t("exitq.rep.rating")}</TableCell><TableCell align="right">{t("exitq.rep.recommend")}</TableCell>
            <TableCell align="right">{t("exitq.rep.return")}</TableCell><TableCell>{t("exitq.rep.reasons")}</TableCell>
          </TableRow></TableHead>
          <TableBody>
            {rows.map(([k, b]) => (
              <TableRow key={k}>
                <TableCell>{k}</TableCell><TableCell align="right">{b.count}</TableCell>
                <TableCell align="right">{b.manager_rating_avg != null ? `${b.manager_rating_avg} / 5` : "—"}</TableCell>
                <TableCell align="right">{pct(b.recommend)}</TableCell><TableCell align="right">{pct(b.return)}</TableCell>
                <TableCell sx={{ fontSize: 13 }}>{b.top_reasons.map(([r, n]) => `${r} (${n})`).join(", ") || "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Box>
  );
}

export default function ExitInterviewReportView() {
  const t = useT();
  const [data, setData] = useState<ExitReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { exitInterviewApi.report().then(setData).catch((e) => setError(extractErrorMessage(e, ""))); }, []);
  if (error) return <Alert severity="warning">{error}</Alert>;
  if (!data) return <Box sx={{ display: "grid", placeItems: "center", py: 6 }}><CircularProgress /></Box>;
  const o = data.overall;
  return (
    <Stack spacing={3} data-testid="exit-interview-report">
      <Typography color="text.secondary">{t("exitq.rep.intro")}</Typography>
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" } }}>
        <StatTile emoji="speech" label={t("exitq.rep.count")} value={o.count} tone="brand" />
        <StatTile emoji="star" label={t("exitq.rep.rating")} value={o.manager_rating_avg != null ? `${o.manager_rating_avg} / 5` : "—"} tone="sun" />
        <StatTile emoji="thumbs_up" label={t("exitq.rep.recommend")} value={pct(o.recommend)} tone="ok" />
        <StatTile emoji="door" label={t("exitq.rep.return")} value={pct(o.return)} tone="sky" />
      </Box>
      <GroupTable title={t("exitq.rep.by_department")} data={data.by_department} />
      <GroupTable title={t("exitq.rep.by_manager")} data={data.by_manager} />
      <GroupTable title={t("exitq.rep.by_tenure")} data={data.by_tenure} />
    </Stack>
  );
}
