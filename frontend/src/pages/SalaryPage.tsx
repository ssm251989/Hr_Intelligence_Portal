import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CircularProgress from "@mui/material/CircularProgress";
import Divider from "@mui/material/Divider";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

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
import StatusChip from "../components/StatusChip";

const RELEVANT_STATUSES = [
  "hr_selected",
  "interview_selected",
  "salary_ok",
  "salary_above_band",
  "salary_approved",
  "salary_rejected",
];
const VALIDATABLE_STATUSES = ["hr_selected", "interview_selected"];

function SalaryApprovalForm({
  application,
  onSubmit,
}: {
  application: ApplicationRead;
  onSubmit: (payload: SalaryApprovalRequest) => Promise<void>;
}) {
  const { can } = useAuth();
  const canEdit = can(ROLE_MATRIX.salaryWrite);
  const [decision, setDecision] = useState<"approve" | "reject" | "">("");
  const [approvedSalary, setApprovedSalary] = useState(
    application.expected_salary != null ? String(application.expected_salary) : ""
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmRejectOpen, setConfirmRejectOpen] = useState(false);

  if (!canEdit) {
    return null;
  }

  const doSubmit = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        decision: decision as "approve" | "reject",
        approved_salary: decision === "approve" && approvedSalary ? Number(approvedSalary) : null,
      });
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to record decision"));
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = () => {
    if (!decision) {
      setError("Choose approve or reject");
      return;
    }
    if (decision === "reject") {
      setConfirmRejectOpen(true);
      return;
    }
    doSubmit();
  };

  const handleConfirmReject = async () => {
    setConfirmRejectOpen(false);
    await doSubmit();
  };

  return (
    <Box mt={2}>
      <Divider sx={{ mb: 1.5 }} />
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center">
        <TextField
          select
          label="Decision"
          value={decision}
          onChange={(e) => setDecision(e.target.value as "approve" | "reject" | "")}
          size="small"
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="">—</MenuItem>
          <MenuItem value="approve">Approve</MenuItem>
          <MenuItem value="reject">Reject</MenuItem>
        </TextField>
        <TextField
          label="Approved salary (optional override)"
          type="number"
          value={approvedSalary}
          onChange={(e) => setApprovedSalary(e.target.value)}
          size="small"
          disabled={decision !== "approve"}
          sx={{ minWidth: 220 }}
        />
        <Button size="small" variant="contained" onClick={handleSubmit} disabled={saving}>
          {saving ? "Saving..." : "Submit Decision"}
        </Button>
      </Stack>

      <ConfirmDialog
        open={confirmRejectOpen}
        title="Reject salary?"
        message="Reject this candidate's salary? This cannot be undone."
        confirmLabel="Reject"
        confirming={saving}
        onConfirm={handleConfirmReject}
        onCancel={() => setConfirmRejectOpen(false)}
      />
    </Box>
  );
}

export default function SalaryPage() {
  const { can } = useAuth();
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

  const loadInitial = () => {
    const jobsPromise = jobsApi
      .list()
      .then(setJobs)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load jobs")));
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
      setError(extractErrorMessage(err, "Failed to load salary data"));
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
      setError(extractErrorMessage(err, "Failed to validate salary"));
    } finally {
      setActionId(null);
    }
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
      setError(extractErrorMessage(err, "Failed to confirm salary"));
    } finally {
      setActionId(null);
    }
  };

  const candidateLabel = (candidateId: string) => {
    const candidate = candidates[candidateId];
    return candidate?.parsed_fields?.full_name || candidate?.full_name || `Candidate ${candidateId.slice(0, 8)}`;
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4">Salary</Typography>
        <RefreshButton loading={refreshing} onRefresh={handleRefresh} />
      </Stack>

      <Card variant="outlined" sx={{ mb: 3 }}>
        <CardContent>
          <TextField
            select
            label="Select Job"
            value={selectedJobId}
            onChange={(e) => handleJobChange(e.target.value)}
            fullWidth
          >
            {jobs.length === 0 && <MenuItem disabled value="">No jobs available</MenuItem>}
            {jobs.map((job) => (
              <MenuItem key={job.id} value={job.id}>
                {job.title}
              </MenuItem>
            ))}
          </TextField>
        </CardContent>
      </Card>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {candidatesLoadFailed && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Couldn't load candidate names — candidates below may show as raw IDs.
        </Alert>
      )}

      {!selectedJobId ? (
        <Typography color="text.secondary">Select a job to manage salary validation.</Typography>
      ) : loading ? (
        <CircularProgress />
      ) : applications.length === 0 ? (
        <Typography color="text.secondary">No applications awaiting salary validation for this job.</Typography>
      ) : (
        <Stack spacing={2}>
          {applications.map((app) => {
            const status = salaryStatus[app.id];
            return (
              <Card key={app.id} variant="outlined">
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                    <Typography variant="h6">{candidateLabel(app.candidate_id)}</Typography>
                    <StatusChip status={app.status} />
                  </Stack>

                  {status && (
                    <Box mt={1.5}>
                      <Divider sx={{ mb: 1.5 }} />
                      <Typography variant="body2">
                        Expected: {status.expected_salary ?? "—"}
                        {" · "}
                        Band: {status.salary_band_min ?? "—"} - {status.salary_band_max ?? "—"}
                        {status.approved_salary != null && ` · Approved: ${status.approved_salary}`}
                      </Typography>
                    </Box>
                  )}

                  {canWrite && (
                    <Stack direction="row" spacing={1} mt={2}>
                      {VALIDATABLE_STATUSES.includes(app.status) && (
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => handleValidate(app.id)}
                          disabled={actionId === app.id}
                        >
                          {actionId === app.id ? "Validating..." : "Validate Salary"}
                        </Button>
                      )}
                      {app.status === "salary_ok" && (
                        <Button
                          size="small"
                          variant="contained"
                          onClick={() => handleConfirm(app.id)}
                          disabled={actionId === app.id}
                        >
                          {actionId === app.id ? "Confirming..." : "Confirm Salary"}
                        </Button>
                      )}
                    </Stack>
                  )}

                  {app.status === "salary_above_band" && (
                    <SalaryApprovalForm application={app} onSubmit={(payload) => handleApprove(app.id, payload)} />
                  )}
                </CardContent>
              </Card>
            );
          })}
        </Stack>
      )}
    </Box>
  );
}
