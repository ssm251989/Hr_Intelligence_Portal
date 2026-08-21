import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CircularProgress from "@mui/material/CircularProgress";
import Divider from "@mui/material/Divider";
import MuiLink from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { Link as RouterLink, useSearchParams } from "react-router-dom";

import { ApiError, applicationsApi, candidatesApi, extractErrorMessage, integrationsApi, jobsApi, offersApi } from "../api/client";
import type { ApplicationRead, CandidateRead, JobRoleRead, OfferGenerateRequest, OfferRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import ConfirmDialog from "../components/ConfirmDialog";
import RefreshButton from "../components/RefreshButton";
import StatusChip from "../components/StatusChip";

const RELEVANT_STATUSES = ["bgv_cleared", "offer_sent", "onboarding_started", "onboarding_completed"];

function OfferGenerateForm({
  onSubmit,
  docusignConnected,
  candidateEmail,
}: {
  onSubmit: (payload: OfferGenerateRequest) => Promise<void>;
  docusignConnected: boolean | null;
  candidateEmail?: string | null;
}) {
  const { can } = useAuth();
  const canEdit = can(ROLE_MATRIX.offersWrite);
  const [startDate, setStartDate] = useState("");
  const [reportingManagerName, setReportingManagerName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canEdit) {
    return null;
  }

  const handleSubmit = async () => {
    if (!startDate) {
      setError("Pick a start date");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ start_date: startDate, reporting_manager_name: reportingManagerName || null });
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to generate offer"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box mt={2}>
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      {docusignConnected === true && candidateEmail && (
        <Alert severity="info" sx={{ mb: 1.5 }}>
          DocuSign is connected — a real signature envelope will be sent to {candidateEmail} once this offer
          is generated.
        </Alert>
      )}
      {docusignConnected === true && !candidateEmail && (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          DocuSign is connected, but this candidate has no email on file, so a real envelope can't be sent —
          this offer will need to be marked as signed manually.
        </Alert>
      )}
      {docusignConnected === false && (
        <Alert severity="info" sx={{ mb: 1.5 }}>
          DocuSign isn't connected for your account, so this offer will need to be marked as signed manually.{" "}
          <MuiLink component={RouterLink} to="/settings">
            Connect DocuSign
          </MuiLink>
          .
        </Alert>
      )}
      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
        <TextField
          label="Start date"
          type="date"
          required
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          InputLabelProps={{ shrink: true }}
          size="small"
        />
        <TextField
          label="Reporting manager (optional)"
          value={reportingManagerName}
          onChange={(e) => setReportingManagerName(e.target.value)}
          size="small"
          sx={{ minWidth: 220 }}
        />
        <Button size="small" variant="contained" onClick={handleSubmit} disabled={saving}>
          {saving ? "Generating..." : "Generate Offer"}
        </Button>
      </Stack>
    </Box>
  );
}

function MarkSignedForm({ onSubmit }: { onSubmit: (envelopeId: string | null) => Promise<void> }) {
  const { can } = useAuth();
  const canEdit = can(ROLE_MATRIX.offersWrite);
  const [envelopeId, setEnvelopeId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  if (!canEdit) {
    return null;
  }

  const handleSubmit = async () => {
    setConfirmOpen(false);
    setSaving(true);
    setError(null);
    try {
      await onSubmit(envelopeId || null);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to mark offer signed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box mt={2}>
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      <Typography variant="caption" color="text.secondary" display="block" mb={1}>
        No real DocuSign envelope was sent for this offer — paste an envelope ID here manually if one exists
        from whatever channel collected the signature, or leave blank.
      </Typography>
      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
        <TextField
          label="DocuSign envelope ID (optional)"
          value={envelopeId}
          onChange={(e) => setEnvelopeId(e.target.value)}
          size="small"
          sx={{ minWidth: 240 }}
        />
        <Button size="small" variant="contained" onClick={() => setConfirmOpen(true)} disabled={saving}>
          {saving ? "Saving..." : "Mark Signed"}
        </Button>
      </Stack>

      <ConfirmDialog
        open={confirmOpen}
        title="Mark offer as signed?"
        message="This manually records the offer as signed without verifying a real signature. Only do this if you've confirmed the candidate signed through some other channel."
        confirmLabel="Mark Signed"
        confirming={saving}
        onConfirm={handleSubmit}
        onCancel={() => setConfirmOpen(false)}
      />
    </Box>
  );
}

function CheckSigningStatusButton({
  envelopeId,
  onCheck,
}: {
  envelopeId: string | null | undefined;
  onCheck: () => Promise<void>;
}) {
  const { can } = useAuth();
  const canEdit = can(ROLE_MATRIX.offersWrite);
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState<{ severity: "info" | "error"; text: string } | null>(null);

  if (!canEdit) {
    return null;
  }

  const handleCheck = async () => {
    setChecking(true);
    setMessage(null);
    try {
      await onCheck();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Envelope exists but isn't fully signed yet -- an expected, non-error outcome.
        setMessage({ severity: "info", text: extractErrorMessage(err, "Envelope is not yet signed") });
      } else {
        setMessage({
          severity: "error",
          text: extractErrorMessage(err, "Failed to check signing status"),
        });
      }
    } finally {
      setChecking(false);
    }
  };

  return (
    <Box mt={2}>
      {message && (
        <Alert severity={message.severity} sx={{ mb: 1.5 }}>
          {message.text}
        </Alert>
      )}
      <Typography variant="caption" color="text.secondary" display="block" mb={1}>
        A real DocuSign envelope ({envelopeId}) was sent for signature — check its live status via DocuSign
        instead of marking this signed manually.
      </Typography>
      <Button size="small" variant="contained" onClick={handleCheck} disabled={checking}>
        {checking ? "Checking..." : "Check Signing Status"}
      </Button>
    </Box>
  );
}

export default function OffersPage() {
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.offersWrite);
  const [searchParams] = useSearchParams();
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [applications, setApplications] = useState<ApplicationRead[]>([]);
  const [candidates, setCandidates] = useState<Record<string, CandidateRead>>({});
  const [offers, setOffers] = useState<Record<string, OfferRead>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);
  const [docusignConnected, setDocusignConnected] = useState<boolean | null>(null);
  const [candidatesLoadFailed, setCandidatesLoadFailed] = useState(false);
  const [docusignStatusLoadFailed, setDocusignStatusLoadFailed] = useState(false);
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
    // Tells the generate-offer form whether the caller (whoever ends up generating the
    // offer) has DocuSign connected. A failure here must be visible -- otherwise the
    // "mark signed manually" guidance can silently show the wrong thing.
    const docusignPromise = integrationsApi
      .docusignStatus()
      .then((status) => setDocusignConnected(status.connected))
      .catch(() => setDocusignStatusLoadFailed(true));
    return Promise.all([jobsPromise, candidatesPromise, docusignPromise]);
  };

  useEffect(() => {
    loadInitial();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // No filters/search/pagination on this page to reset (its only real "filter" is which
  // job is selected, deliberately left alone -- clearing it would drop the recruiter out
  // of whatever job they were actively reviewing) -- Refresh just re-fetches the job
  // dropdown/candidate names/DocuSign status plus the currently selected job's own data,
  // if any.
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

      const withOffers = relevant.filter((app) => app.status !== "bgv_cleared");
      const offerResults = await Promise.all(withOffers.map((app) => offersApi.get(app.id)));
      const byApplication: Record<string, OfferRead> = {};
      withOffers.forEach((app, idx) => {
        byApplication[app.id] = offerResults[idx];
      });
      setOffers(byApplication);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load offer data"));
    } finally {
      setLoading(false);
    }
  };

  const handleJobChange = (jobId: string) => {
    setSelectedJobId(jobId);
    if (jobId) loadJobData(jobId);
    else {
      setApplications([]);
      setOffers({});
    }
  };

  // Deep-link support for the Candidate Detail page's "Move Stage" -> Generate Offer
  // action (see app/candidates/pipeline_actions.py's "navigate" actions).
  useEffect(() => {
    const jobId = searchParams.get("jobId");
    if (jobId && jobId !== selectedJobId && jobs.some((job) => job.id === jobId)) {
      handleJobChange(jobId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs, searchParams]);

  const handleGenerate = async (applicationId: string, payload: OfferGenerateRequest) => {
    const offer = await offersApi.generate(applicationId, payload);
    setOffers((prev) => ({ ...prev, [applicationId]: offer }));
    await loadJobData(selectedJobId);
  };

  const handleMarkSigned = async (applicationId: string, envelopeId: string | null) => {
    const offer = await offersApi.markSigned(applicationId, { docusign_envelope_id: envelopeId });
    setOffers((prev) => ({ ...prev, [applicationId]: offer }));
    await loadJobData(selectedJobId);
  };

  const handleCompleteOnboarding = async (applicationId: string) => {
    setActionId(applicationId);
    setError(null);
    try {
      const offer = await offersApi.completeOnboarding(applicationId);
      setOffers((prev) => ({ ...prev, [applicationId]: offer }));
      await loadJobData(selectedJobId);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to complete onboarding"));
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
        <Typography variant="h4">Offers & Onboarding</Typography>
        <RefreshButton loading={refreshing} onRefresh={handleRefresh} />
      </Stack>

      <Card variant="outlined" sx={{ mb: 3 }}>
        <CardContent>
          <TextField select label="Select Job" value={selectedJobId} onChange={(e) => handleJobChange(e.target.value)} fullWidth>
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
      {docusignStatusLoadFailed && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Couldn't verify your DocuSign connection status — the guidance shown below may be inaccurate.
        </Alert>
      )}

      {!selectedJobId ? (
        <Typography color="text.secondary">Select a job to manage offers and onboarding.</Typography>
      ) : loading ? (
        <CircularProgress />
      ) : applications.length === 0 ? (
        <Typography color="text.secondary">No applications in the offer/onboarding pipeline for this job.</Typography>
      ) : (
        <Stack spacing={2}>
          {applications.map((app) => {
            const offer = offers[app.id];
            return (
              <Card key={app.id} variant="outlined">
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                    <Typography variant="h6">{candidateLabel(app.candidate_id)}</Typography>
                    <StatusChip status={app.status} />
                  </Stack>

                  {app.status === "bgv_cleared" && (
                    <OfferGenerateForm
                      onSubmit={(payload) => handleGenerate(app.id, payload)}
                      docusignConnected={docusignConnected}
                      candidateEmail={candidates[app.candidate_id]?.email}
                    />
                  )}

                  {offer && (
                    <Box mt={2}>
                      <Divider sx={{ mb: 1.5 }} />
                      <Typography variant="body2" color="text.secondary">
                        Signed: {offer.signed ? "yes" : "no"}
                        {offer.docusign_envelope_id &&
                          ` · Envelope: ${offer.docusign_envelope_id} (${offer.docusign_sender_id ? "DocuSign" : "manual"})`}
                        {" · "}Onboarding: {offer.onboarding_status}
                      </Typography>
                      {offer.offer_letter_text && (
                        <Box mt={1.5} p={1.5} bgcolor="action.hover" borderRadius={1}>
                          <Typography variant="subtitle2" gutterBottom>
                            Offer Letter
                          </Typography>
                          <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", fontFamily: "monospace" }}>
                            {offer.offer_letter_text}
                          </Typography>
                        </Box>
                      )}
                    </Box>
                  )}

                  {app.status === "offer_sent" && offer?.docusign_sender_id && (
                    <CheckSigningStatusButton
                      envelopeId={offer.docusign_envelope_id}
                      onCheck={() => handleMarkSigned(app.id, null)}
                    />
                  )}
                  {app.status === "offer_sent" && !offer?.docusign_sender_id && (
                    <MarkSignedForm onSubmit={(envelopeId) => handleMarkSigned(app.id, envelopeId)} />
                  )}

                  {canWrite && app.status === "onboarding_started" && (
                    <Box mt={2}>
                      <Button
                        size="small"
                        variant="contained"
                        onClick={() => handleCompleteOnboarding(app.id)}
                        disabled={actionId === app.id}
                      >
                        {actionId === app.id ? "Completing..." : "Complete Onboarding"}
                      </Button>
                    </Box>
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
