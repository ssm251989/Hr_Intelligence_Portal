import { useCallback, useEffect, useState } from "react";
import BudgetReleaseSettings from "./BudgetReleaseSettings";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
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

import { extractErrorMessage } from "../../api/client";
import { budgetsApi, type DeptBudget } from "../../api/budgetsApi";
import { useT } from "../../i18n";
import { lakh } from "./SalaryPanel";

type Draft = { allocated: string; alert_pct: string; on_exceed: string; q1: string; q2: string; q3: string; q4: string };

// Part 18.15: Settings > Hiring > Department budgets -- one row per department for the chosen
// financial year: allocated amount, optional quarter split, alert %, and what happens when a
// hire would go over (needs approval / block). Used by the salary auto-decision (18.13).
export default function BudgetsSettingsPage() {
  const t = useT();
  const [fy, setFy] = useState<string>("");
  const [data, setData] = useState<{ fiscal_year: string; fiscal_years: string[]; departments: DeptBudget[]; can_edit: boolean } | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [newDept, setNewDept] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    budgetsApi.list(fy || undefined).then((r) => {
      setData(r);
      if (!fy) setFy(r.fiscal_year);
      const d: Record<string, Draft> = {};
      r.departments.forEach((b) => {
        const q = b.quarters ?? {};
        d[b.department] = { allocated: b.allocated != null ? String(b.allocated) : "", alert_pct: String(b.alert_pct), on_exceed: b.on_exceed,
          q1: q.Q1 != null ? String(q.Q1) : "", q2: q.Q2 != null ? String(q.Q2) : "", q3: q.Q3 != null ? String(q.Q3) : "", q4: q.Q4 != null ? String(q.Q4) : "" };
      });
      setDrafts(d);
    }).catch((err) => setMsg({ ok: false, text: extractErrorMessage(err, t("budget.err")) }));
  }, [fy, t]);
  useEffect(load, [load]);

  const set = (dept: string, key: keyof Draft, v: string) => setDrafts((d) => ({ ...d, [dept]: { ...(d[dept] ?? { allocated: "", alert_pct: "80", on_exceed: "needs_approval", q1: "", q2: "", q3: "", q4: "" }), [key]: v } }));
  const save = async (dept: string) => {
    const d = drafts[dept];
    if (!d?.allocated) return;
    const quarters = [d.q1, d.q2, d.q3, d.q4].some(Boolean) ? { Q1: Number(d.q1 || 0), Q2: Number(d.q2 || 0), Q3: Number(d.q3 || 0), Q4: Number(d.q4 || 0) } : null;
    try {
      await budgetsApi.save({ department: dept, fiscal_year: fy, allocated: Number(d.allocated), quarters, alert_pct: Number(d.alert_pct || 80), on_exceed: d.on_exceed });
      setMsg({ ok: true, text: t("budget.saved", { dept }) });
      load();
    } catch (err) { setMsg({ ok: false, text: extractErrorMessage(err, t("budget.err")) }); }
  };

  if (!data) return msg ? <Alert severity="error">{msg.text}</Alert> : null;
  const rows = [...data.departments.map((b) => b.department), ...(newDept && !data.departments.some((b) => b.department === newDept) ? [newDept] : [])];
  return (
    <Card>
      <CardContent>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }} justifyContent="space-between" mb={1.5}>
          <Typography variant="body2" color="text.secondary" sx={{ maxWidth: "70ch" }}>{t("budget.intro")}</Typography>
          <TextField select size="small" label={t("budget.fy")} value={fy} onChange={(e) => setFy(e.target.value)} sx={{ minWidth: 140 }}>
            {Array.from(new Set([...data.fiscal_years, data.fiscal_year, nextFy(data.fiscal_year)])).map((y) => <MenuItem key={y} value={y}>{y}</MenuItem>)}
          </TextField>
        </Stack>
        {msg && <Alert severity={msg.ok ? "success" : "error"} sx={{ mb: 1.5 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}
        <BudgetReleaseSettings />
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t("budget.col.department")}</TableCell>
                <TableCell>{t("budget.col.allocated")}</TableCell>
                <TableCell>{t("budget.col.quarters")}</TableCell>
                <TableCell>{t("budget.col.alert")}</TableCell>
                <TableCell>{t("budget.col.exceed")}</TableCell>
                <TableCell>{t("budget.col.used")}</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((dept) => {
                const b = data.departments.find((x) => x.department === dept);
                const d = drafts[dept] ?? { allocated: "", alert_pct: "80", on_exceed: "needs_approval", q1: "", q2: "", q3: "", q4: "" };
                return (
                  <TableRow key={dept}>
                    <TableCell sx={{ fontWeight: 700 }}>{dept}</TableCell>
                    <TableCell>
                      <TextField size="small" type="number" value={d.allocated} onChange={(e) => set(dept, "allocated", e.target.value)} disabled={!data.can_edit}
                        placeholder="5000000" helperText={d.allocated ? lakh(Number(d.allocated)) : " "} sx={{ width: 150 }} />
                    </TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.5}>
                        {(["q1", "q2", "q3", "q4"] as const).map((q) => (
                          <TextField key={q} size="small" type="number" label={q.toUpperCase()} value={d[q]} onChange={(e) => set(dept, q, e.target.value)} disabled={!data.can_edit} sx={{ width: 90 }} />
                        ))}
                      </Stack>
                    </TableCell>
                    <TableCell>
                      <TextField size="small" type="number" value={d.alert_pct} onChange={(e) => set(dept, "alert_pct", e.target.value)} disabled={!data.can_edit}
                        slotProps={{ htmlInput: { min: 1, max: 100 } }} sx={{ width: 80 }} />
                    </TableCell>
                    <TableCell>
                      <TextField select size="small" value={d.on_exceed} onChange={(e) => set(dept, "on_exceed", e.target.value)} disabled={!data.can_edit} sx={{ minWidth: 160 }}>
                        <MenuItem value="needs_approval">{t("budget.exceed.needs_approval")}</MenuItem>
                        <MenuItem value="block">{t("budget.exceed.block")}</MenuItem>
                      </TextField>
                    </TableCell>
                    <TableCell>{b && b.allocated != null ? `${lakh(b.reserved + b.committed)} (${b.used_pct ?? 0}%)` : "—"}</TableCell>
                    <TableCell align="right">
                      {data.can_edit && <Button size="small" variant="contained" disabled={!d.allocated} onClick={() => save(dept)}>{t("lock.save")}</Button>}
                      {data.can_edit && b?.id && <Button size="small" color="error" onClick={async () => { await budgetsApi.remove(b.id!); load(); }}>{t("budget.clear")}</Button>}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
        {data.can_edit && (
          <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
            <TextField size="small" label={t("budget.add_dept")} value={newDept} onChange={(e) => setNewDept(e.target.value)} />
          </Stack>
        )}
      </CardContent>
    </Card>
  );
}

function nextFy(fy: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(fy);
  if (!m) return fy;
  const y = Number(m[1]) + 1;
  return `${y}-${String(y + 1).slice(-2)}`;
}
