// Part 20.3: the signed-in employee's own page -- profile (request a change -> HR approves), job details,
// documents & letters, assets, and the way into their exit. Only their own data (backend: /api/v1/ui/self-service/me).
import { useCallback, useEffect, useState, type ReactNode } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { extractErrorMessage } from "../api/client";
import { openBlob, selfServiceApi, type ChangeRequest, type Editable, type MyProfile } from "../api/selfServiceApi";
import { CompanyEmail, EmpStatusChip } from "../components/employees/EmployeeDialogs";
import { useT } from "../i18n";
import { EmptyState, FriendlyError, PageHeader, StatusChip, UserAvatar } from "../ui-kit";

const fmtDate = (iso?: string | null) => (iso ? new Date(iso.length === 10 ? `${iso}T00:00:00` : iso).toLocaleDateString() : "—");
const grid = { display: "grid", gap: 1, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", md: "1fr 1fr 1fr" } };
const TEXT_FIELDS = ["preferred_name", "pronouns", "personal_email", "phone", "marital_status", "blood_group", "address"] as const;

function Field({ label, value }: { label: string; value: ReactNode }) {
  const f = useTheme().palette.fresh;
  return (
    <Box sx={{ p: 1.25, borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
      <Typography sx={{ fontSize: 12, color: f.muted }}>{label}</Typography>
      <Typography sx={{ fontSize: 14, fontWeight: 600, wordBreak: "break-word" }}>{value === null || value === undefined || value === "" ? "—" : value}</Typography>
    </Box>
  );
}

function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") {  // an emergency contact: always name, relation, phone (the database reorders keys)
    const o = v as Record<string, unknown>;
    return [o.name, o.relation, o.phone].filter(Boolean).join(", ") || "—";
  }
  return String(v);
}

export function ChangeList({ items, onCancel }: { items: ChangeRequest[]; onCancel?: (id: string) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const tone = { pending: "sun", approved: "ok", rejected: "coral", cancelled: "muted" } as const;
  return (
    <Stack spacing={1}>
      {items.map((r) => (
        <Box key={r.id} sx={{ p: 1.25, borderRadius: "10px", border: `1px solid ${f.line}` }} data-testid={`cr-${r.status}`}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <StatusChip tone={tone[r.status]} label={t(`me.cr.status.${r.status}`)} />
            <Typography sx={{ fontSize: 12, color: f.muted, flex: 1 }}>{fmtDate(r.created_at)}{r.reviewed_by ? ` · ${r.reviewed_by}` : ""}</Typography>
            {onCancel && r.status === "pending" && <Button size="small" onClick={() => onCancel(r.id)}>{t("me.cr.cancel")}</Button>}
          </Stack>
          {Object.entries(r.changes).map(([k, ch]) => (
            <Typography key={k} sx={{ fontSize: 13, mt: 0.5 }}><b>{t(`me.f.${k}`)}</b>: {show(ch.old)} → {show(ch.new)}</Typography>
          ))}
          {r.note && <Typography sx={{ fontSize: 13, color: f.muted }}>“{r.note}”</Typography>}
          {r.review_note && <Typography sx={{ fontSize: 13 }}>{t("me.cr.hr_note", { note: r.review_note })}</Typography>}
        </Box>
      ))}
    </Stack>
  );
}

function ChangeDialog({ current, onClose, onSent }: { current: Editable; onClose: () => void; onSent: (msg: string) => void }) {
  const t = useT();
  const [v, setV] = useState<Editable>({ ...current, emergency_contact: current.emergency_contact ?? { name: "", relation: "", phone: "" } });
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ec = v.emergency_contact ?? { name: "", relation: "", phone: "" };
  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await selfServiceApi.requestChange(v, note);
      onSent(t("me.cr.sent"));
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm" aria-labelledby="me-change-title">
      <DialogTitle id="me-change-title">{t("me.cr.title")}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={1.5}>
          <Typography sx={{ fontSize: 13, color: "text.secondary" }}>{t("me.cr.hint")}</Typography>
          {TEXT_FIELDS.map((k) => (
            <TextField key={k} label={t(`me.f.${k}`)} value={(v[k] as string | null | undefined) ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })}
              multiline={k === "address"} minRows={k === "address" ? 2 : undefined} />
          ))}
          <Typography sx={{ fontWeight: 700 }}>{t("me.f.emergency_contact")}</Typography>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            {(["name", "relation", "phone"] as const).map((k) => (
              <TextField key={k} label={t(`me.ec.${k}`)} value={ec[k] ?? ""} onChange={(e) => setV({ ...v, emergency_contact: { ...ec, [k]: e.target.value } })} />
            ))}
          </Stack>
          <TextField label={t("me.cr.note")} value={note} onChange={(e) => setNote(e.target.value)} multiline minRows={2} />
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={send} disabled={busy}>{t("me.cr.send")}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function MyProfilePage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [d, setD] = useState<MyProfile | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState("personal");
  const [changing, setChanging] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const load = useCallback(() => { setError(null); selfServiceApi.me().then(setD).catch(setError); }, []);
  useEffect(load, [load]);

  if (error) return <FriendlyError error={error} onRetry={load} />;
  if (!d) return <Box sx={{ display: "grid", placeItems: "center", py: 8 }}><CircularProgress aria-label={t("me.loading")} /></Box>;
  if (!d.linked || !d.profile) return (<Box><PageHeader emoji="id_card" title={t("me.title")} purpose={t("me.purpose")} /><EmptyState illustration="access-denied" title={t("me.not_linked")} /></Box>);
  const p = d.profile;
  const e = d.editable ?? {};
  const pending = (d.change_requests ?? []).filter((r) => r.status === "pending");
  const letters = p.documents.filter((x) => x.kind === "letter");
  const docs = p.documents.filter((x) => x.kind !== "letter");
  const exitKey = d.exit?.key;

  return (
    <Box>
      <PageHeader emoji="id_card" title={t("me.title")} purpose={t("me.purpose")} />
      <Card sx={{ p: { xs: 2, md: 2.5 }, mb: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
          <UserAvatar name={p.name} size={64} />
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography component="h2" sx={{ fontWeight: 800, fontSize: 22 }}>{p.name}</Typography>
            <Typography sx={{ color: f.muted }}>{[p.employee_code, p.designation, p.department].filter(Boolean).join(" · ")}</Typography>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.75 }} flexWrap="wrap" useFlexGap>
              <EmpStatusChip status={p.status} />
              <Typography sx={{ fontSize: 13 }}><CompanyEmail email={p.company_email} test={p.company_email_test} /></Typography>
            </Stack>
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button variant="contained" onClick={() => setChanging(true)} data-testid="me-request-change">{t("me.cr.button")}</Button>
            {d.is_interviewer && <Button variant="outlined" component={RouterLink} to="/my-interviews">{t("me.my_interviews")}</Button>}
            {(d.can_resign || exitKey) && (
              <Button variant="outlined" color={exitKey ? "primary" : "error"} component={RouterLink} to="/exits">{t(exitKey ? "me.see_exit" : "me.raise_exit")}</Button>
            )}
          </Stack>
        </Stack>
        {exitKey && (
          <Alert severity="info" sx={{ mt: 2 }} data-testid="me-exit-status">
            {t(`me.exit.${exitKey}`, { date: fmtDate(d.exit?.last_working_day) })}
          </Alert>
        )}
        {pending.length > 0 && <Alert severity="warning" sx={{ mt: 2 }}>{t("me.cr.waiting", { n: pending.length })}</Alert>}
      </Card>

      <Card sx={{ p: { xs: 2, md: 2.5 } }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" allowScrollButtonsMobile sx={{ mb: 2 }}>
          <Tab value="personal" label={t("emp.tab.personal")} />
          <Tab value="job" label={t("emp.tab.job")} />
          <Tab value="documents" label={t("me.tab.documents", { n: p.documents.length })} />
          <Tab value="assets" label={t("emp.tab.assets", { n: p.assets.filter((a) => !a.returned_on).length })} />
          <Tab value="requests" label={t("me.tab.requests", { n: (d.change_requests ?? []).length })} />
        </Tabs>

        {tab === "personal" && (
          <Stack spacing={2}>
            <Box sx={grid}>
              <Field label={t("emp.edit.first_name")} value={p.personal.first_name} />
              <Field label={t("emp.edit.last_name")} value={p.personal.last_name} />
              {TEXT_FIELDS.map((k) => <Field key={k} label={t(`me.f.${k}`)} value={e[k] as string | null} />)}
              <Field label={t("emp.dob")} value={fmtDate(p.personal.dob)} />
              <Field label={t("me.f.emergency_contact")} value={show(e.emergency_contact)} />
            </Box>
            <Typography sx={{ fontWeight: 700 }}>{t("emp.bank_id")}</Typography>
            <Box sx={grid}>
              <Field label="PAN" value={p.personal.pan} />
              <Field label="Aadhaar" value={p.personal.aadhaar} />
              <Field label={t("emp.bank")} value={p.personal.bank_account} />
            </Box>
            <Typography sx={{ fontSize: 13, color: f.muted }}>{t("me.bank_hint")}</Typography>
          </Stack>
        )}

        {tab === "job" && (
          <Box sx={grid}>
            <Field label={t("emp.col.code")} value={p.employee_code} />
            <Field label={t("emp.col.designation")} value={p.job.designation} />
            <Field label={t("emp.col.department")} value={p.job.department} />
            <Field label={t("emp.col.manager")} value={p.job.manager} />
            <Field label={t("emp.col.location")} value={p.job.location} />
            <Field label={t("emp.col.joined")} value={fmtDate(p.job.joined_on)} />
            <Field label={t("emp.col.exp_company")} value={p.experience_company} />
            <Field label={t("emp.col.exp_total")} value={p.experience_total} />
            <Field label={t("emp.notice_days")} value={p.job.notice_period_days != null ? t("emp.days", { n: p.job.notice_period_days }) : null} />
          </Box>
        )}

        {tab === "documents" && (p.documents.length === 0 ? <EmptyState compact illustration="files-uploading" title={t("emp.no_documents")} /> : (
          <Stack spacing={1}>
            {[...letters, ...docs].map((x) => (
              <Stack key={`${x.kind}-${x.id}`} direction="row" spacing={1} alignItems="center" sx={{ p: 1.25, borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                <Typography sx={{ flex: 1, fontWeight: 600 }}>{x.label}</Typography>
                <Typography sx={{ fontSize: 12, color: f.muted }}>{t(`emp.doc.${x.kind}`)}</Typography>
                <Typography sx={{ fontSize: 12, color: f.muted }}>{fmtDate(x.date)}</Typography>
                {x.kind === "letter" && <Button size="small" onClick={() => openBlob(selfServiceApi.letterBlob(x.id))}>{t("me.open_pdf")}</Button>}
              </Stack>
            ))}
          </Stack>
        ))}

        {tab === "assets" && (
          <Stack spacing={1}>
            {p.assets.length === 0 && <EmptyState compact illustration="devices" title={t("emp.no_assets")} />}
            {p.assets.map((a) => (
              <Stack key={a.allocation_id} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}
                sx={{ p: 1.25, borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}`, opacity: a.returned_on ? 0.65 : 1 }}>
                <Typography sx={{ flex: 1, fontWeight: 600 }}>{`${a.tag} - ${a.name}`}</Typography>
                <Typography sx={{ fontSize: 12, color: f.muted }}>
                  {a.returned_on ? t("emp.asset.returned_on", { date: fmtDate(a.returned_on), condition: a.condition ?? "" }) : t("emp.asset.given_on", { date: fmtDate(a.given_on) })}
                </Typography>
              </Stack>
            ))}
            <Box><Button component={RouterLink} to="/assets">{t("me.assets_page")}</Button></Box>
          </Stack>
        )}

        {tab === "requests" && ((d.change_requests ?? []).length === 0 ? <EmptyState compact illustration="completed-tasks" title={t("me.cr.none")} /> : (
          <ChangeList items={d.change_requests ?? []} onCancel={async (id) => { try { await selfServiceApi.cancelChange(id); load(); } catch (x) { setToast(extractErrorMessage(x, "")); } }} />
        ))}
      </Card>
      {changing && <ChangeDialog current={e} onClose={() => setChanging(false)} onSent={(m) => { setChanging(false); setToast(m); setTab("requests"); load(); }} />}
      <Snackbar open={Boolean(toast)} autoHideDuration={5000} onClose={() => setToast(null)} message={toast ?? ""} />
    </Box>
  );
}
