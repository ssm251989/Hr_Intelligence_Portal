import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Grid from "@mui/material/Grid";

import { onboardingExtraApi, type DropoutReport } from "../../api/onboardingExtra";
import { useT } from "../../i18n";
import { StatTile } from "../../ui-kit";

// Fix 2026-10-05: offer dropouts, no-shows, early leavers (within 90 days of joining) and absconding,
// counted by job, department, recruiter and reason (backend joiner_actions.dropout_report).

type Dim = "by_job" | "by_department" | "by_recruiter" | "by_reason";
const DIMS: { key: Dim; labelKey: string }[] = [
  { key: "by_job", labelKey: "joinerx.report.by_job" }, { key: "by_department", labelKey: "joinerx.report.by_department" },
  { key: "by_recruiter", labelKey: "joinerx.report.by_recruiter" }, { key: "by_reason", labelKey: "joinerx.report.by_reason" },
];
const PERIODS = [{ days: 30, labelKey: "joinerx.report.p30" }, { days: 90, labelKey: "joinerx.report.p90" }, { days: 365, labelKey: "joinerx.report.p365" },
  { days: 0, labelKey: "joinerx.report.all" }];
const CAT: { key: "offer_dropout" | "no_show" | "early_leaver" | "absconding"; labelKey: string; emoji: string; tone: "coral" | "sun" | "sky" | "muted" }[] = [
  { key: "offer_dropout", labelKey: "joinerx.report.offer_dropout", emoji: "envelope", tone: "sun" },
  { key: "no_show", labelKey: "joinerx.report.no_show", emoji: "pause", tone: "coral" },
  { key: "early_leaver", labelKey: "joinerx.report.early_leaver", emoji: "door", tone: "sky" },
  { key: "absconding", labelKey: "joinerx.report.absconding", emoji: "warning", tone: "coral" },
];

export default function DropoutReportView() {
  const t = useT();
  const [days, setDays] = useState(365);
  const [dim, setDim] = useState<Dim>("by_job");
  const [data, setData] = useState<DropoutReport | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setData(null); setFailed(false);
    const since = days ? new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10) : undefined;
    onboardingExtraApi.dropoutReport(since).then(setData).catch(() => setFailed(true));
  }, [days]);

  return (
    <Stack spacing={2.5}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
        <TextField select size="small" label={t("joinerx.report.period")} value={days} onChange={(e) => setDays(Number(e.target.value))} sx={{ minWidth: 180 }}>
          {PERIODS.map((p) => <MenuItem key={p.days} value={p.days}>{t(p.labelKey)}</MenuItem>)}
        </TextField>
        <TextField select size="small" label={t("joinerx.report.group")} value={dim} onChange={(e) => setDim(e.target.value as Dim)} sx={{ minWidth: 180 }}>
          {DIMS.map((d) => <MenuItem key={d.key} value={d.key}>{t(d.labelKey)}</MenuItem>)}
        </TextField>
      </Stack>
      {failed && <Alert severity="warning">{t("joinerx.report.failed")}</Alert>}
      {!data && !failed && <Box sx={{ display: "grid", placeItems: "center", py: 4 }}><CircularProgress /></Box>}
      {data && (
        <>
          <Grid container spacing={2}>
            {CAT.map((c) => (
              <Grid key={c.key} size={{ xs: 6, md: 3 }}>
                <StatTile emoji={c.emoji} value={data.totals[c.key]} label={t(c.labelKey)} tone={c.tone} />
              </Grid>
            ))}
          </Grid>
          <Typography sx={{ fontSize: 13 }} color="text.secondary">{t("joinerx.report.note", { days: data.early_days })}</Typography>
          {data[dim].length === 0 ? (
            <Typography color="text.secondary">{t("joinerx.report.none")}</Typography>
          ) : (
            <TableContainer sx={{ border: 1, borderColor: "divider", borderRadius: 2 }}>
              <Table size="small" aria-label={t("joinerx.report.tab")}>
                <TableHead>
                  <TableRow>
                    <TableCell>{t(DIMS.find((d) => d.key === dim)!.labelKey)}</TableCell>
                    {CAT.map((c) => <TableCell key={c.key} align="right">{t(c.labelKey)}</TableCell>)}
                    <TableCell align="right">{t("joinerx.report.total")}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {data[dim].map((r) => (
                    <TableRow key={r.key}>
                      <TableCell>{r.key}</TableCell>
                      {CAT.map((c) => <TableCell key={c.key} align="right">{r[c.key] || "—"}</TableCell>)}
                      <TableCell align="right" sx={{ fontWeight: 700 }}>{r.total}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </>
      )}
    </Stack>
  );
}
