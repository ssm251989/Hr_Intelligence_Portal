import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import InputAdornment from "@mui/material/InputAdornment";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import FormLabel from "@mui/material/FormLabel";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage, jobsApi, salaryApi } from "../api/client";
import { SALARY_CHIPS, salaryQueueApi, type SalaryChip, type SalaryQueue, type SalaryQueueItem } from "../api/salaryApi";
import type { JobRoleRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import ConfirmDialog from "../components/ConfirmDialog";
import RefreshButton from "../components/RefreshButton";
import { Figure, Inset, useMoney, useWhen } from "../components/offers/shared";
import MoneyField, { DaysField } from "../components/salary/MoneyField";
import SalaryBandBar from "../components/salary/SalaryBandBar";
import { useT } from "../i18n";
import { EmptyState, Emoji, FriendlyError, InfoTip, PageHeader, StatusChip, UserAvatar, type Tone } from "../ui-kit";

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

function FiguresDialog({ item, onClose, onSaved }: { item: SalaryQueueItem; onClose: () => void; onSaved: () => Promise<void> }) {
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

function QueueCard({ item, onChanged, onEdit }: { item: SalaryQueueItem; onChanged: () => Promise<void>; onEdit: () => void }) {
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

export default function SalaryPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [searchParams, setSearchParams] = useSearchParams();
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const jobId = searchParams.get("jobId") ?? "";
  const chip = (searchParams.get("state") ?? "") as SalaryChip | "";
  const [data, setData] = useState<SalaryQueue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState<SalaryQueueItem | null>(null);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true });
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await salaryQueueApi.queue({ state: chip || undefined, jobId: jobId || undefined }));
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [chip, jobId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    jobsApi.list().then(setJobs).catch(() => setJobs([]));
  }, []);

  const counts = data?.counts ?? {};
  const total = data?.total ?? 0;
  const items = data?.items ?? [];

  return (
    <Box>
      <PageHeader
        emoji="money"
        title={t("salary.title")}
        purpose={t("salaryQueue.purpose")}
        tourKey="salary"
        extra={<RefreshButton loading={loading} onRefresh={() => void load()} label={t("offers.shared.refresh")} />}
      />

      <Card sx={{ p: { xs: 1.5, sm: 2 }, mb: 2.5 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ xs: "stretch", md: "center" }}>
          <Tabs
            value={chip}
            onChange={(_, v: string) => setParam("state", v)}
            variant="scrollable"
            scrollButtons="auto"
            allowScrollButtonsMobile
            sx={{ flex: 1, minWidth: 0 }}
            aria-label={t("salaryQueue.tabs_label")}
          >
            <Tab value="" label={t("salaryQueue.tab.all", { count: total })} />
            {SALARY_CHIPS.map((k) => (
              <Tab key={k} value={k} label={t("salaryQueue.tab.with_count", { label: t(`salaryQueue.chip.${k}`), count: counts[k] ?? 0 })} />
            ))}
          </Tabs>
          <TextField
            select
            size="small"
            label={t("salaryQueue.job")}
            value={jobId}
            onChange={(e) => setParam("jobId", e.target.value)}
            sx={{ minWidth: { md: 260 } }}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><Emoji name="briefcase" size={16} /></InputAdornment> } }}
          >
            <MenuItem value="">{t("salaryQueue.all_jobs")}</MenuItem>
            {jobs.map((j) => (
              <MenuItem key={j.id} value={j.id}>{j.title}</MenuItem>
            ))}
          </TextField>
        </Stack>
        {chip && (
          <Typography sx={{ mt: 1.25, px: 0.5, fontSize: 14, color: f.muted }}>{t(`salaryQueue.chip_hint.${chip}`)}</Typography>
        )}
      </Card>

      {error !== null && !loading ? (
        <FriendlyError what={t("salaryQueue.error.load")} fix={t("salary.error.fix")} error={error} onRetry={() => void load()} />
      ) : loading && !data ? (
        <Box sx={{ display: "grid", placeItems: "center", py: 6 }} role="status" aria-label={t("offers.shared.loading")}>
          <CircularProgress />
        </Box>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            illustration="empty"
            title={chip ? t("salaryQueue.empty.filtered") : t("salaryQueue.empty.none")}
            hint={chip ? t("salaryQueue.empty.filtered_hint") : t("salaryQueue.empty.none_hint")}
          />
        </Card>
      ) : (
        <Stack spacing={2}>
          {items.map((item) => (
            <QueueCard key={item.application_id} item={item} onChanged={load} onEdit={() => setEditing(item)} />
          ))}
        </Stack>
      )}

      {editing && <FiguresDialog item={editing} onClose={() => setEditing(null)} onSaved={load} />}
    </Box>
  );
}
