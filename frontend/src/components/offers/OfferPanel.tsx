import { useCallback, useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
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
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { offersExtraApi, type OfferReviseInput, type OfferVersionRow, type OfferVersionStatus, type OfferVersionsSummary } from "../../api/offersExtra";
import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";
import { useMoney, useWhen } from "./shared";

// Fix 2026-10-05: the Offer section on the candidate profile and on each Offers-page card --
// [Resend for signature] (15 min apart), [Send revised offer] (v2, v3 ...; approval when above the
// limit) and the offer history: every version with who sent it, why, what changed, its status and PDF.

type ChipColor = "default" | "info" | "warning" | "success" | "error";
// literal keys so the i18n check can see them
const STATUS: Record<OfferVersionStatus, { labelKey: string; color: ChipColor }> = {
  draft: { labelKey: "offerx.status.draft", color: "default" },
  sent: { labelKey: "offerx.status.sent", color: "info" },
  viewed: { labelKey: "offerx.status.viewed", color: "warning" },
  signed: { labelKey: "offerx.status.signed", color: "success" },
  declined: { labelKey: "offerx.status.declined", color: "error" },
  replaced: { labelKey: "offerx.status.replaced", color: "default" },
  pending_approval: { labelKey: "offerx.status.pending_approval", color: "warning" },
  rejected: { labelKey: "offerx.status.rejected", color: "error" },
  withdrawn: { labelKey: "offerx.status.withdrawn", color: "default" },
};
const REASONS: { code: string; labelKey: string }[] = [
  { code: "salary", labelKey: "offerx.reason.salary" },
  { code: "joining_date", labelKey: "offerx.reason.joining_date" },
  { code: "designation", labelKey: "offerx.reason.designation" },
  { code: "other", labelKey: "offerx.reason.other" },
];
const REASON_KEY: Record<string, string> = Object.fromEntries(REASONS.map((r) => [r.code, r.labelKey]));

function StatusBadge({ status }: { status: OfferVersionStatus }) {
  const t = useT();
  const s = STATUS[status] ?? STATUS.sent;
  return <Chip size="small" color={s.color} variant={status === "replaced" || status === "withdrawn" ? "outlined" : "filled"} label={t(s.labelKey)} />;
}

export default function OfferPanel({ applicationId, canWrite, onChanged }: { applicationId: string; canWrite: boolean; onChanged?: () => void }) {
  const t = useT();
  const when = useWhen();
  const money = useMoney();
  const [data, setData] = useState<OfferVersionsSummary | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [reviseOpen, setReviseOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(() => {
    offersExtraApi.versions(applicationId).then((d) => { setData(d); setFailed(null); }).catch((e) => setFailed(extractErrorMessage(e, t("offerx.load_failed"))));
  }, [applicationId, t]);
  useEffect(load, [load]);
  // the cooldown text counts down by itself
  useEffect(() => {
    if (!data?.resend_available_at) return;
    const id = window.setInterval(() => setNow(Date.now()), 20_000);
    return () => window.clearInterval(id);
  }, [data?.resend_available_at]);

  if (failed) return <Alert severity="warning" action={<Button onClick={load}>{t("offerx.retry")}</Button>}>{failed}</Alert>;
  if (!data) return null;

  const coolUntil = data.resend_available_at ? new Date(data.resend_available_at).getTime() : 0;
  const cooling = coolUntil > now;
  const waitMin = cooling ? Math.max(1, Math.ceil((coolUntil - now) / 60_000)) : 0;

  const after = (s: OfferVersionsSummary, text: string, ok = true) => { setData(s); setMsg({ ok, text }); onChanged?.(); };

  const resend = async () => {
    setBusy("resend"); setMsg(null);
    try {
      const r = await offersExtraApi.resend(applicationId);
      after(r.summary, r.email_status === "sent" || r.email_status === "queued" ? t("offerx.resent", { n: r.sent_count }) : t("offerx.resent_not_emailed"), r.email_status !== "failed");
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, t("offerx.resend_failed")) });
      load();
    } finally { setBusy(null); }
  };

  const decide = async (approve: boolean) => {
    if (!data.pending) return;
    setBusy(approve ? "approve" : "reject"); setMsg(null);
    try {
      const r = await offersExtraApi.decideRevision(applicationId, data.pending.id, approve);
      after(r.summary, approve ? t("offerx.approved_sent", { n: r.version_no }) : t("offerx.rejected_done", { n: r.version_no }));
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, t("offerx.decide_failed")) });
    } finally { setBusy(null); }
  };

  const problems = (r: OfferVersionRow) =>
    (r.approval?.needed ?? []).map((p) => (p.code === "above_band" ? t("offerx.problem.above_band", { pct: p.over_pct ?? 0, max: money(p.band_max) })
      : t("offerx.problem.budget", { short: money(p.short_by), dept: p.department ?? "" }))).join(" ");

  return (
    <Stack spacing={1.5}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }} justifyContent="space-between" flexWrap="wrap" useFlexGap>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography sx={{ fontWeight: 700 }}>{t("offerx.version", { n: data.version_no })}</Typography>
          <StatusBadge status={data.status} />
          {data.values.ctc_total != null && <Typography sx={{ fontSize: 14 }} color="text.secondary">{t("offerx.ctc_is", { ctc: money(data.values.ctc_total) })}</Typography>}
        </Stack>
        {data.last_sent_at && (
          <Typography sx={{ fontSize: 13 }} color="text.secondary">{t("offerx.last_sent", { when: when(data.last_sent_at), n: data.sent_count })}</Typography>
        )}
      </Stack>

      {canWrite && (
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25} alignItems={{ sm: "center" }}>
          {data.can_resend && (
            <Button variant="outlined" onClick={resend} disabled={busy !== null || cooling} startIcon={<Emoji name="envelope" size={16} />}>
              {busy === "resend" ? t("offerx.resending") : t("offerx.resend")}
            </Button>
          )}
          <Button variant="contained" onClick={() => { setMsg(null); setReviseOpen(true); }} disabled={busy !== null} startIcon={<Emoji name="memo" size={16} />}>
            {t("offerx.revise")}
          </Button>
          {data.can_resend && cooling && <Typography sx={{ fontSize: 13 }} color="text.secondary">{t("offerx.cooldown", { min: waitMin })}</Typography>}
        </Stack>
      )}

      {data.pending && (
        <Alert severity="warning" icon={<Emoji name="hourglass" />}
          action={data.can_approve ? (
            <Stack direction="row" spacing={1}>
              <Button color="inherit" size="small" disabled={busy !== null} onClick={() => decide(false)}>{t("offerx.reject")}</Button>
              <Button variant="contained" size="small" disabled={busy !== null} onClick={() => decide(true)}>{t("offerx.approve_send")}</Button>
            </Stack>
          ) : undefined}>
          <b>{t("offerx.pending_title", { n: data.pending.version_no })}</b> {problems(data.pending)}{" "}
          {data.pending.changes.map((c) => `${c.label}: ${c.old} → ${c.new}`).join(" · ")}
          {!data.can_approve && <> {t("offerx.pending_who")}</>}
        </Alert>
      )}
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}

      <OfferHistory applicationId={applicationId} rows={data.history} />

      {reviseOpen && (
        <ReviseDialog applicationId={applicationId} data={data} onClose={() => setReviseOpen(false)}
          onDone={(s, text) => { setReviseOpen(false); after(s, text); }} />
      )}
    </Stack>
  );
}

function OfferHistory({ applicationId, rows }: { applicationId: string; rows: OfferVersionRow[] }) {
  const t = useT();
  const when = useWhen();
  const phone = useMediaQuery(useTheme().breakpoints.down("sm"));
  const [problem, setProblem] = useState<string | null>(null);
  const download = async (n: number) => {
    setProblem(null);
    const blob = await offersExtraApi.versionPdf(applicationId, n);
    if (!blob) { setProblem(t("offerx.pdf_failed")); return; }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `offer-letter-v${n}.pdf`;
    document.body.appendChild(a); a.click(); a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 5000);
  };
  if (!rows.length) return null;
  const reason = (r: OfferVersionRow) => (r.reason_code ? t(REASON_KEY[r.reason_code] ?? "offerx.reason.other") : t("offerx.first_offer")) + (r.reason_note ? ` - ${r.reason_note}` : "");
  const changes = (r: OfferVersionRow) => (r.changes.length ? r.changes.map((c) => `${c.label}: ${c.old} → ${c.new}`).join("; ") : "—");
  const pdf = (r: OfferVersionRow) => (["pending_approval", "rejected", "withdrawn"].includes(r.status) ? null : (
    <Button size="small" onClick={() => download(r.version_no)} startIcon={<Emoji name="page" size={14} />}>{t("offerx.pdf")}</Button>
  ));

  return (
    <Box>
      <Typography component="h3" sx={{ fontWeight: 700, fontSize: 14, mb: 0.75 }}>{t("offerx.history")}</Typography>
      {phone ? (
        <Stack spacing={1}>
          {rows.map((r) => (
            <Box key={r.id} sx={{ border: 1, borderColor: "divider", borderRadius: 2, p: 1.25 }}>
              <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
                <Typography sx={{ fontWeight: 700 }}>v{r.version_no}</Typography>
                <StatusBadge status={r.status} />
              </Stack>
              <Typography sx={{ fontSize: 13 }} color="text.secondary">{[when(r.sent_at ?? r.created_at), r.sent_by].filter(Boolean).join(" · ")}</Typography>
              <Typography sx={{ fontSize: 13 }}>{reason(r)}</Typography>
              <Typography sx={{ fontSize: 13 }}>{changes(r)}</Typography>
              {pdf(r)}
            </Box>
          ))}
        </Stack>
      ) : (
        <TableContainer sx={{ border: 1, borderColor: "divider", borderRadius: 2 }}>
          <Table size="small" aria-label={t("offerx.history")}>
            <TableHead>
              <TableRow>
                <TableCell>{t("offerx.col.version")}</TableCell>
                <TableCell>{t("offerx.col.date")}</TableCell>
                <TableCell>{t("offerx.col.by")}</TableCell>
                <TableCell>{t("offerx.col.reason")}</TableCell>
                <TableCell>{t("offerx.col.changes")}</TableCell>
                <TableCell>{t("offerx.col.status")}</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id}>
                  <TableCell sx={{ fontWeight: 700 }}>v{r.version_no}</TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>{when(r.sent_at ?? r.created_at)}</TableCell>
                  <TableCell>{r.sent_by ?? "—"}</TableCell>
                  <TableCell>{reason(r)}</TableCell>
                  <TableCell sx={{ maxWidth: 280 }}>{changes(r)}</TableCell>
                  <TableCell><StatusBadge status={r.status} /></TableCell>
                  <TableCell align="right">{pdf(r)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      {problem && <Alert severity="error" sx={{ mt: 1 }}>{problem}</Alert>}
    </Box>
  );
}

function ReviseDialog({ applicationId, data, onClose, onDone }: { applicationId: string; data: OfferVersionsSummary; onClose: () => void; onDone: (s: OfferVersionsSummary, text: string) => void }) {
  const t = useT();
  const money = useMoney();
  const phone = useMediaQuery(useTheme().breakpoints.down("sm"));
  const v = data.values;
  const [ctc, setCtc] = useState(v.ctc_total != null ? String(Math.round(v.ctc_total)) : "");
  const [components, setComponents] = useState(v.components.map((c) => ({ ...c, amount: c.amount != null ? String(c.amount) : "" })));
  const [joining, setJoining] = useState(v.joining_date ?? "");
  const [designation, setDesignation] = useState(v.designation);
  const [location, setLocation] = useState(v.work_location);
  const [terms, setTerms] = useState(v.terms);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);

  const ctcNum = ctc.trim() === "" ? null : Number(ctc.replace(/,/g, ""));
  const overBand = data.band?.max != null && ctcNum != null && ctcNum > data.band.max;
  const changed = useMemo(() => (
    (ctcNum ?? null) !== (v.ctc_total != null ? Math.round(v.ctc_total) : null) || joining !== (v.joining_date ?? "") || designation.trim() !== v.designation.trim()
    || location.trim() !== v.work_location.trim() || terms.trim() !== v.terms.trim()
    || components.some((c, i) => Number(c.amount || 0) !== Number(v.components[i]?.amount ?? 0))
  ), [ctcNum, joining, designation, location, terms, components, v]);
  const ready = changed && reason !== "" && (reason !== "other" || note.trim() !== "") && (ctcNum == null || ctcNum > 0);

  const submit = async () => {
    setBusy(true); setProblem(null);
    const body: OfferReviseInput = {
      ctc_total: ctcNum, joining_date: joining || null, designation, work_location: location, terms, reason_code: reason, reason_note: note || undefined,
      components: components.length && components.some((c, i) => Number(c.amount || 0) !== Number(v.components[i]?.amount ?? 0))
        ? components.map((c) => ({ code: c.code, name: c.name, amount: Number(c.amount || 0) })) : undefined,
    };
    try {
      const r = await offersExtraApi.revise(applicationId, body);
      onDone(r.summary, r.state === "pending_approval" ? t("offerx.revise_pending", { n: r.version_no }) : r.emailed ? t("offerx.revise_sent", { n: r.version_no }) : t("offerx.revise_sent_no_email", { n: r.version_no }));
    } catch (e) {
      setProblem(extractErrorMessage(e, t("offerx.revise_failed")));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} fullScreen={phone} fullWidth maxWidth="sm">
      <DialogTitle>{t("offerx.revise_title", { n: data.version_no + 1 })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography sx={{ fontSize: 14 }} color="text.secondary">{t("offerx.revise_intro")}</Typography>
          <TextField label={t("offerx.f.ctc")} value={ctc} onChange={(e) => setCtc(e.target.value.replace(/[^\d,]/g, ""))} inputMode="numeric"
            helperText={overBand ? t("offerx.f.ctc_over", { max: money(data.band?.max) }) : data.band?.max != null ? t("offerx.f.ctc_band", { min: money(data.band.min ?? 0), max: money(data.band.max) }) : t("offerx.f.ctc_hint")}
            error={overBand} slotProps={{ formHelperText: { sx: overBand ? { color: "warning.main" } : undefined } }} />
          {components.length > 0 && (
            <Box>
              <Typography sx={{ fontWeight: 700, fontSize: 14, mb: 1 }}>{t("offerx.f.breakup")}</Typography>
              <Box sx={{ display: "grid", gap: 1.25, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" } }}>
                {components.map((c, i) => (
                  <TextField key={c.code ?? i} size="small" label={c.name ?? c.code ?? ""} value={c.amount} inputMode="numeric"
                    onChange={(e) => setComponents((x) => x.map((y, j) => (j === i ? { ...y, amount: e.target.value.replace(/[^\d.]/g, "") } : y)))} />
                ))}
              </Box>
            </Box>
          )}
          <TextField type="date" label={t("offerx.f.joining")} value={joining} onChange={(e) => setJoining(e.target.value)}
            slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: tomorrow } }} helperText={t("offerx.f.joining_hint")} />
          <TextField label={t("offerx.f.designation")} value={designation} onChange={(e) => setDesignation(e.target.value)} />
          <TextField label={t("offerx.f.location")} value={location} onChange={(e) => setLocation(e.target.value)} />
          <TextField label={t("offerx.f.terms")} value={terms} onChange={(e) => setTerms(e.target.value)} multiline minRows={2} helperText={t("offerx.f.terms_hint")} />
          <TextField select required label={t("offerx.f.reason")} value={reason} onChange={(e) => setReason(e.target.value)}>
            {REASONS.map((r) => <MenuItem key={r.code} value={r.code}>{t(r.labelKey)}</MenuItem>)}
          </TextField>
          <TextField label={reason === "other" ? t("offerx.f.note_required") : t("offerx.f.note")} value={note} onChange={(e) => setNote(e.target.value)}
            required={reason === "other"} multiline minRows={2} />
          {overBand && <Alert severity="warning">{t("offerx.needs_approval_hint")}</Alert>}
          {data.signed && <Alert severity="info">{t("offerx.signed_hint")}</Alert>}
          {!changed && <Typography sx={{ fontSize: 13 }} color="text.secondary">{t("offerx.nothing_changed")}</Typography>}
          {problem && <Alert severity="error">{problem}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>{t("offerx.cancel")}</Button>
        <Button variant="contained" onClick={submit} disabled={busy || !ready}>
          {busy ? t("offerx.sending") : overBand ? t("offerx.send_for_approval") : t("offerx.send_revised")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
