import { useEffect, useMemo, useState } from "react";
import { Link as RouterLink, useParams, useSearchParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid";
import Link from "@mui/material/Link";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { peopleApi, skillList, type EmployeeSummary, type PeopleFilters, type PersonRow, type SensitiveField as FieldKey } from "../../api/peopleApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import DocumentsPanel from "../../components/people/DocumentsPanel";
import HistoryPanel, { eventLabel } from "../../components/people/HistoryPanel";
import JobChangeDialog from "../../components/people/JobChangeDialog";
import LettersPanel from "../../components/people/LettersPanel";
import SensitiveField from "../../components/people/SensitiveField";
import { EmployeeStatusChip, Field, NoAccess, PendingBadge, SectionCard, listOf, useFormatDate } from "../../components/people/shared";
import { useT } from "../../i18n";
import { Emoji, EmptyState, FriendlyError, InfoTip, PageHeader, StatusChip, UserAvatar } from "../../ui-kit";

type TabKey = "personal" | "job" | "documents" | "history";
const TABS: TabKey[] = ["personal", "job", "documents", "history"];
const SENSITIVE: FieldKey[] = ["pan", "aadhaar", "bank_account", "passport"];
// which job field a pending change touches -> the field shown on the Job tab
const CHANGE_FIELD: Record<string, string> = {
  department_id: "department", location_id: "location", manager_employee_id: "manager", designation: "designation",
  grade: "grade", work_mode: "work_mode", position_id: "designation", confirmation_date: "confirmation_date",
};

export default function EmployeeProfilePage() {
  const { employeeId = "" } = useParams();
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useFormatDate();
  const { can, loading: bootLoading } = useMeBootstrap();
  const canView = can("core_hr.employee.view");
  const [params, setParams] = useSearchParams();
  const tab = (TABS.includes(params.get("tab") as TabKey) ? params.get("tab") : "personal") as TabKey;

  const [data, setData] = useState<EmployeeSummary | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [filters, setFilters] = useState<PeopleFilters | null>(null);
  const [people, setPeople] = useState<PersonRow[]>([]);
  const [changeOpen, setChangeOpen] = useState(false);
  const [notice, setNotice] = useState<{ tone: "ok" | "sun"; text: string } | null>(null);
  const [historyKey, setHistoryKey] = useState(0);

  const load = () => {
    setError(null);
    return peopleApi.summary(employeeId).then(setData).catch(setError);
  };
  useEffect(() => {
    if (!canView || !employeeId) return;
    setData(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeId, canView]);

  const openChange = () => {
    if (!filters) peopleApi.filters().then(setFilters).catch(() => undefined);
    if (!people.length) peopleApi.list({ status: "active,on_notice,pre_hire" }).then((r) => setPeople(r.items)).catch(() => undefined);
    setChangeOpen(true);
  };

  const pendingFields = useMemo(() => {
    const s = new Set<string>();
    (data?.pending_changes ?? []).forEach((p) => p.changes.forEach((c) => s.add(CHANGE_FIELD[c] ?? c)));
    return s;
  }, [data]);

  const letterContext = useMemo(() => {
    if (!data) return {};
    const p = data.person;
    const j = data.job ?? {};
    const employee = {
      name: p.name, first_name: p.first_name, last_name: p.last_name ?? "", employee_code: p.employee_code, designation: j.designation ?? "",
      department: j.department ?? "", location: j.location ?? "", manager_name: j.manager_name ?? "", joining_date: fmt(p.joined_on),
      confirmation_date: j.confirmation_date ? fmt(j.confirmation_date) : "",
    };
    return { ...employee, employee_name: p.name, date: fmt(new Date().toISOString()), employee };
  }, [data, fmt]);

  if (!bootLoading && !canView) {
    return (
      <Box>
        <PageHeader emoji="people" title={t("people.profile.title")} purpose={t("people.profile.purpose")} />
        <NoAccess />
      </Box>
    );
  }
  if (error) {
    return (
      <Box>
        <PageHeader emoji="people" title={t("people.profile.title")} purpose={t("people.profile.purpose")}
          primary={<Button variant="contained" component={RouterLink} to="/employees">{t("people.profile.back")}</Button>} />
        <FriendlyError error={error} what={t("people.profile.load_failed")} onRetry={load} actionLabel={t("people.profile.back")} actionTo="/employees" />
      </Box>
    );
  }
  if (!data) {
    return (
      <Stack spacing={2}>
        <Skeleton variant="rounded" height={60} />
        <Skeleton variant="rounded" height={160} />
        <Skeleton variant="rounded" height={320} />
      </Stack>
    );
  }

  const { person, job, sensitive, pending_changes: pending } = data;
  const skills = skillList(person.skills);
  const headerLine = [job?.department, job?.location].filter(Boolean).join(" · ");

  return (
    <Box>
      <PageHeader
        emoji="people"
        title={t("people.profile.title")}
        purpose={t("people.profile.purpose")}
        tourKey="employee_profile"
        primary={data.can.edit_job ? <Button variant="contained" onClick={openChange}>{t("people.profile.request_change")}</Button> : undefined}
        extra={<Button variant="outlined" component={RouterLink} to="/employees">{t("people.profile.back")}</Button>}
      />

      {notice && (
        <Card role="status" sx={{ p: 1.5, mb: 2, bgcolor: notice.tone === "ok" ? f.okSoft : f.sunSoft, boxShadow: "none" }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <Emoji name={notice.tone === "ok" ? "check" : "hourglass"} size={18} />
            <Typography sx={{ flex: 1, fontWeight: 600 }}>{notice.text}</Typography>
            <Button size="small" onClick={() => setNotice(null)}>{t("action.close")}</Button>
          </Stack>
        </Card>
      )}

      {/* header card */}
      <Card sx={{ p: { xs: 2, sm: 3 }, mb: 2.5 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={3} alignItems={{ md: "center" }}>
          <UserAvatar name={person.name} src={person.photo_url} size={96} />
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography variant="h2" component="h2" sx={{ fontWeight: 800 }}>{person.name}</Typography>
              <EmployeeStatusChip status={person.status} size="medium" />
              {pending.length > 0 && <PendingBadge label={t("people.pending.count", { count: pending.length })} />}
            </Stack>
            <Typography sx={{ fontSize: 17, fontWeight: 600, mt: 0.5 }}>{job?.designation || t("people.profile.no_designation")}</Typography>
            <Stack direction="row" spacing={2.5} sx={{ mt: 1, color: f.muted, flexWrap: "wrap", rowGap: 0.5 }}>
              {headerLine && <Typography sx={{ display: "flex", alignItems: "center", gap: 0.5 }}><Emoji name="building" size={16} />{headerLine}</Typography>}
              <Typography sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                <Emoji name="handshake" size={16} />
                {job?.manager_id && job.manager_name
                  ? <>{t("people.profile.reports_to")} <Link component={RouterLink} to={`/employees/${job.manager_id}`} sx={{ fontWeight: 700 }}>{job.manager_name}</Link></>
                  : t("people.profile.no_manager")}
              </Typography>
              <Typography sx={{ display: "flex", alignItems: "center", gap: 0.5 }}><Emoji name="id_card" size={16} />{t("people.profile.code", { code: person.employee_code })}</Typography>
              {data.direct_reports > 0 && (
                <Typography sx={{ display: "flex", alignItems: "center", gap: 0.5 }}><Emoji name="people" size={16} />{t("people.profile.reports", { count: data.direct_reports })}</Typography>
              )}
            </Stack>
          </Box>
          <Stack spacing={1} sx={{ minWidth: { md: 220 } }}>
            {person.work_email && <Button variant="outlined" href={`mailto:${person.work_email}`} startIcon={<Emoji name="envelope" size={16} />} sx={{ justifyContent: "flex-start" }}>{person.work_email}</Button>}
            <Button variant="text" component={RouterLink} to="/org-chart" startIcon={<Emoji name="building" size={16} />} sx={{ justifyContent: "flex-start" }}>{t("people.profile.see_org_chart")}</Button>
          </Stack>
        </Stack>
      </Card>

      <Tabs value={tab} onChange={(_e, v: TabKey) => { const p = new URLSearchParams(params); p.set("tab", v); setParams(p, { replace: true }); }}
        variant="scrollable" allowScrollButtonsMobile aria-label={t("people.profile.tabs")} sx={{ mb: 2.5 }}>
        {TABS.map((k) => <Tab key={k} value={k} label={t(`people.profile.tab.${k}`)} id={`tab-${k}`} aria-controls={`panel-${k}`} />)}
      </Tabs>

      <Box role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "personal" && (
          <Grid container spacing={2.5}>
            <Grid size={{ xs: 12, lg: 7 }}>
              <SectionCard emoji="id_card" title={t("people.personal.basic")}>
                <Grid container spacing={2}>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.first_name")} value={person.first_name} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.last_name")} value={person.last_name} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.preferred_name")} value={person.preferred_name} tip={<InfoTip text={t("people.field.preferred_name_tip")} />} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.pronouns")} value={person.pronouns} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.dob")} value={person.dob ? fmt(person.dob) : null} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.gender")} value={person.gender} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.marital_status")} value={person.marital_status} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.nationality")} value={person.nationality} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.blood_group")} value={person.blood_group} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.worker_type")} value={t(`people.worker.${person.worker_type}`)} tip={<InfoTip text={t("people.field.worker_type_tip")} />} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.work_email")} value={person.work_email} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.personal_email")} value={person.personal_email} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.phone")} value={person.personal_phone} /></Grid>
                  <Grid size={{ xs: 12, sm: 6 }}><Field label={t("people.field.joined")} value={person.joined_on ? fmt(person.joined_on) : null} /></Grid>
                </Grid>
                <Typography sx={{ fontSize: 12, color: f.muted, mt: 2, display: "flex", alignItems: "center", gap: 0.5 }}>
                  <Emoji name="lock" size={14} />{t("people.personal.read_only")}
                </Typography>
              </SectionCard>
            </Grid>
            <Grid size={{ xs: 12, lg: 5 }}>
              <SectionCard emoji="shield" title={<>{t("people.sensitive.title")}<InfoTip text={t("people.sensitive.audit_tip")} /></>}>
                <Stack spacing={1.5}>
                  {SENSITIVE.filter((k) => sensitive[k]).map((k) => (
                    <SensitiveField key={k} employeeId={person.id} field={k} present={sensitive[k]!.present} masked={sensitive[k]!.masked}
                      canReveal={data.can.reveal} canEdit={data.can.edit_sensitive}
                      onSaved={() => { setNotice({ tone: "ok", text: t("people.sensitive.saved", { field: t(`people.sensitive.${k}`) }) }); load(); }} />
                  ))}
                  {person.bank_verification_status && (
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Typography sx={{ fontSize: 13, color: f.muted }}>{t("people.sensitive.bank_check")}</Typography>
                      <StatusChip tone={person.bank_verification_status === "verified" ? "ok" : "muted"} emoji={person.bank_verification_status === "verified" ? "check" : "hourglass"}
                        label={t(`people.bank.${person.bank_verification_status === "verified" ? "verified" : "unverified"}`)} />
                    </Stack>
                  )}
                </Stack>
              </SectionCard>
            </Grid>
            <Grid size={{ xs: 12, md: 6 }}>
              <SectionCard emoji="house" title={t("people.personal.contact")}>
                <Stack spacing={2}>
                  <ListBlock label={t("people.personal.addresses")} items={listOf(person.addresses)} />
                  <ListBlock label={t("people.personal.emergency")} items={listOf(person.emergency_contacts)} />
                  <ListBlock label={t("people.personal.family")} items={listOf(person.family)} />
                </Stack>
              </SectionCard>
            </Grid>
            <Grid size={{ xs: 12, md: 6 }}>
              <SectionCard emoji="graduation" title={t("people.personal.background")}>
                <Stack spacing={2}>
                  <Box>
                    <Typography sx={{ fontSize: 12, fontWeight: 700, color: f.muted, textTransform: "uppercase", letterSpacing: 0.4 }}>{t("people.personal.skills")}</Typography>
                    {skills.length ? (
                      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 0.75 }}>
                        {skills.map((s) => <Chip key={s} size="small" label={s} component={RouterLink} to={`/directory?skill=${encodeURIComponent(s)}`} clickable />)}
                      </Stack>
                    ) : <Typography sx={{ color: f.muted, mt: 0.25 }}>—</Typography>}
                  </Box>
                  <ListBlock label={t("people.personal.education")} items={listOf(person.education)} />
                  <ListBlock label={t("people.personal.prior")} items={listOf(person.prior_employment)} />
                  <ListBlock label={t("people.personal.certifications")} items={listOf(person.certifications)} />
                  <ListBlock label={t("people.personal.languages")} items={listOf(person.languages)} />
                </Stack>
              </SectionCard>
            </Grid>
            {person.custom_fields && Object.keys(person.custom_fields).length > 0 && (
              <Grid size={12}>
                <SectionCard emoji="label" title={t("people.personal.more")}>
                  <Grid container spacing={2}>
                    {Object.entries(person.custom_fields).map(([k, v]) => (
                      <Grid key={k} size={{ xs: 12, sm: 6, lg: 3 }}>
                        <Field label={k.replace(/[_-]+/g, " ")} value={typeof v === "object" && v !== null ? listOf(Array.isArray(v) ? v : [v]).join(", ") : v === null || v === undefined ? null : String(v)} />
                      </Grid>
                    ))}
                  </Grid>
                </SectionCard>
              </Grid>
            )}
          </Grid>
        )}

        {tab === "job" && (
          <Grid container spacing={2.5}>
            <Grid size={{ xs: 12, lg: 8 }}>
              <SectionCard emoji="briefcase" title={t("people.job.title")}
                action={data.can.edit_job ? <Button size="small" variant="outlined" onClick={openChange}>{t("people.profile.request_change")}</Button> : undefined}>
                {!job ? (
                  <EmptyState compact illustration="personal-information" title={t("people.job.none")}
                    action={data.can.edit_job ? <Button variant="contained" onClick={openChange}>{t("people.job.add")}</Button> : undefined} />
                ) : (
                  <Grid container spacing={2}>
                    {([
                      ["designation", job.designation],
                      ["department", job.department],
                      ["location", job.location],
                      ["manager", job.manager_id && job.manager_name ? <Link component={RouterLink} to={`/employees/${job.manager_id}`}>{job.manager_name}</Link> : null],
                      ["grade", job.grade],
                      ["work_mode", job.work_mode ? t(`people.work_mode.${job.work_mode}`) : null],
                      ["employment_type", job.employment_type],
                      ["cost_center", job.cost_center],
                      ["probation_end", job.probation_end ? fmt(job.probation_end) : null],
                      ["confirmation_date", job.confirmation_date ? fmt(job.confirmation_date) : null],
                      ["notice_period", job.notice_period_days != null ? t("people.job.days", { count: job.notice_period_days }) : null],
                      ["since", job.effective_from ? t("people.job.since_value", { date: fmt(job.effective_from), what: eventLabel(t, job.event_type) }) : null],
                    ] as [string, React.ReactNode][]).map(([k, v]) => (
                      <Grid key={k} size={{ xs: 12, sm: 6, xl: 4 }}>
                        <Field label={t(`people.field.${k}`)} value={v}
                          tip={["grade", "cost_center", "probation_end"].includes(k) ? <InfoTip text={t(`people.field.${k}_tip`)} /> : undefined}
                          badge={pendingFields.has(k) ? <PendingBadge /> : undefined} />
                      </Grid>
                    ))}
                  </Grid>
                )}
                <Typography sx={{ fontSize: 12, color: f.muted, mt: 2 }}>{t("people.job.how_changes_work")}</Typography>
              </SectionCard>
            </Grid>
            <Grid size={{ xs: 12, lg: 4 }}>
              <SectionCard emoji="hourglass" title={t("people.pending.title", { count: pending.length })}>
                {pending.length === 0 ? (
                  <Typography sx={{ color: f.muted }}>{t("people.pending.none")}</Typography>
                ) : (
                  <Stack spacing={1.25}>
                    {pending.map((p) => (
                      <Box key={p.id} sx={{ p: 1.5, borderRadius: "12px", bgcolor: f.sunSoft }}>
                        <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
                          <Typography sx={{ fontWeight: 700 }}>{eventLabel(t, p.event_type)}</Typography>
                          <PendingBadge />
                        </Stack>
                        <Typography sx={{ fontSize: 13, mt: 0.5 }}>
                          {t("people.pending.what", { fields: p.changes.map((c) => t(`people.field.${CHANGE_FIELD[c] ?? c}`)).join(", ") || "—", date: fmt(p.effective_from) })}
                        </Typography>
                        <Typography sx={{ fontSize: 12, color: f.muted, mt: 0.25 }}>{t("people.pending.by", { who: p.requested_by ?? "—", date: fmt(p.requested_at, true) })}</Typography>
                      </Box>
                    ))}
                    <Button variant="text" component={RouterLink} to="/approvals">{t("people.pending.open_approvals")}</Button>
                  </Stack>
                )}
              </SectionCard>
            </Grid>
          </Grid>
        )}

        {tab === "documents" && (
          <Stack spacing={2.5}>
            <DocumentsPanel employeeId={person.id} canAdd={data.can.add_document} />
          </Stack>
        )}

        {tab === "history" && (
          <Stack spacing={2.5}>
            {data.can.view_history ? <HistoryPanel key={historyKey} employeeId={person.id} /> : (
              <Card sx={{ p: 2 }}><Typography sx={{ color: f.muted }}>{t("people.history.no_access")}</Typography></Card>
            )}
            {data.can.letters_view && (
              <>
                <Typography variant="h5" component="h2" sx={{ display: "flex", alignItems: "center", gap: 1, fontWeight: 800 }}>
                  <Emoji name="page" size={22} />{t("people.letters.title")}
                </Typography>
                <LettersPanel employeeId={person.id} canCreate={data.can.letters_create} context={letterContext} />
              </>
            )}
          </Stack>
        )}
      </Box>

      <JobChangeDialog
        open={changeOpen} employeeId={person.id} job={job} filters={filters} people={people}
        onClose={() => setChangeOpen(false)}
        onDone={(applied) => {
          setChangeOpen(false);
          setNotice(applied ? { tone: "ok", text: t("people.jobchange.applied") } : { tone: "sun", text: t("people.jobchange.pending") });
          setHistoryKey((k) => k + 1);
          load();
        }}
      />
    </Box>
  );
}

function ListBlock({ label, items }: { label: string; items: string[] }) {
  const f = useTheme().palette.fresh;
  return (
    <Box>
      <Typography sx={{ fontSize: 12, fontWeight: 700, color: f.muted, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</Typography>
      {items.length ? (
        <Box component="ul" sx={{ m: 0, mt: 0.5, pl: 2.5 }}>
          {items.map((i, n) => <Typography component="li" key={n} sx={{ fontWeight: 500 }}>{i}</Typography>)}
        </Box>
      ) : <Typography sx={{ color: f.muted, mt: 0.25 }}>—</Typography>}
    </Box>
  );
}
