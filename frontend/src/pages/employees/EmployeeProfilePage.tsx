import { useCallback, useEffect, useState, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink, useParams } from "react-router-dom";

import { extractErrorMessage } from "../../api/client";
import { employeesApi, type EmployeeFacets, type EmployeeProfile, type EmployeeRow } from "../../api/employeesApi";
import { AccountChip, CompanyEmail, EditEmployeeDialog, EmpStatusChip, GiveAssetDialog } from "../../components/employees/EmployeeDialogs";
import { employeeActionsRegistry } from "../../components/employees/registry";
import { useT } from "../../i18n";
import { EmptyState, FriendlyError, StatusChip, UserAvatar } from "../../ui-kit";

// Part 20.1: one employee -- Personal / Job / Documents / Assets / History. Bank, PAN and Aadhaar
// are only ever shown masked here (the audited reveal stays on the HR record).

const fmtDate = (iso?: string | null) => (iso ? new Date(iso.length === 10 ? `${iso}T00:00:00` : iso).toLocaleDateString() : "—");

function Field({ label, value }: { label: string; value: ReactNode }) {
  const f = useTheme().palette.fresh;
  return (
    <Box sx={{ p: 1.25, borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
      <Typography sx={{ fontSize: 12, color: f.muted }}>{label}</Typography>
      <Typography sx={{ fontSize: 14, fontWeight: 600, wordBreak: "break-word" }}>{value === null || value === undefined || value === "" ? "—" : value}</Typography>
    </Box>
  );
}

const grid = { display: "grid", gap: 1, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", md: "1fr 1fr 1fr" } };

export default function EmployeeProfilePage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { id = "" } = useParams();
  const [p, setP] = useState<EmployeeProfile | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState("personal");
  const [editing, setEditing] = useState(false);
  const [giving, setGiving] = useState(false);
  const [facets, setFacets] = useState<EmployeeFacets | null>(null);
  const [people, setPeople] = useState<EmployeeRow[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [extra, setExtra] = useState<ReactNode>(null);

  const load = useCallback(() => { setError(null); employeesApi.get(id).then(setP).catch(setError); }, [id]);
  useEffect(load, [load]);
  const startEdit = async () => {
    const l = await employeesApi.list();
    setFacets(l.facets);
    setPeople(l.items);
    setEditing(true);
  };
  const invite = async () => {
    try {
      const r = await employeesApi.invite(id);
      setToast((r.email_status ?? "").startsWith("failed") ? t("emp.invite.failed_link", { link: r.link ?? "" }) : t("emp.invite.sent_to", { to: r.sent_to.join(", ") }));
      load();
    } catch (e) {
      setToast(extractErrorMessage(e, ""));
    }
  };

  if (error) return <FriendlyError error={error} onRetry={load} />;
  if (!p) return <Box sx={{ display: "grid", placeItems: "center", py: 8 }}><CircularProgress /></Box>;
  const closed = p.status === "exited" || p.status === "absconded";

  return (
    <Box>
      <Button component={RouterLink} to="/employees" startIcon={<ArrowBackIcon />} sx={{ mb: 1 }}>{t("emp.back")}</Button>
      <Card sx={{ p: { xs: 2, md: 2.5 }, mb: 2 }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
          <UserAvatar name={p.name} size={64} />
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography component="h1" sx={{ fontWeight: 800, fontSize: 22 }}>{p.name}</Typography>
            <Typography sx={{ color: f.muted }}>{[p.employee_code, p.designation, p.department].filter(Boolean).join(" · ")}</Typography>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.75 }} flexWrap="wrap" useFlexGap>
              <EmpStatusChip status={p.status} />
              <AccountChip account={p.app_account} long />
              {p.demo && <StatusChip tone="muted" label={t("emp.demo")} />}
              <Typography sx={{ fontSize: 13 }}><CompanyEmail email={p.company_email} test={p.company_email_test} /></Typography>
            </Stack>
          </Box>
          {p.can_edit && (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button variant="outlined" onClick={startEdit}>{t("emp.menu.edit")}</Button>
              {!closed && <Button variant="outlined" onClick={() => setGiving(true)}>{t("emp.menu.asset")}</Button>}
              {employeeActionsRegistry.items.filter((a) => a.visible(p)).map((a) => (
                <Button key={a.key} variant="outlined" onClick={() => setExtra(a.render(p, () => { setExtra(null); load(); }, setToast))}>{t(a.labelKey)}</Button>
              ))}
              {!closed && <Button variant="outlined" onClick={invite}>{t("emp.menu.invite")}</Button>}
            </Stack>
          )}
        </Stack>
      </Card>

      <Card sx={{ p: { xs: 2, md: 2.5 } }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" allowScrollButtonsMobile sx={{ mb: 2 }}>
          <Tab value="personal" label={t("emp.tab.personal")} />
          <Tab value="job" label={t("emp.tab.job")} />
          <Tab value="documents" label={t("emp.tab.documents", { n: p.documents.length })} />
          <Tab value="assets" label={t("emp.tab.assets", { n: p.assets.filter((a) => !a.returned_on).length })} />
          <Tab value="history" label={t("emp.tab.history")} />
        </Tabs>

        {tab === "personal" && (
          <Stack spacing={2}>
            <Box sx={grid}>
              <Field label={t("emp.edit.first_name")} value={p.personal.first_name} />
              <Field label={t("emp.edit.last_name")} value={p.personal.last_name} />
              <Field label={t("emp.edit.preferred_name")} value={p.personal.preferred_name} />
              <Field label={t("emp.dob")} value={fmtDate(p.personal.dob)} />
              <Field label={t("emp.col.phone")} value={p.personal.phone} />
              <Field label={t("emp.edit.personal_email")} value={p.personal.personal_email} />
            </Box>
            <Typography sx={{ fontWeight: 700 }}>{t("emp.bank_id")}</Typography>
            <Typography sx={{ fontSize: 13, color: f.muted, mt: -1.5 }}>{t("emp.bank_id_hint")}</Typography>
            <Box sx={grid}>
              <Field label="PAN" value={p.personal.pan} />
              <Field label="Aadhaar" value={p.personal.aadhaar} />
              <Field label={t("emp.bank")} value={p.personal.bank_account} />
            </Box>
            {p.personal.emergency_contacts.length > 0 && (
              <>
                <Typography sx={{ fontWeight: 700 }}>{t("emp.emergency")}</Typography>
                <Box sx={grid}>
                  {p.personal.emergency_contacts.map((c, i) => <Field key={i} label={c.relationship ?? c.relation ?? ""} value={`${c.name ?? ""} ${c.phone ?? ""}`.trim()} />)}
                </Box>
              </>
            )}
          </Stack>
        )}

        {tab === "job" && (
          <Box sx={grid}>
            <Field label={t("emp.col.code")} value={p.employee_code} />
            <Field label={t("emp.col.designation")} value={p.job.designation} />
            <Field label={t("emp.col.department")} value={p.job.department} />
            <Field label={t("emp.col.manager")} value={p.job.manager} />
            <Field label={t("emp.col.location")} value={p.job.location} />
            <Field label={t("emp.col.type")} value={p.job.employment_type ? t(`emp.type.${p.job.employment_type}`) : null} />
            <Field label={t("emp.col.joined")} value={fmtDate(p.job.joined_on)} />
            <Field label={t("emp.col.exp_company")} value={p.experience_company} />
            <Field label={t("emp.col.exp_total")} value={p.experience_total} />
            <Field label={t("emp.notice_days")} value={p.job.notice_period_days != null ? t("emp.days", { n: p.job.notice_period_days }) : null} />
            <Field label={t("emp.col.email")} value={<CompanyEmail email={p.company_email} test={p.company_email_test} />} />
            <Field label={t("emp.login")} value={p.login} />
            <Field label={t("emp.col.roles")} value={p.roles.join(", ")} />
            {p.exited_on && <Field label={t("emp.exited_on")} value={fmtDate(p.exited_on)} />}
            {p.rehire_eligible !== null && <Field label={t("emp.rehire")} value={p.rehire_eligible ? t("emp.yes") : t("emp.no")} />}
          </Box>
        )}

        {tab === "documents" && (p.documents.length === 0 ? <EmptyState compact illustration="files-uploading" title={t("emp.no_documents")} /> : (
          <Stack spacing={1}>
            {p.documents.map((d) => (
              <Stack key={`${d.kind}-${d.id}`} direction="row" spacing={1} alignItems="center" sx={{ p: 1.25, borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                <Typography sx={{ flex: 1, fontWeight: 600 }}>{d.label}</Typography>
                <Typography sx={{ fontSize: 12, color: f.muted }}>{t(`emp.doc.${d.kind}`)}</Typography>
                <Typography sx={{ fontSize: 12, color: f.muted }}>{fmtDate(d.date)}</Typography>
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
                {!a.returned_on && p.can_edit && (
                  <Button size="small" onClick={async () => {
                    try { await employeesApi.returnAsset(p.id, a.allocation_id, "good"); setToast(t("emp.asset.returned")); load(); } catch (e) { setToast(extractErrorMessage(e, "")); }
                  }}>{t("emp.asset.mark_returned")}</Button>
                )}
              </Stack>
            ))}
          </Stack>
        )}

        {tab === "history" && (p.history.length === 0 ? <EmptyState compact illustration="report" title={t("emp.no_history")} /> : (
          <Stack spacing={0.75}>
            {p.history.map((h, i) => (
              <Stack key={i} direction="row" spacing={1.5} sx={{ py: 0.75, borderBottom: `1px solid ${f.line}` }}>
                <Typography sx={{ fontSize: 12, color: f.muted, minWidth: 150 }}>{h.at ? new Date(h.at).toLocaleString() : ""}</Typography>
                <Typography sx={{ fontSize: 14, flex: 1 }}>{h.action.replace(/_/g, " ")}</Typography>
                <Typography sx={{ fontSize: 12, color: f.muted }}>{h.actor}</Typography>
              </Stack>
            ))}
          </Stack>
        ))}
      </Card>

      {editing && <EditEmployeeDialog employee={p} facets={facets} people={people} onClose={() => setEditing(false)} onSaved={(np) => { setEditing(false); setP({ ...p, ...np }); setToast(t("emp.saved")); load(); }} />}
      {giving && <GiveAssetDialog employee={p} onClose={() => setGiving(false)} onDone={(m) => { setGiving(false); setToast(m); load(); }} />}
      {extra}
      <Snackbar open={Boolean(toast)} autoHideDuration={7000} onClose={() => setToast(null)} message={toast} anchorOrigin={{ vertical: "bottom", horizontal: "center" }} />
    </Box>
  );
}
