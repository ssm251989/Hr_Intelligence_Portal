import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, http } from "../../api/client";
import { salaryQueueApi } from "../../api/salaryApi";
import { useT } from "../../i18n";
import type { StageRow } from "../stage/StageTable";
import StatusChip from "../StatusChip";

export const money = (v: number | null | undefined) => (v == null ? "—" : `₹${Math.round(v).toLocaleString("en-IN")}`);
export const lakh = (v: number | null | undefined) => (v == null ? "—" : `${(v / 100000).toLocaleString("en-IN", { maximumFractionDigits: 1 })} L`);

/** Part 18.14: one reason as a short red/amber chip text ("Hike 35% > 20% limit"). */
export function reasonText(t: (k: string, v?: Record<string, string | number>) => string, r: { code: string; [k: string]: unknown }): string {
  if (r.code === "hike") return t("salaryx.reason.hike", { hike: Number(r.hike_pct), limit: Number(r.limit_pct) });
  if (r.code === "above_band") return t("salaryx.reason.above_band", { pct: Number(r.over_pct) });
  if (r.code === "budget_short") return t("salaryx.reason.budget_short", { amount: lakh(Number(r.short_by)) });
  if (r.code === "no_current") return t("salaryx.reason.no_current");
  return t("salaryx.reason.no_band");
}

interface AuditRow { action: string; actor: string; created_at: string; details?: Record<string, unknown> }

// Part 18.14: side panel -- figures, why it needs a decision, history, and approve / counter / reject.
export default function SalaryPanel({ row, onClose, onChanged }: { row: StageRow | null; onClose: () => void; onChanged: () => void }) {
  const t = useT();
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [history, setHistory] = useState<AuditRow[]>([]);

  useEffect(() => {
    setMsg(null); setReason("");
    setAmount(row?.expected_salary != null ? String(Math.round(row.expected_salary)) : "");
    if (!row) return;
    http.get<{ items?: AuditRow[] } | AuditRow[]>(`/reports/audit?entity_id=${row.application_id}&limit=30`)
      .then((r) => setHistory((Array.isArray(r) ? r : r.items ?? []).filter((x) => x.action.startsWith("salary"))))
      .catch(() => setHistory([]));
  }, [row]);

  const decide = async (decision: "approve" | "counter" | "reject") => {
    if (!row) return;
    setBusy(true); setMsg(null);
    try {
      await http.post(`/api/v1/ui/salary/applications/${row.application_id}/decide`, {
        decision, amount: decision === "reject" ? null : amount ? Number(amount) : null, reason: reason || null,
      });
      setMsg({ ok: true, text: t(`salaryx.done.${decision}`) });
      onChanged();
    } catch (err) {
      setMsg({ ok: false, text: extractErrorMessage(err, t("salaryx.err")) });
    } finally { setBusy(false); }
  };
  const sendForm = async () => {
    if (!row) return;
    setBusy(true);
    try {
      const r = await salaryQueueApi.sendForm(row.application_id);
      setMsg({ ok: r.sent, text: r.sent ? t("salaryx.form_sent") : r.link ? t("salaryx.form_link", { link: r.link }) : t("salaryx.err") });
      onChanged();
    } catch (err) { setMsg({ ok: false, text: extractErrorMessage(err, t("salaryx.err")) }); } finally { setBusy(false); }
  };

  const open = row !== null;
  const canDecide = row && ["needs_approval", "countered"].includes(row.salary_status ?? "");
  return (
    <Drawer anchor="right" open={open} onClose={onClose} slotProps={{ paper: { sx: { width: { xs: "100%", sm: 440 }, p: 2.5 } } }}>
      {row && (
        <Stack spacing={2}>
          <Box>
            <Typography variant="h6">{row.name}</Typography>
            <Typography variant="body2" color="text.secondary">{row.job} · {row.department || "—"}</Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
              <StatusChip status={row.status} />
              <Chip size="small" label={t(`salaryx.status.${row.salary_status ?? "waiting_form"}`)} />
            </Stack>
          </Box>
          <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1.5 }}>
            {[["salaryx.col.current", money(row.current_ctc)], ["salaryx.col.expected", money(row.expected_salary)],
              ["salaryx.col.hike", row.hike_pct != null ? `${row.hike_pct}%` : "—"], ["salaryx.col.band", `${lakh(row.band_min)} – ${lakh(row.band_max)}`],
              ["salaryx.col.budget", row.budget_configured ? lakh(row.budget_after) : t("salaryx.no_budget")], ["salaryx.col.approved", money(row.approved_salary)],
            ].map(([k, v]) => (
              <Box key={k}><Typography variant="caption">{t(k)}</Typography><Typography sx={{ fontWeight: 700 }}>{v}</Typography></Box>
            ))}
          </Box>
          {(row.reasons ?? []).length > 0 && (
            <Alert severity="error" icon={false}>
              <Typography sx={{ fontWeight: 700, mb: 0.5 }}>{t("salaryx.why")}</Typography>
              {(row.reasons ?? []).map((r, i) => <Typography key={i} variant="body2">• {reasonText(t, r)}</Typography>)}
            </Alert>
          )}
          {row.counter != null && <Alert severity="info">{t("salaryx.countered", { amount: money(row.counter) })}</Alert>}
          {canDecide && (
            <Stack spacing={1.25}>
              <TextField size="small" type="number" label={t("salaryx.amount")} value={amount} onChange={(e) => setAmount(e.target.value)}
                helperText={amount ? money(Number(amount)) : " "} />
              <TextField size="small" label={t("salaryx.reason_note")} value={reason} onChange={(e) => setReason(e.target.value)} multiline minRows={2} />
              <Stack direction="row" spacing={1}>
                <Button variant="contained" color="success" disabled={busy} onClick={() => decide("approve")}>{t("salaryx.approve")}</Button>
                <Button variant="outlined" disabled={busy || !amount} onClick={() => decide("counter")}>{t("salaryx.counter")}</Button>
                <Button color="error" disabled={busy || !reason.trim()} onClick={() => decide("reject")}>{t("salaryx.reject")}</Button>
              </Stack>
            </Stack>
          )}
          {row.salary_status === "waiting_form" && <Button variant="outlined" disabled={busy} onClick={sendForm}>{t("salaryx.send_form")}</Button>}
          {msg && <Alert severity={msg.ok ? "success" : "warning"}>{msg.text}</Alert>}
          <Divider />
          <Typography sx={{ fontWeight: 700 }}>{t("salaryx.history")}</Typography>
          {history.length === 0 ? <Typography variant="body2" color="text.secondary">{t("salaryx.history_none")}</Typography> : history.map((h, i) => (
            <Box key={i}>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>{t(`salaryx.event.${h.action}`)}</Typography>
              <Typography variant="caption">{new Date(h.created_at).toLocaleString()} · {h.actor}</Typography>
            </Box>
          ))}
          <Button onClick={onClose}>{t("salaryx.close")}</Button>
        </Stack>
      )}
    </Drawer>
  );
}
