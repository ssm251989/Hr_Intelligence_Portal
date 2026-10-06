// Part 15.6 -- /exits (L X1, X2, X3, X5). Employee: self-service resignation, then their
// exit's progress + letter. HR: everyone leaving, the clearance board by team with owners,
// each person's exit (last day, exit interview, relieving letter -- HR issues or holds it).
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import FormControlLabel from "@mui/material/FormControlLabel";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { http } from "../../api/client";
import { serviceDeskExtra, type MySeparation, type SeparationRow } from "../../api/serviceDeskExtra";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import ConfirmDialog from "../../components/ConfirmDialog";
import ClearanceBoard from "../../components/servicedesk/ClearanceBoard";
import ExitCaseDialog, { stageIndex } from "../../components/servicedesk/ExitCaseDialog";
import { LetterChip, LetterPreviewButton, letterState } from "../../components/servicedesk/LetterStatus";
import { Section, SeparationStatusChip, localISO, typeLabel, useCategories, useDateFmt, useToast } from "../../components/servicedesk/shared";
import { useT } from "../../i18n";
import { MyExitInterview } from "../../components/exits/ExitInterviewCards";
import ExitChecklist, { MyExitTasks } from "../../components/exits/ExitChecklist";
import { selfServiceApi } from "../../api/selfServiceApi";
import TeamExitApprovals from "../../components/exits/TeamExitApprovals";
import { Cell, EmptyState, Emoji, FriendlyError, PageGrid, PageHeader, StageStepper, StatTile } from "../../ui-kit";

const STAGES = ["submitted", "approved", "clearance", "completed"];
const OPEN = ["submitted", "retention", "approved", "clearance"];

function addDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return localISO(d);
}

// ---- employee ----

function ResignForm({ notice, onSent }: { notice: number | null; onSent: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const reasons = useCategories("exit_reason");
  const [lwd, setLwd] = useState(notice != null ? addDays(notice) : "");  // Part 20.3: defaults to the notice period
  const [early, setEarly] = useState(false);
  const [letter, setLetter] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const [details, setDetails] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const today = localISO();

  const send = async () => {
    setConfirm(false);
    setBusy(true);
    setError(null);
    try {
      await serviceDeskExtra.resign({ requested_lwd: lwd || null, reason_code: reason || null, reason_text: details.trim() || null, early_release_requested: early });
      if (letter) await selfServiceApi.uploadResignationLetter(letter);
      onSent();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack spacing={2}>
      <Typography sx={{ color: f.muted, maxWidth: "75ch" }}>{t("exits.resign.intro")}</Typography>
      {notice != null && (
        <Box sx={{ bgcolor: f.skySoft, borderRadius: "12px", p: 1.5, display: "flex", gap: 1, alignItems: "center" }}>
          <Emoji name="calendar" size={18} />
          <Typography sx={{ fontSize: 14 }}>{t("exits.resign.notice", { days: notice, date: fmt.date(addDays(notice)) })}</Typography>
        </Box>
      )}
      <TextField type="date" label={t("exits.resign.lwd")} helperText={t("exits.resign.lwd_hint")} value={lwd} onChange={(e) => setLwd(e.target.value)}
        InputLabelProps={{ shrink: true }} inputProps={{ min: today }} sx={{ maxWidth: 360 }} />
      {(reasons.list?.length ?? 0) > 0 && (
        <TextField select label={t("exits.resign.reason")} helperText={t("exits.resign.reason_hint")} value={reason} onChange={(e) => setReason(e.target.value)} sx={{ maxWidth: 360 }}>
          <MenuItem value="">{t("exits.resign.reason_none")}</MenuItem>
          {reasons.list!.map((r) => <MenuItem key={r.code} value={r.code}>{r.label}</MenuItem>)}
        </TextField>
      )}
      <TextField label={t("exits.resign.details")} placeholder={t("exits.resign.details_ph")} helperText={t("exits.resign.reason_hint")} value={details}
        onChange={(e) => setDetails(e.target.value)} multiline minRows={3} fullWidth />
      <FormControlLabel control={<Checkbox checked={early} onChange={(e) => setEarly(e.target.checked)} />} label={t("me.resign.early")} />
      <Box>
        <Button component="label" variant="text" startIcon={<Emoji name="page" size={16} />}>
          {letter ? letter.name : t("me.resign.letter")}
          <input hidden type="file" accept=".pdf,.doc,.docx,image/*" onChange={(e) => setLetter(e.target.files?.[0] ?? null)} />
        </Button>
        <Typography sx={{ fontSize: 12, color: f.muted }}>{t("me.resign.letter_hint")}</Typography>
      </Box>
      {error ? <FriendlyError error={error} compact /> : null}
      <Box>
        <Button variant="contained" color="error" disabled={busy} onClick={() => setConfirm(true)} startIcon={<Emoji name="door" size={16} />}>
          {busy ? t("helpdesk.submitting") : t("exits.resign.submit")}
        </Button>
      </Box>
      <ConfirmDialog open={confirm} title={t("exits.resign.confirm_title")} message={t("exits.resign.confirm_text")} confirmLabel={t("exits.resign.submit")}
        cancelLabel={t("action.cancel")} onCancel={() => setConfirm(false)} onConfirm={send} />
    </Stack>
  );
}

function MyExit({ data, justResigned, onSkip, onChanged }: { data: SeparationRow; justResigned?: boolean; onSkip?: () => void; onChanged?: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const [withdrawing, setWithdrawing] = useState(false);
  const [werr, setWerr] = useState<unknown>(null);
  const canWithdraw = ["submitted", "retention"].includes(data.status);
  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
        <SeparationStatusChip status={data.status} />
        {/* Part 20.3: Submitted / Manager approved / HR approved - last day <date> / Withdrawn */}
        {data.status_label && (
          <Typography sx={{ fontSize: 14, fontWeight: 700 }} data-testid="my-exit-status">
            {t(`me.exit.${data.status_label}`, { date: fmt.date(data.approved_lwd) })}
            {data.waiting_for_manager ? ` - ${t("me.exit.waiting_manager", { name: data.waiting_for_manager })}` : ""}
          </Typography>
        )}
        {data.early_release_requested && <Typography sx={{ fontSize: 13, color: f.muted }}>{t("me.resign.early_asked")}</Typography>}
        <Box sx={{ flex: 1 }} />
        {canWithdraw && <Button color="error" onClick={() => setWithdrawing(true)}>{t("me.resign.withdraw")}</Button>}
      </Stack>
      {werr ? <FriendlyError error={werr} compact /> : null}
      <ConfirmDialog open={withdrawing} title={t("me.resign.withdraw")} message={t("me.resign.withdraw_confirm")} confirmLabel={t("me.resign.withdraw")}
        cancelLabel={t("action.cancel")} onCancel={() => setWithdrawing(false)}
        onConfirm={async () => { setWithdrawing(false); try { await selfServiceApi.withdraw(); onChanged?.(); } catch (e) { setWerr(e); } }} />
      {/* fix 2026-10-06: step 2 right after "Submit resignation" (skippable) -- and here until the last working day */}
      {justResigned && data.status !== "withdrawn" && <MyExitInterview firstTime onSkip={onSkip} />}
      {data.status !== "withdrawn" && <StageStepper stages={STAGES.map((k) => t(`exits.step.${k}`))} current={stageIndex(data.status)} />}
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 1.5 }}>
        <Box sx={{ bgcolor: f.surface2, borderRadius: "12px", p: 1.5 }}>
          <Typography sx={{ fontSize: 12, color: f.muted }}>{t("exits.me.lwd")}</Typography>
          <Typography sx={{ fontWeight: 800, fontSize: 18 }}>{data.approved_lwd ? fmt.date(data.approved_lwd) : t("exits.me.lwd_pending")}</Typography>
          {!data.approved_lwd && data.requested_lwd && <Typography sx={{ fontSize: 13, color: f.muted }}>{t("exits.me.requested", { date: fmt.date(data.requested_lwd) })}</Typography>}
        </Box>
        <Box sx={{ bgcolor: f.surface2, borderRadius: "12px", p: 1.5 }}>
          <Typography sx={{ fontSize: 12, color: f.muted, mb: 0.5 }}>{t("exits.letter.title")}</Typography>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <LetterChip s={data} forEmployee />
            {data.letters.relieving && <LetterPreviewButton separationId={data.id} />}
          </Stack>
        </Box>
      </Box>
      {!justResigned && data.status !== "withdrawn" && <MyExitInterview />}
      {/* feat 2026-10-06: the employee's own checklist -- "I have returned it" on their asset lines */}
      {data.status !== "withdrawn" && (
        <Box>
          <Typography component="h3" sx={{ fontWeight: 800, mb: 1 }}>{t("exits.me.progress")}</Typography>
          <ExitChecklist />
        </Box>
      )}
    </Stack>
  );
}

function EmployeeExit({ canResign, onToast, formRequested }: { canResign: boolean; onToast: (m: string) => void; formRequested: number }) {
  const t = useT();
  const [data, setData] = useState<MySeparation | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [justResigned, setJustResigned] = useState(false);
  const load = useCallback(() => {
    setError(null);
    serviceDeskExtra.mySeparation().then(setData).catch(setError);
  }, []);
  useEffect(load, [load]);

  let body;
  if (error) body = <FriendlyError error={error} onRetry={load} compact />;
  else if (!data) body = <Box sx={{ display: "grid", placeItems: "center", py: 4 }}><CircularProgress aria-label={t("helpdesk.common.loading")} /></Box>;
  else if (!data.linked) body = <EmptyState compact illustration="access-denied" title={t("exits.resign.not_linked")} />;
  else if (data.separation && data.separation.status !== "withdrawn") body = <MyExit data={data.separation} justResigned={justResigned} onSkip={() => setJustResigned(false)} onChanged={load} />;
  else if (!canResign || !["active", "probation"].includes(data.employee_status ?? "active")) body = <EmptyState compact illustration="empty" title={t("exits.resign.not_active")} />;
  else body = <ResignForm key={formRequested} notice={data.notice_period_days} onSent={() => { onToast(t("exits.resign.sent")); setJustResigned(true); load(); }} />;

  const hasCase = Boolean(data?.separation && data.separation.status !== "withdrawn");
  return <Section id="sd-resign" emoji="door" title={t(hasCase ? "exits.me.title" : "exits.resign.title")}>{body}</Section>;
}

// ---- HR ----

function HrExits({ onToast, focusItem, openSep }: { onToast: (m: string) => void; focusItem: string | null; openSep?: string | null }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const { can } = useMeBootstrap();
  const reasons = useCategories("exit_reason");
  const [tab, setTab] = useState<"list" | "board">("list");
  const [includeClosed, setIncludeClosed] = useState(false);
  const [rows, setRows] = useState<SeparationRow[] | null>(null);
  const [today, setToday] = useState(localISO());
  const [error, setError] = useState<unknown>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    serviceDeskExtra.separations(includeClosed).then((r) => { setRows(r.items); setToday(r.today); }).catch(setError);
  }, [includeClosed]);
  useEffect(load, [load]);
  // feat 2026-10-06: emails link to /exits?item=<id> -> open that exit with the item expanded
  useEffect(() => {
    const hit = focusItem ? rows?.find((s) => (s.items ?? []).some((i) => i.id === focusItem)) : undefined;
    if (hit) setOpenId(hit.id);
    else if (openSep && rows?.some((r) => r.id === openSep)) setOpenId(openSep);  // Part 20.3: after HR starts an exit
  }, [rows, focusItem, openSep]);

  const open = useMemo(() => (rows ?? []).filter((s) => OPEN.includes(s.status)), [rows]);
  const itemsLeft = open.reduce((n, s) => n + s.items_pending, 0);
  const soonLimit = new Date(`${today}T00:00:00`);
  soonLimit.setDate(soonLimit.getDate() + 7);
  const soon = open.filter((s) => s.approved_lwd && new Date(`${s.approved_lwd}T00:00:00`) <= soonLimit).length;
  const ready = open.filter((s) => letterState(s) === "ready").length;
  const current = rows?.find((s) => s.id === openId) ?? null;

  return (
    <>
      <PageGrid sx={{ mb: 2.25 }}>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="door" value={open.length} label={t("exits.stat.open", { count: open.length })} loading={rows === null} /></Cell>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="clipboard" value={itemsLeft} label={t("exits.stat.items", { count: itemsLeft })} tone="sun" loading={rows === null} /></Cell>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="calendar" value={soon} label={t("exits.stat.soon")} tone="coral" loading={rows === null} /></Cell>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="page" value={ready} label={t("exits.stat.letters", { count: ready })} tone="ok" loading={rows === null} /></Cell>
      </PageGrid>
      <Card sx={{ p: { xs: 1.5, md: 2 } }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }} sx={{ mb: 1.5 }}>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} aria-label={t("exits.title")}>
            <Tab value="list" label={t("exits.hr.tab.list")} />
            <Tab value="board" label={t("exits.hr.tab.board")} />
          </Tabs>
          <Box sx={{ flex: 1 }} />
          {tab === "list" && <FormControlLabel control={<Switch checked={includeClosed} onChange={(e) => setIncludeClosed(e.target.checked)} />} label={t("exits.hr.show_closed")} />}
        </Stack>
        {error ? <FriendlyError error={error} onRetry={load} compact /> : rows === null ? <LinearProgress aria-label={t("helpdesk.common.loading")} /> : tab === "board" ? (
          <ClearanceBoard separations={open} canClear={can("separation.clearance.edit")} onChanged={load} onToast={onToast} />
        ) : rows.length === 0 ? (
          <EmptyState illustration="team-spirit" title={t("exits.hr.empty")} hint={t("exits.hr.empty_hint")} />
        ) : (
          <TableContainer>
            <Table size="small" aria-label={t("exits.hr.tab.list")}>
              <TableHead>
                <TableRow>
                  <TableCell>{t("exits.col.person")}</TableCell>
                  <TableCell>{t("exits.col.type")}</TableCell>
                  <TableCell>{t("exits.col.submitted")}</TableCell>
                  <TableCell>{t("exits.col.lwd")}</TableCell>
                  <TableCell>{t("exits.col.status")}</TableCell>
                  <TableCell>{t("exits.col.clearance")}</TableCell>
                  <TableCell>{t("exits.col.letter")}</TableCell>
                  <TableCell align="right"><Box component="span" sx={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>{t("helpdesk.common.more")}</Box></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((s) => (
                  <TableRow key={s.id} hover sx={{ cursor: "pointer" }} onClick={() => setOpenId(s.id)}>
                    <TableCell>
                      <Typography sx={{ fontWeight: 700, fontSize: 14 }}>{s.employee_name ?? "—"}</Typography>
                      <Typography sx={{ fontSize: 12, color: f.muted }}>{s.employee_code}</Typography>
                    </TableCell>
                    <TableCell>{typeLabel(t, s.type)}</TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{fmt.date(s.submitted_on)}</TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{s.approved_lwd ? fmt.date(s.approved_lwd) : <Typography component="span" sx={{ fontSize: 13, color: f.muted }}>{t("exits.me.lwd_pending")}</Typography>}</TableCell>
                    <TableCell><SeparationStatusChip status={s.status} /></TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{s.items_total ? t("exits.me.progress_text", { done: s.items_total - s.items_pending, total: s.items_total }) : "—"}</TableCell>
                    <TableCell><LetterChip s={s} /></TableCell>
                    <TableCell align="right"><Button size="small" onClick={(e) => { e.stopPropagation(); setOpenId(s.id); }}>{t("exits.case.open")}</Button></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Card>
      <ExitCaseDialog separation={current} onClose={() => setOpenId(null)} onChanged={load} onToast={onToast} reasonLabel={reasons.label} focusItemId={focusItem} />
    </>
  );
}

export default function ExitsPage() {
  const t = useT();
  const { can } = useMeBootstrap();
  const [toast, show] = useToast();
  const [formKey, setFormKey] = useState(0);
  const [params] = useSearchParams();
  const focusItem = params.get("item");
  const [hrKey, setHrKey] = useState(0);
  const isHr = can("separation.case.view");
  const canResign = can("separation.self.create");
  const canExport = can("separation.case.export");

  const download = async () => {
    const blob = await http.fetchBlob(serviceDeskExtra.exportUrl);
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "exits.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const primary = isHr
    ? (canExport ? <Button variant="contained" onClick={download} startIcon={<Emoji name="bar_chart" size={16} />}>{t("exits.export")}</Button> : undefined)
    : canResign ? (
      <Button variant="contained" onClick={() => { setFormKey((k) => k + 1); document.getElementById("sd-resign")?.scrollIntoView({ block: "start" }); }}
        startIcon={<Emoji name="door" size={16} />}>{t("exits.resign.primary")}</Button>
    ) : undefined;

  return (
    <Box>
      <PageHeader emoji="door" title={t("exits.title")} purpose={t(isHr ? "exits.purpose_hr" : "exits.purpose_me")} tourKey="exits" primary={primary} />
      <TeamExitApprovals focusId={params.get("approve")} onToast={(m) => show(m)} onChanged={() => setHrKey((k) => k + 1)} />
      {isHr && <HrExits key={hrKey} onToast={(m) => show(m)} focusItem={focusItem} openSep={params.get("open")} />}
      {!isHr && (
        <Box sx={{ mb: 2.25 }}><MyExitTasks focusItemId={focusItem} onToast={(m) => show(m)} /></Box>
      )}
      {(canResign || !isHr) && (
        <Box sx={{ mt: isHr ? 2.25 : 0 }}>
          <EmployeeExit canResign={canResign} onToast={(m) => show(m)} formRequested={formKey} />
        </Box>
      )}
      {toast}
    </Box>
  );
}
