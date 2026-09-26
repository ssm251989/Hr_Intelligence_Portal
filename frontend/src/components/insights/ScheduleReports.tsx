import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { insightsApi, REPORT_TEMPLATE_KEY, type ReportScheduleRow } from "../../api/insightsApi";
import { useT, type TFunction } from "../../i18n";
import { EmptyState, FriendlyError, StatusChip } from "../../ui-kit";
import { InsightCard, useLoaded } from "./InsightCard";

// Part 15.6 R2: scheduled reports -- "email this report every Monday at 9 am to ...".

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DAYS = [0, 1, 2, 3, 4, 5, 6];

function hourLabel(h: number) {
  const d = new Date();
  d.setHours(h, 0, 0, 0);
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function describeSchedule(t: TFunction, s: Pick<ReportScheduleRow, "frequency" | "hour" | "day_of_week" | "day_of_month">): string {
  const at = hourLabel(s.hour);
  if (s.frequency === "weekly") return t("builder.sched.every_week", { day: t(`builder.day.${s.day_of_week ?? 0}`), time: at });
  if (s.frequency === "monthly") return t("builder.sched.every_month", { day: s.day_of_month ?? 1, time: at });
  return t("builder.sched.every_day", { time: at });
}

export default function ScheduleReports({ reports, canSchedule }: { reports: { id: string; name: string }[]; canSchedule: boolean }) {
  const t = useT();
  const [list, reload] = useLoaded(insightsApi.schedules);
  const [form, setForm] = useState({ report: "", frequency: "weekly" as "daily" | "weekly" | "monthly", day_of_week: 0, day_of_month: 1, hour: 9, recipients: "", format: "xlsx" as "csv" | "xlsx" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const emails = form.recipients.split(/[,;\s]+/).map((e) => e.trim()).filter(Boolean);
  const badEmail = emails.find((e) => !EMAIL.test(e));
  const reportId = form.report || reports[0]?.id || "";

  const submit = () => {
    if (!reportId || !emails.length || badEmail) return;
    setBusy(true);
    setError(null);
    insightsApi
      .createSchedule(reportId, {
        frequency: form.frequency, hour: form.hour, recipients: emails, template_key: REPORT_TEMPLATE_KEY, format: form.format,
        day_of_week: form.frequency === "weekly" ? form.day_of_week : undefined, day_of_month: form.frequency === "monthly" ? form.day_of_month : undefined,
      })
      .then((r) => {
        setSaved(r.next_run_at);
        setForm((f) => ({ ...f, recipients: "" }));
        reload();
      })
      .catch(setError)
      .finally(() => setBusy(false));
  };

  return (
    <InsightCard emoji="alarm_clock" title={t("builder.sched.title")} sub={t("builder.sched.sub")} dataTour="builder-schedule">
      {!canSchedule || reports.length === 0 ? (
        <Typography sx={{ color: "text.secondary", mb: 2 }}>{reports.length === 0 ? t("builder.sched.save_first") : t("builder.sched.no_access")}</Typography>
      ) : (
        <Box component="form" onSubmit={(e) => { e.preventDefault(); submit(); }} sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(6, minmax(0, 1fr))" }, mb: 2 }}>
          <TextField select label={t("builder.sched.report")} value={reportId} onChange={(e) => setForm({ ...form, report: e.target.value })} sx={{ gridColumn: { md: "span 2" } }}>
            {reports.map((r) => <MenuItem key={r.id} value={r.id}>{r.name}</MenuItem>)}
          </TextField>
          <TextField select label={t("builder.sched.how_often")} value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value as typeof form.frequency })}>
            {(["daily", "weekly", "monthly"] as const).map((f) => <MenuItem key={f} value={f}>{t(`builder.sched.${f}`)}</MenuItem>)}
          </TextField>
          {form.frequency === "weekly" && (
            <TextField select label={t("builder.sched.on_day")} value={form.day_of_week} onChange={(e) => setForm({ ...form, day_of_week: Number(e.target.value) })}>
              {DAYS.map((d) => <MenuItem key={d} value={d}>{t(`builder.day.${d}`)}</MenuItem>)}
            </TextField>
          )}
          {form.frequency === "monthly" && (
            <TextField type="number" label={t("builder.sched.on_date")} value={form.day_of_month} placeholder="1"
              slotProps={{ htmlInput: { min: 1, max: 28 } }} helperText={t("builder.sched.on_date_hint")}
              onChange={(e) => setForm({ ...form, day_of_month: Math.min(28, Math.max(1, Number(e.target.value) || 1)) })} />
          )}
          <TextField select label={t("builder.sched.at")} value={form.hour} onChange={(e) => setForm({ ...form, hour: Number(e.target.value) })}>
            {Array.from({ length: 24 }, (_, h) => <MenuItem key={h} value={h}>{hourLabel(h)}</MenuItem>)}
          </TextField>
          <TextField select label={t("builder.sched.file")} value={form.format} onChange={(e) => setForm({ ...form, format: e.target.value as "csv" | "xlsx" })}>
            <MenuItem value="xlsx">{t("builder.export.excel")}</MenuItem>
            <MenuItem value="csv">{t("builder.export.csv")}</MenuItem>
          </TextField>
          <TextField label={t("builder.sched.recipients")} value={form.recipients} onChange={(e) => setForm({ ...form, recipients: e.target.value })}
            placeholder="priya@yourcompany.com, hr-team@yourcompany.com" error={Boolean(badEmail)}
            helperText={badEmail ? t("builder.sched.bad_email", { email: badEmail }) : t("builder.sched.recipients_hint")} sx={{ gridColumn: { md: "span 4" } }} />
          <Box sx={{ gridColumn: { md: "span 2" }, display: "flex", alignItems: "flex-start" }}>
            <Button type="submit" variant="contained" disabled={busy || !emails.length || Boolean(badEmail)} fullWidth sx={{ mt: 0.5 }}>
              {busy ? t("builder.sched.saving") : t("builder.sched.save")}
            </Button>
          </Box>
          <Typography variant="caption" color="text.secondary" sx={{ gridColumn: "1 / -1" }}>
            {describeSchedule(t, { frequency: form.frequency, hour: form.hour, day_of_week: form.day_of_week, day_of_month: form.day_of_month })}
            {saved ? ` · ${t("builder.sched.saved", { when: new Date(saved).toLocaleString() })}` : ""}
          </Typography>
          {error !== null && <Box sx={{ gridColumn: "1 / -1" }}><FriendlyError error={error} compact /></Box>}
        </Box>
      )}

      {list.state === "error" && <FriendlyError error={list.error} onRetry={reload} compact />}
      {list.state === "ok" && list.data.length === 0 && <EmptyState compact illustration="calendar" title={t("builder.sched.none")} />}
      {list.state === "ok" && list.data.length > 0 && (
        <Box sx={{ overflowX: "auto" }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("builder.sched.report")}</TableCell>
                <TableCell>{t("builder.sched.when")}</TableCell>
                <TableCell>{t("builder.sched.recipients")}</TableCell>
                <TableCell>{t("builder.sched.next")}</TableCell>
                <TableCell>{t("builder.sched.status")}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {list.data.map((s) => (
                <TableRow key={s.id}>
                  <TableCell sx={{ fontWeight: 700 }}>{s.report_name}</TableCell>
                  <TableCell>{describeSchedule(t, s)}</TableCell>
                  <TableCell>{t("builder.sched.people", { count: s.recipients.length })}<Typography variant="caption" display="block" color="text.secondary">{s.recipients.join(", ")}</Typography></TableCell>
                  <TableCell>{s.next_run_at ? new Date(s.next_run_at).toLocaleString() : "—"}</TableCell>
                  <TableCell>{s.enabled ? <StatusChip status="active" /> : <StatusChip status="on_hold" />}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </InsightCard>
  );
}
