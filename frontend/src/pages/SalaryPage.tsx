import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Grid from "@mui/material/Grid";
import InputAdornment from "@mui/material/InputAdornment";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { applicationsApi, candidatesApi, extractErrorMessage, jobsApi, salaryApi } from "../api/client";
import type {
  ApplicationRead,
  CandidateRead,
  JobRoleRead,
  SalaryApprovalRequest,
  SalaryStatusResponse,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import ConfirmDialog from "../components/ConfirmDialog";
import RefreshButton from "../components/RefreshButton";
import { Figure, Inset, JobPickerCard, PersonHeader, useMoney } from "../components/offers/shared";
import SalaryBandBar, { bandPosition } from "../components/salary/SalaryBandBar";
import { useT } from "../i18n";
import { EmptyState, Emoji, FriendlyError, InfoTip, PageHeader, StatTile } from "../ui-kit";

const RELEVANT_STATUSES = [
  "hr_selected",
  "interview_selected",
  "salary_ok",
  "salary_above_band",
  "salary_approved",
  "salary_rejected",
];
const VALIDATABLE_STATUSES = ["hr_selected", "interview_selected"];

const num = (v: unknown): number | null => (v == null || v === "" || Number.isNaN(Number(v)) ? null : Number(v));

// L-B2: one-click approval -- "Approve" / "Decline" buttons (was a Decision dropdown +
// Submit). The optional override amount and the confirm-before-decline step are unchanged.
function SalaryApprovalForm({
  application,
  onSubmit,
}: {
  application: ApplicationRead;
  onSubmit: (payload: SalaryApprovalRequest) => Promise<void>;
}) {
  const { can } = useAuth();
  const t = useT();
  const f = useTheme().palette.fresh;
  const money = useMoney();
  const canEdit = can(ROLE_MATRIX.salaryWrite);
  const [approvedSalary, setApprovedSalary] = useState(
    application.expected_salary != null ? String(application.expected_salary) : ""
  );
  const [saving, setSaving] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmRejectOpen, setConfirmRejectOpen] = useState(false);

  if (!canEdit) {
    return (
      <Inset>
        <Stack direction="row" spacing={1} alignItems="center">
          <Emoji name="hourglass" size={18} />
          <Typography sx={{ fontSize: 14 }}>{t("salary.approval.waiting")}</Typography>
        </Stack>
      </Inset>
    );
  }

  const doSubmit = async (decision: "approve" | "reject") => {
    setSaving(decision);
    setError(null);
    try {
      await onSubmit({
        decision,
        approved_salary: decision === "approve" && approvedSalary ? Number(approvedSalary) : null,
      });
    } catch (err) {
      setError(extractErrorMessage(err, t("salary.error.decision")));
    } finally {
      setSaving(null);
    }
  };

  const handleConfirmReject = async () => {
    setConfirmRejectOpen(false);
    await doSubmit("reject");
  };

  return (
    <Inset title={<><Emoji name="writing_hand" size={16} /> {t("salary.approval.title")}</>}>
      <Typography sx={{ fontSize: 14, color: f.muted, mb: 1.5 }}>{t("salary.approval.intro")}</Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }} flexWrap="wrap" useFlexGap>
        <TextField
          label={t("salary.approval.amount")}
          type="number"
          value={approvedSalary}
          onChange={(e) => setApprovedSalary(e.target.value)}
          size="small"
          sx={{ minWidth: 220 }}
          InputProps={{ endAdornment: <InputAdornment position="end"><InfoTip text={t("salary.approval.amount_tip")} /></InputAdornment> }}
        />
        <Button variant="contained" onClick={() => doSubmit("approve")} disabled={saving !== null} startIcon={<Emoji name="check" size={16} />}>
          {saving === "approve" ? t("salary.approval.approving") : t("salary.approval.approve", { amount: approvedSalary ? money(Number(approvedSalary)) : "" })}
        </Button>
        <Button variant="outlined" color="error" onClick={() => setConfirmRejectOpen(true)} disabled={saving !== null}>
          {saving === "reject" ? t("salary.approval.declining") : t("salary.approval.decline")}
        </Button>
      </Stack>

      <ConfirmDialog
        open={confirmRejectOpen}
        title={t("salary.approval.decline_title")}
        message={t("salary.approval.decline_message")}
        confirmLabel={t("salary.approval.decline")}
        cancelLabel={t("action.cancel")}
        confirming={saving === "reject"}
        onConfirm={handleConfirmReject}
        onCancel={() => setConfirmRejectOpen(false)}
      />
    </Inset>
  );
}

export default function SalaryPage() {
  const { can } = useAuth();
  const t = useT();
  const f = useTheme().palette.fresh;
  const money = useMoney();
  const canWrite = can(ROLE_MATRIX.salaryWrite);
  const [searchParams] = useSearchParams();
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [applications, setApplications] = useState<ApplicationRead[]>([]);
  const [candidates, setCandidates] = useState<Record<string, CandidateRead>>({});
  const [salaryStatus, setSalaryStatus] = useState<Record<string, SalaryStatusResponse>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);
  const [candidatesLoadFailed, setCandidatesLoadFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [bulkChecking, setBulkChecking] = useState(false);

  const loadInitial = () => {
    const jobsPromise = jobsApi
      .list()
      .then(setJobs)
      .catch((err) => setError(extractErrorMessage(err, t("salary.error.jobs"))));
    const candidatesPromise = candidatesApi
      .list()
      .then((data) => setCandidates(Object.fromEntries(data.map((c) => [c.id, c]))))
      .catch(() => setCandidatesLoadFailed(true));
    return Promise.all([jobsPromise, candidatesPromise]);
  };

  useEffect(() => {
    loadInitial();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // No filters/search/pagination on this page to reset (its only real "filter" is which
  // job is selected, deliberately left alone -- clearing it would drop the recruiter out
  // of whatever job they were actively reviewing) -- Refresh just re-fetches the job
  // dropdown/candidate names plus the currently selected job's own data, if any.
  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await loadInitial();
      if (selectedJobId) await loadJobData(selectedJobId);
    } finally {
      setRefreshing(false);
    }
  };

  const loadJobData = async (jobId: string) => {
    setLoading(true);
    setError(null);
    try {
      const allApplications = await applicationsApi.list(jobId);
      const relevant = allApplications.filter((app) => RELEVANT_STATUSES.includes(app.status));
      setApplications(relevant);

      const statuses = await Promise.all(relevant.map((app) => salaryApi.status(app.id)));
      const byApplication: Record<string, SalaryStatusResponse> = {};
      relevant.forEach((app, idx) => {
        byApplication[app.id] = statuses[idx];
      });
      setSalaryStatus(byApplication);
    } catch (err) {
      setError(extractErrorMessage(err, t("salary.error.load")));
    } finally {
      setLoading(false);
    }
  };

  const handleJobChange = (jobId: string) => {
    setSelectedJobId(jobId);
    if (jobId) loadJobData(jobId);
    else {
      setApplications([]);
      setSalaryStatus({});
    }
  };

  // Deep-link support for the Candidate Detail page's "Move Stage" -> Approve/Reject
  // Salary action (see app/candidates/pipeline_actions.py's "navigate" actions).
  useEffect(() => {
    const jobId = searchParams.get("jobId");
    if (jobId && jobId !== selectedJobId && jobs.some((job) => job.id === jobId)) {
      handleJobChange(jobId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs, searchParams]);

  const refreshOne = async (applicationId: string, updated: ApplicationRead) => {
    setApplications((prev) => prev.map((app) => (app.id === applicationId ? updated : app)));
    try {
      const status = await salaryApi.status(applicationId);
      setSalaryStatus((prev) => ({ ...prev, [applicationId]: status }));
    } catch {
      // salary-status is a secondary read; ignore failures here
    }
  };

  const handleValidate = async (applicationId: string) => {
    setActionId(applicationId);
    setError(null);
    try {
      const updated = await salaryApi.validate(applicationId);
      await refreshOne(applicationId, updated);
    } catch (err) {
      setError(extractErrorMessage(err, t("salary.error.validate")));
    } finally {
      setActionId(null);
    }
  };

  // Primary button: the same "Check salary" action, run for everyone still waiting.
  const toCheck = applications.filter((app) => VALIDATABLE_STATUSES.includes(app.status));
  const handleValidateAll = async () => {
    setBulkChecking(true);
    setError(null);
    const failures: string[] = [];
    for (const app of toCheck) {
      try {
        const updated = await salaryApi.validate(app.id);
        await refreshOne(app.id, updated);
      } catch (err) {
        failures.push(`${candidateLabel(app.candidate_id)}: ${extractErrorMessage(err, t("salary.error.validate"))}`);
      }
    }
    if (failures.length) setError(failures.join(" · "));
    setBulkChecking(false);
  };

  const handleApprove = async (applicationId: string, payload: SalaryApprovalRequest) => {
    const updated = await salaryApi.approve(applicationId, payload);
    await refreshOne(applicationId, updated);
  };

  const handleConfirm = async (applicationId: string) => {
    setActionId(applicationId);
    setError(null);
    try {
      const updated = await salaryApi.confirm(applicationId);
      await refreshOne(applicationId, updated);
    } catch (err) {
      setError(extractErrorMessage(err, t("salary.error.confirm")));
    } finally {
      setActionId(null);
    }
  };

  const candidateLabel = (candidateId: string) => {
    const candidate = candidates[candidateId];
    return candidate?.parsed_fields?.full_name || candidate?.full_name || t("offers.shared.candidate_fallback", { id: candidateId.slice(0, 8) });
  };

  const count = (statuses: string[]) => applications.filter((a) => statuses.includes(a.status)).length;
  const stats = [
    { emoji: "hourglass", value: count(VALIDATABLE_STATUSES), key: "salary.stat.to_check", tone: "sky" as const },
    { emoji: "warning", value: count(["salary_above_band"]), key: "salary.stat.above", tone: "coral" as const },
    { emoji: "check", value: count(["salary_ok", "salary_approved"]), key: "salary.stat.ok", tone: "ok" as const },
  ];

  return (
    <Box>
      <PageHeader
        emoji="money"
        title={t("salary.title")}
        purpose={t("salary.purpose")}
        tourKey="salary"
        extra={<RefreshButton loading={refreshing} onRefresh={handleRefresh} label={t("offers.shared.refresh")} />}
        primary={
          canWrite ? (
            <Button variant="contained" onClick={handleValidateAll} disabled={!selectedJobId || toCheck.length === 0 || bulkChecking || loading}>
              {bulkChecking ? t("salary.checking_all") : t("salary.check_all", { count: toCheck.length })}
            </Button>
          ) : undefined
        }
      />

      <JobPickerCard jobs={jobs} value={selectedJobId} onChange={handleJobChange} hint={t("salary.pick_hint")} />

      {error && (
        <Box sx={{ mb: 2 }}>
          <FriendlyError compact what={error} fix={t("salary.error.fix")} onRetry={selectedJobId ? () => loadJobData(selectedJobId) : handleRefresh} />
        </Box>
      )}
      {candidatesLoadFailed && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t("offers.shared.names_failed")}
        </Alert>
      )}

      {!selectedJobId ? (
        <Card>
          <EmptyState illustration="search" title={t("salary.empty.no_job")} hint={t("salary.empty.no_job_hint")} />
        </Card>
      ) : loading ? (
        <Box sx={{ display: "grid", placeItems: "center", py: 6 }} role="status" aria-label={t("offers.shared.loading")}>
          <CircularProgress />
        </Box>
      ) : applications.length === 0 ? (
        <Card>
          <EmptyState illustration="empty" title={t("salary.empty.none")} hint={t("salary.empty.none_hint")} />
        </Card>
      ) : (
        <>
          <Grid container spacing={2} sx={{ mb: 2.5 }}>
            {stats.map((s) => (
              <Grid key={s.key} size={{ xs: 12, sm: 4 }}>
                <StatTile emoji={s.emoji} value={s.value} label={t(s.key, { count: s.value })} tone={s.tone} />
              </Grid>
            ))}
          </Grid>
          <Stack spacing={2}>
            {applications.map((app) => {
              const status = salaryStatus[app.id];
              const expected = num(status?.expected_salary);
              const min = num(status?.salary_band_min);
              const max = num(status?.salary_band_max);
              const approved = num(status?.approved_salary);
              const { pos } = bandPosition(expected, min, max);
              return (
                <Card key={app.id} sx={{ p: 2.5 }}>
                  <PersonHeader name={candidateLabel(app.candidate_id)} status={app.status} />

                  {status && (
                    <>
                      <Box sx={{ mt: 2.5 }}>
                        <SalaryBandBar expected={expected} min={min} max={max} approved={approved} />
                      </Box>
                      <Stack direction="row" spacing={3} flexWrap="wrap" useFlexGap sx={{ mt: 1.5, pt: 1.5, borderTop: `1px solid ${f.line}` }}>
                        <Figure label={t("salary.fig.expected")} value={money(expected)} tip={<InfoTip text={t("salary.fig.ctc_tip")} />} />
                        <Figure
                          label={t("salary.fig.band")}
                          value={min != null && max != null ? t("salary.fig.band_value", { min: money(min), max: money(max) }) : t("salary.fig.no_band")}
                          tip={<InfoTip text={t("salary.fig.band_tip")} />}
                        />
                        {approved != null && <Figure label={t("salary.fig.approved")} value={money(approved)} />}
                      </Stack>
                    </>
                  )}

                  {canWrite && (VALIDATABLE_STATUSES.includes(app.status) || app.status === "salary_ok") && (
                    <Stack direction="row" spacing={1} mt={2} alignItems="center" flexWrap="wrap" useFlexGap>
                      {VALIDATABLE_STATUSES.includes(app.status) && (
                        <Button
                          variant="outlined"
                          onClick={() => handleValidate(app.id)}
                          disabled={actionId === app.id || bulkChecking}
                          startIcon={<Emoji name="magnifier" size={16} />}
                        >
                          {actionId === app.id ? t("salary.validating") : t("salary.validate")}
                        </Button>
                      )}
                      {app.status === "salary_ok" && (
                        <Button
                          variant="contained"
                          onClick={() => handleConfirm(app.id)}
                          disabled={actionId === app.id}
                          startIcon={<Emoji name="check" size={16} />}
                        >
                          {actionId === app.id ? t("salary.confirming") : t("salary.confirm")}
                        </Button>
                      )}
                      <Typography sx={{ fontSize: 13, color: f.muted }}>
                        {VALIDATABLE_STATUSES.includes(app.status) ? t("salary.validate_hint") : pos === "above" ? "" : t("salary.confirm_hint")}
                      </Typography>
                    </Stack>
                  )}

                  {app.status === "salary_above_band" && (
                    <SalaryApprovalForm application={app} onSubmit={(payload) => handleApprove(app.id, payload)} />
                  )}
                </Card>
              );
            })}
          </Stack>
        </>
      )}
    </Box>
  );
}
