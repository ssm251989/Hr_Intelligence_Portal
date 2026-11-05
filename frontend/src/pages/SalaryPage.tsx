import { useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import Link from "@mui/material/Link";
import Chip from "@mui/material/Chip";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import FormLabel from "@mui/material/FormLabel";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage, salaryApi } from "../api/client";
import { salaryQueueApi, type SalaryChip, type SalaryQueueItem } from "../api/salaryApi";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import ConfirmDialog from "../components/ConfirmDialog";
import { Figure, Inset, useMoney, useWhen } from "../components/offers/shared";
import MoneyField, { DaysField } from "../components/salary/MoneyField";
import SalaryBandBar from "../components/salary/SalaryBandBar";
import { useT } from "../i18n";
import StageTable, { type StageRow } from "../components/stage/StageTable";
import SalaryPanel, { lakh, money, reasonText } from "../components/salary/SalaryPanel";
import FinanceDashboard from "../components/salary/FinanceDashboard";
import { http } from "../api/client";
import { Emoji, InfoTip, PageHeader, StatusChip, UserAvatar, type Tone } from "../ui-kit";

// Part 17.8: the Salary page is a QUEUE. Figures come in by themselves (the apply form, the
// resume, or the candidate's own "Salary & joining details" form) and are checked against the
// job's band automatically. HR only steps in for: approve / decline above the band, send the
// form again, or correct a figure.

const CHIP_META: Record<SalaryChip, { tone: Tone; emoji: string }> = {
  waiting_for_candidate: { tone: "sky", emoji: "hourglass" },
  in_band: { tone: "ok", emoji: "check" },
  needs_approval: { tone: "sun", emoji: "writing_hand" },
  flagged: { tone: "coral", emoji: "warning" },
  approved: { tone: "ok", emoji: "thumbs_up" },
  declined: { tone: "muted", emoji: "cross" },
  no_band: { tone: "muted", emoji: "question" },
};

function SalaryChipLabel({ chip }: { chip: SalaryChip }) {
  const t = useT();
  const meta = CHIP_META[chip] ?? CHIP_META.waiting_for_candidate;
  return <StatusChip tone={meta.tone} emoji={meta.emoji} label={t(`salaryQueue.chip.${chip}`)} size="medium" />;
}

// ---------------------------------------------------------------- approve / decline

function ApprovalBox({ item, onDone }: { item: SalaryQueueItem; onDone: () => Promise<void> }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const money = useMoney();
  const { can } = useAuth();
  const canApprove = can(ROLE_MATRIX.salaryWrite);
  const start = item.check.suggestion ?? item.expected_ctc;
  const [amount, setAmount] = useState(start != null ? String(Math.round(start)) : "");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  if (!canApprove) {
    return (
      <Inset>
        <Stack direction="row" spacing={1} alignItems="center">
          <Emoji name="hourglass" size={18} />
          <Typography sx={{ fontSize: 14 }}>{t("salary.approval.waiting")}</Typography>
        </Stack>
      </Inset>
    );
  }

  const decide = async (decision: "approve" | "reject") => {
    setSaving(decision);
    setError(null);
    try {
      await salaryApi.approve(item.application_id, {
        decision,
        approved_salary: decision === "approve" && amount ? Number(amount) : null,
        notes: notes.trim() || null,
      });
      await onDone();
    } catch (err) {
      setError(extractErrorMessage(err, t("salary.error.decision")));
    } finally {
      setSaving(null);
    }
  };

  const over = item.check.over_pct;
  return (
    <Inset title={<><Emoji name="writing_hand" size={16} /> {t("salary.approval.title")}</>}>
      <Typography sx={{ fontSize: 14, color: f.muted, mb: 1.5 }}>
        {item.chip === "flagged" ? t("salaryQueue.approval.flagged_intro", { pct: over ?? 0 }) : t("salaryQueue.approval.intro", { pct: over ?? 0 })}
      </Typography>
      {error && <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert>}
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ xs: "stretch", md: "flex-start" }}>
        <Box sx={{ minWidth: 220 }}>
          <MoneyField label={t("salary.approval.amount")} value={amount} onChange={setAmount} size="small" helper={t("salaryQueue.approval.amount_hint")} />
        </Box>
        <TextField label={t("salaryQueue.approval.notes")} value={notes} onChange={(e) => setNotes(e.target.value)} size="small" sx={{ minWidth: 220, flex: 1 }} />
        <Stack direction="row" spacing={1}>
          <Button variant="contained" onClick={() => decide("approve")} disabled={saving !== null} startIcon={<Emoji name="check" size={16} />}>
            {saving === "approve" ? t("salary.approval.approving") : t("salary.approval.approve", { amount: amount ? money(Number(amount)) : "" })}
          </Button>
          <Button variant="outlined" color="error" onClick={() => setConfirmOpen(true)} disabled={saving !== null}>
            {saving === "reject" ? t("salary.approval.declining") : t("salary.approval.decline")}
          </Button>
        </Stack>
      </Stack>
      <ConfirmDialog
        open={confirmOpen}
        title={t("salary.approval.decline_title")}
        message={t("salary.approval.decline_message")}
        confirmLabel={t("salary.approval.decline")}
        cancelLabel={t("action.cancel")}
        confirming={saving === "reject"}
        onConfirm={() => {
          setConfirmOpen(false);
          void decide("reject");
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </Inset>
  );
}

// ---------------------------------------------------------------- edit figures

export function FiguresDialog({ item, onClose, onSaved }: { item: SalaryQueueItem; onClose: () => void; onSaved: () => Promise<void> }) {
  const t = useT();
  const s = (v: number | null | undefined) => (v == null ? "" : String(Math.round(v)));
  const [current, setCurrent] = useState(s(item.current_ctc));
  const [expected, setExpected] = useState(s(item.expected_ctc));
  const [notice, setNotice] = useState(item.notice_period_days == null ? "" : String(item.notice_period_days));
  const [relocate, setRelocate] = useState<"" | "yes" | "no">("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (notice !== "" && Number(notice) > 365) {
      setError(t("salaryApply.notice_too_long"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await salaryQueueApi.setFigures(item.application_id, {
        ...(current !== "" ? { current_ctc: Number(current) } : {}),
        ...(expected !== "" ? { expected_ctc: Number(expected) } : {}),
        ...(notice !== "" ? { notice_period_days: Number(notice) } : {}),
        ...(relocate !== "" ? { willing_to_relocate: relocate === "yes" } : {}),
      });
      await onSaved();
      onClose();
    } catch (err) {
      setError(extractErrorMessage(err, t("salaryQueue.error.figures")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={saving ? undefined : onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t("salaryQueue.figures.title", { name: item.candidate_name || t("salaryQueue.no_name") })}</DialogTitle>
      <DialogContent>
        <Typography sx={{ fontSize: 14, mb: 2 }} color="text.secondary">{t("salaryQueue.figures.intro")}</Typography>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <Stack spacing={2}>
          <MoneyField label={t("salaryForm.current")} value={current} onChange={setCurrent} />
          <MoneyField label={t("salaryForm.expected")} value={expected} onChange={setExpected} />
          <DaysField label={t("salaryForm.notice")} value={notice} onChange={setNotice} />
          <Box>
            <FormLabel id="fig-relocate" sx={{ fontSize: 14 }}>{t("salaryForm.relocate")}</FormLabel>
            <RadioGroup row aria-labelledby="fig-relocate" value={relocate} onChange={(e) => setRelocate(e.target.value as "yes" | "no")}>
              <FormControlLabel value="yes" control={<Radio />} label={t("salaryForm.yes")} />
              <FormControlLabel value="no" control={<Radio />} label={t("salaryForm.no")} />
            </RadioGroup>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={saving}>
          {saving ? t("salaryQueue.figures.saving") : t("salaryQueue.figures.save")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

// ---------------------------------------------------------------- one row

export function QueueCard({ item, onChanged, onEdit }: { item: SalaryQueueItem; onChanged: () => Promise<void>; onEdit: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const money = useMoney();
  const when = useWhen();
  const { can: canRole } = useAuth();
  const { can } = useMeBootstrap();
  const canEdit = can("recruitment.application.edit");
  const canConfirm = canRole(ROLE_MATRIX.salaryWrite);
  const [busy, setBusy] = useState<"send" | "check" | "confirm" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sendResult, setSendResult] = useState<{ sent: boolean; link?: string | null } | null>(null);
  const [copied, setCopied] = useState(false);

  const c = item.check ?? {};
  const name = item.candidate_name || t("salaryQueue.no_name");
  const missing = c.missing ?? [];
  const final = item.chip === "approved" || item.chip === "declined";
  const showSend = canEdit && !final && (item.chip === "waiting_for_candidate" || missing.length > 0);

  const run = async (kind: "send" | "check" | "confirm") => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "send") {
        const res = await salaryQueueApi.sendForm(item.application_id);
        setSendResult(res);
        setCopied(false);
      } else if (kind === "check") {
        await salaryQueueApi.recheck(item.application_id);
      } else {
        await salaryApi.confirm(item.application_id);
      }
      await onChanged();
    } catch (err) {
      setError(extractErrorMessage(err, kind === "send" ? t("salaryQueue.error.send") : kind === "check" ? t("salaryQueue.error.check") : t("salary.error.confirm")));
    } finally {
      setBusy(null);
    }
  };

  const copy = async (link: string) => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const formLine = item.form
    ? item.form.answered_at
      ? t("salaryQueue.form.answered", { when: when(item.form.answered_at) })
      : item.form.reminded
        ? t("salaryQueue.form.reminded", { when: when(item.form.sent_at) })
        : t("salaryQueue.form.sent", { when: when(item.form.sent_at) })
    : t("salaryQueue.form.not_sent");

  return (
    <Card sx={{ p: { xs: 2, sm: 2.5 } }}>
      <Stack direction="row" spacing={1.5} alignItems="center" justifyContent="space-between" flexWrap="wrap" useFlexGap>
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
          <UserAvatar name={name} size={42} />
          <Box sx={{ minWidth: 0 }}>
            <Link component={RouterLink} to={`/candidates/${item.application_id}`} sx={{ fontWeight: 800, fontSize: 17, color: f.ink }}>
              {name}
            </Link>
            <Typography sx={{ color: f.muted, fontSize: 13 }}>{item.job_title}</Typography>
          </Box>
        </Stack>
        <SalaryChipLabel chip={item.chip} />
      </Stack>

      <Box sx={{ mt: 2.5 }}>
        <SalaryBandBar expected={c.expected ?? item.expected_ctc} min={c.band_min} max={c.band_max} approved={item.approved_salary} suggested={c.suggestion} />
      </Box>

      <Stack direction="row" spacing={3} flexWrap="wrap" useFlexGap sx={{ mt: 1.5, pt: 1.5, borderTop: `1px solid ${f.line}` }}>
        <Figure label={t("salaryQueue.fig.current")} value={money(item.current_ctc)} tip={<InfoTip text={t("salary.fig.ctc_tip")} />} />
        <Figure label={t("salary.fig.expected")} value={money(item.expected_ctc)} />
        <Figure
          label={t("salaryQueue.fig.notice")}
          value={item.notice_period_days == null ? "—" : t("salaryQueue.fig.days", { count: item.notice_period_days })}
        />
        <Figure
          label={t("salary.fig.band")}
          value={c.band_min != null && c.band_max != null ? t("salary.fig.band_value", { min: money(c.band_min), max: money(c.band_max) }) : t("salary.fig.no_band")}
          tip={<InfoTip text={t("salary.fig.band_tip")} />}
        />
        {c.suggestion != null && (
          <Figure label={t("salaryQueue.fig.suggestion")} value={money(c.suggestion)} tip={<InfoTip text={t("salaryQueue.fig.suggestion_tip")} />} />
        )}
        {item.approved_salary != null && <Figure label={t("salary.fig.approved")} value={money(item.approved_salary)} />}
      </Stack>

      {missing.length > 0 && !final && (
        <Typography sx={{ mt: 1.5, fontSize: 14 }}>
          <Emoji name="clipboard" size={16} /> {t("salaryQueue.missing", { fields: missing.map((m) => t(`salaryQueue.field.${m}`)).join(", ") })}
        </Typography>
      )}
      {item.chip === "no_band" && (
        <Typography sx={{ mt: 1, fontSize: 14, color: f.muted }}>{t("salaryQueue.no_band_hint")}</Typography>
      )}
      {item.chip === "in_band" && (
        <Typography sx={{ mt: 1, fontSize: 14, color: f.muted }}>{t("salaryQueue.in_band_hint")}</Typography>
      )}

      {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
      {sendResult?.sent && <Alert severity="success" sx={{ mt: 1.5 }}>{t("salaryQueue.form.sent_now")}</Alert>}
      {sendResult && !sendResult.sent && sendResult.link && (
        <Alert
          severity="warning"
          sx={{ mt: 1.5, "& .MuiAlert-message": { minWidth: 0, flex: 1 } }}
          action={<Button size="small" onClick={() => copy(sendResult.link!)}>{copied ? t("salaryQueue.form.copied") : t("salaryQueue.form.copy")}</Button>}
        >
          {t("salaryQueue.form.share")}
          <Box component="code" sx={{ display: "block", mt: 0.5, fontSize: 12, wordBreak: "break-all" }}>{sendResult.link}</Box>
        </Alert>
      )}
      {sendResult && !sendResult.sent && !sendResult.link && (
        <Alert severity="warning" sx={{ mt: 1.5 }}>{t("salaryQueue.form.no_email")}</Alert>
      )}

      {item.status === "salary_above_band" && <ApprovalBox item={item} onDone={onChanged} />}

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ xs: "stretch", sm: "center" }} mt={2} flexWrap="wrap" useFlexGap>
        {showSend && (
          <Button variant={item.chip === "waiting_for_candidate" ? "contained" : "outlined"} onClick={() => run("send")} disabled={busy !== null} startIcon={<Emoji name="envelope" size={16} />}>
            {busy === "send" ? t("salaryQueue.form.sending") : item.form ? t("salaryQueue.form.send_again") : t("salaryQueue.form.send")}
          </Button>
        )}
        {item.status === "salary_ok" && canConfirm && (
          <Button variant="contained" onClick={() => run("confirm")} disabled={busy !== null} startIcon={<Emoji name="check" size={16} />}>
            {busy === "confirm" ? t("salary.confirming") : t("salary.confirm")}
          </Button>
        )}
        {canEdit && !final && (
          <Button variant="outlined" onClick={onEdit} disabled={busy !== null} startIcon={<Emoji name="pencil" size={16} />}>
            {t("salaryQueue.edit")}
          </Button>
        )}
        {!final && (
          <Button variant="text" onClick={() => run("check")} disabled={busy !== null}>
            {busy === "check" ? t("salaryQueue.checking") : t("salaryQueue.check_again")}
          </Button>
        )}
        <Typography sx={{ fontSize: 13, color: f.muted, ml: { sm: "auto" } }}>
          <Emoji name="mail" size={14} /> {formLine}
        </Typography>
      </Stack>
    </Card>
  );
}

// ---------------------------------------------------------------- page

// Part 18.14: the Salary page is ONE table of everyone at the salary stage (all jobs) -- no
// scrolling through cards. Red rows need a decision; a row opens the side panel (figures,
// why, history, approve / counter / reject). Bulk approve + export. The finance view is the
// second tab (18.15).
export default function SalaryPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") === "finance" ? "finance" : "candidates";
  const [open, setOpen] = useState<StageRow | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);

  const statusTone = (r: StageRow): "success" | "warning" | "error" | "info" | "default" =>
    r.salary_status === "needs_approval" ? "error" : r.salary_status === "countered" ? "warning" : r.salary_status === "rejected" ? "default"
      : r.salary_status === "waiting_form" ? "info" : "success";

  return (
    <Box>
      <PageHeader emoji="money" title={t("salary.title")} purpose={t("salaryQueue.purpose")} tourKey="salary" />
      <Tabs value={tab} onChange={(_e, v: string) => { const n = new URLSearchParams(searchParams); if (v === "finance") n.set("tab", v); else n.delete("tab"); setSearchParams(n, { replace: true }); }}
        sx={{ mb: 2 }}>
        <Tab value="candidates" label={t("salaryx.tab.candidates")} />
        <Tab value="finance" label={t("salaryx.tab.finance")} />
      </Tabs>
      {tab === "finance" ? <FinanceDashboard /> : (
        <>
          {bulkMsg && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setBulkMsg(null)}>{bulkMsg}</Alert>}
          <StageTable
            stage="salary"
            refreshSignal={refresh}
            onOpen={setOpen}
            rowTone={(r) => (r.salary_status === "needs_approval" ? f.coralSoft : undefined)}
            extraColumns={[
              { key: "current", label: t("salaryx.col.current"), render: (r) => money(r.current_ctc) },
              { key: "expected", label: t("salaryx.col.expected"), render: (r) => money(r.expected_salary) },
              { key: "hike", label: t("salaryx.col.hike"), sortKey: "hike", render: (r) => r.hike_pct == null ? "—" : (
                <Chip size="small" label={`${r.hike_pct}%`} color={(r.reasons ?? []).some((x) => x.code === "hike") ? "error" : "success"} variant="outlined" />) },
              { key: "band", label: t("salaryx.col.band"), render: (r) => `${lakh(r.band_min)} – ${lakh(r.band_max)}` },
              { key: "budget", label: t("salaryx.col.budget"), render: (r) => (r.budget_configured ? (
                <Typography variant="body2" sx={{ color: (r.budget_after ?? 0) < 0 ? f.coral : "inherit", fontWeight: 700 }}>{lakh(r.budget_after)}</Typography>) : "—") },
              { key: "sstatus", label: t("salaryx.col.salary_status"), render: (r) => (
                <Stack spacing={0.5} alignItems="flex-start">
                  <Chip size="small" color={statusTone(r)} label={t(`salaryx.status.${r.salary_status ?? "waiting_form"}`)} />
                  {["needs_approval", "countered"].includes(r.salary_status ?? "") && (r.reasons ?? []).map((x, i) => <Chip key={i} size="small" color="error" variant="outlined" label={reasonText(t, x)} />)}
                </Stack>) },
            ]}
            bulkActions={(sel, clear) => {
              const ready = sel.filter((r) => r.salary_status === "needs_approval" || r.salary_status === "countered");
              return ready.length > 0 ? (
                <Button size="small" variant="contained" color="success" onClick={async () => {
                  let ok = 0;
                  for (const r of ready) {
                    try { await http.post(`/api/v1/ui/salary/applications/${r.application_id}/decide`, { decision: "approve" }); ok += 1; } catch { /* reported by the count */ }
                  }
                  setBulkMsg(t("salaryx.bulk_done", { ok, total: ready.length }));
                  clear(); setRefresh((k) => k + 1);
                }}>{t("salaryx.bulk_approve", { count: ready.length })}</Button>
              ) : null;
            }}
          />
          <SalaryPanel row={open} onClose={() => setOpen(null)} onChanged={() => setRefresh((k) => k + 1)} />
        </>
      )}
    </Box>
  );
}
