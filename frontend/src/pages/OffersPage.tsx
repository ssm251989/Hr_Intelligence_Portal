import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Divider from "@mui/material/Divider";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { ApiError, applicationsApi, candidatesApi, jobsApi, offersApi } from "../api/client";
import type { ApplicationRead, CandidateRead, JobRoleRead, OfferGenerateRequest, OfferRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";

const RELEVANT_STATUSES = ["bgv_cleared", "offer_sent", "onboarding_started", "onboarding_completed"];

function OfferGenerateForm({ onSubmit }: { onSubmit: (payload: OfferGenerateRequest) => Promise<void> }) {
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
      setError(err instanceof ApiError ? String(err.detail) : "Failed to generate offer");
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

  if (!canEdit) {
    return null;
  }

  const handleSubmit = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSubmit(envelopeId || null);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Failed to mark offer signed");
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
        Real DocuSign integration is out of scope for the MVP — paste an envelope ID here manually if one
        exists from whatever channel collected the signature, or leave blank.
      </Typography>
      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
        <TextField
          label="DocuSign envelope ID (optional)"
          value={envelopeId}
          onChange={(e) => setEnvelopeId(e.target.value)}
          size="small"
          sx={{ minWidth: 240 }}
        />
        <Button size="small" variant="contained" onClick={handleSubmit} disabled={saving}>
          {saving ? "Saving..." : "Mark Signed"}
        </Button>
      </Stack>
    </Box>
  );
}

export default function OffersPage() {
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.offersWrite);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [applications, setApplications] = useState<ApplicationRead[]>([]);
  const [candidates, setCandidates] = useState<Record<string, CandidateRead>>({});
  const [offers, setOffers] = useState<Record<string, OfferRead>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);

  useEffect(() => {
    jobsApi
      .list()
      .then(setJobs)
      .catch((err) => setError(err instanceof ApiError ? String(err.detail) : "Failed to load jobs"));
    candidatesApi
      .list()
      .then((data) => setCandidates(Object.fromEntries(data.map((c) => [c.id, c]))))
      .catch(() => undefined);
  }, []);

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
      setError(err instanceof ApiError ? String(err.detail) : "Failed to load offer data");
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
      setError(err instanceof ApiError ? String(err.detail) : "Failed to complete onboarding");
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
      <Typography variant="h4" mb={3}>
        Offers & Onboarding
      </Typography>

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
                    <Chip label={app.status} size="small" />
                  </Stack>

                  {app.status === "bgv_cleared" && (
                    <OfferGenerateForm onSubmit={(payload) => handleGenerate(app.id, payload)} />
                  )}

                  {offer && (
                    <Box mt={2}>
                      <Divider sx={{ mb: 1.5 }} />
                      <Typography variant="body2" color="text.secondary">
                        Signed: {offer.signed ? "yes" : "no"}
                        {offer.docusign_envelope_id && ` · Envelope: ${offer.docusign_envelope_id}`}
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

                  {app.status === "offer_sent" && (
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
