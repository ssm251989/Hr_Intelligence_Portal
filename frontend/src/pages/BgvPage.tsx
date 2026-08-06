import { useEffect, useRef, useState } from "react";
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

import { applicationsApi, bgvApi, candidatesApi, extractErrorMessage, jobsApi } from "../api/client";
import type { ApplicationRead, BgvClearRequest, BgvDocumentRead, CandidateRead, JobRoleRead } from "../api/types";
import { BGV_DOC_TYPES } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import ConfirmDialog from "../components/ConfirmDialog";
import StatusChip from "../components/StatusChip";

const RELEVANT_STATUSES = ["salary_approved", "bgv_requested", "bgv_pending", "bgv_cleared", "bgv_rejected"];
const IN_PROGRESS_STATUSES = ["bgv_requested", "bgv_pending"];

function BgvUploadForm({ onUpload }: { onUpload: (docType: string, file: File) => Promise<void> }) {
  const { can } = useAuth();
  const canEdit = can(ROLE_MATRIX.bgvWrite);
  const [docType, setDocType] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  if (!canEdit) {
    return null;
  }

  const handleUpload = async () => {
    if (!docType || !file) {
      setError("Choose a document type and a file");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      await onUpload(docType, file);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to upload document"));
    } finally {
      setUploading(false);
    }
  };

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
        <TextField select label="Document type" value={docType} onChange={(e) => setDocType(e.target.value)} size="small" sx={{ minWidth: 160 }}>
          {BGV_DOC_TYPES.map((type) => (
            <MenuItem key={type} value={type}>
              {type}
            </MenuItem>
          ))}
        </TextField>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.jpg,.jpeg,.png"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <Button size="small" variant="outlined" onClick={handleUpload} disabled={uploading}>
          {uploading ? "Uploading..." : "Upload Document"}
        </Button>
      </Stack>
    </Box>
  );
}

function BgvClearForm({ onSubmit }: { onSubmit: (payload: BgvClearRequest) => Promise<void> }) {
  const { can } = useAuth();
  const canEdit = can(ROLE_MATRIX.bgvWrite);
  const [decision, setDecision] = useState<"clear" | "reject" | "">("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  if (!canEdit) {
    return null;
  }

  const doSubmit = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ decision: decision as "clear" | "reject", notes: notes || null });
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to record BGV decision"));
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = () => {
    if (!decision) {
      setError("Choose clear or reject");
      return;
    }
    setConfirmOpen(true);
  };

  const handleConfirm = async () => {
    setConfirmOpen(false);
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
      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
        <TextField
          select
          label="Decision"
          value={decision}
          onChange={(e) => setDecision(e.target.value as "clear" | "reject" | "")}
          size="small"
          sx={{ minWidth: 140 }}
        >
          <MenuItem value="">—</MenuItem>
          <MenuItem value="clear">Clear</MenuItem>
          <MenuItem value="reject">Reject</MenuItem>
        </TextField>
        <TextField label="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} size="small" sx={{ minWidth: 220 }} />
        <Button size="small" variant="contained" onClick={handleSubmit} disabled={saving}>
          {saving ? "Saving..." : "Submit Decision"}
        </Button>
      </Stack>

      <ConfirmDialog
        open={confirmOpen}
        title={decision === "reject" ? "Reject BGV?" : "Clear BGV?"}
        message={
          decision === "reject"
            ? "Reject this candidate's background verification? This cannot be undone."
            : "Clear this candidate's background verification? This moves them forward to offer generation and cannot be undone."
        }
        confirmLabel={decision === "reject" ? "Reject" : "Clear"}
        destructive={decision === "reject"}
        confirming={saving}
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </Box>
  );
}

export default function BgvPage() {
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.bgvWrite);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [applications, setApplications] = useState<ApplicationRead[]>([]);
  const [candidates, setCandidates] = useState<Record<string, CandidateRead>>({});
  const [documents, setDocuments] = useState<Record<string, BgvDocumentRead[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);
  const [candidatesLoadFailed, setCandidatesLoadFailed] = useState(false);

  useEffect(() => {
    jobsApi
      .list()
      .then(setJobs)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load jobs")));
    candidatesApi
      .list()
      .then((data) => setCandidates(Object.fromEntries(data.map((c) => [c.id, c]))))
      .catch(() => setCandidatesLoadFailed(true));
  }, []);

  const loadJobData = async (jobId: string) => {
    setLoading(true);
    setError(null);
    try {
      const allApplications = await applicationsApi.list(jobId);
      const relevant = allApplications.filter((app) => RELEVANT_STATUSES.includes(app.status));
      setApplications(relevant);

      const withDocs = relevant.filter((app) => app.status !== "salary_approved");
      const docLists = await Promise.all(withDocs.map((app) => bgvApi.listDocuments(app.id)));
      const byApplication: Record<string, BgvDocumentRead[]> = {};
      withDocs.forEach((app, idx) => {
        byApplication[app.id] = docLists[idx];
      });
      setDocuments(byApplication);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load BGV data"));
    } finally {
      setLoading(false);
    }
  };

  const handleJobChange = (jobId: string) => {
    setSelectedJobId(jobId);
    if (jobId) loadJobData(jobId);
    else {
      setApplications([]);
      setDocuments({});
    }
  };

  const handleRequestBgv = async (applicationId: string) => {
    setActionId(applicationId);
    setError(null);
    try {
      const updated = await bgvApi.request(applicationId);
      setApplications((prev) => prev.map((app) => (app.id === applicationId ? updated : app)));
      setDocuments((prev) => ({ ...prev, [applicationId]: [] }));
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to request BGV"));
    } finally {
      setActionId(null);
    }
  };

  const handleUpload = async (applicationId: string, docType: string, file: File) => {
    const doc = await bgvApi.uploadDocument(applicationId, docType, file);
    setDocuments((prev) => ({ ...prev, [applicationId]: [...(prev[applicationId] || []), doc] }));
    const updated = await applicationsApi.list(selectedJobId);
    setApplications(updated.filter((app) => RELEVANT_STATUSES.includes(app.status)));
  };

  const handleValidateDoc = async (applicationId: string, docId: string) => {
    setActionId(docId);
    setError(null);
    try {
      const updated = await bgvApi.validateDocument(applicationId, docId);
      setDocuments((prev) => ({
        ...prev,
        [applicationId]: (prev[applicationId] || []).map((doc) => (doc.id === docId ? updated : doc)),
      }));
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to validate document"));
    } finally {
      setActionId(null);
    }
  };

  const handleClear = async (applicationId: string, payload: BgvClearRequest) => {
    const updated = await bgvApi.clear(applicationId, payload);
    setApplications((prev) => prev.map((app) => (app.id === applicationId ? updated : app)));
  };

  const candidateLabel = (candidateId: string) => {
    const candidate = candidates[candidateId];
    return candidate?.parsed_fields?.full_name || candidate?.full_name || `Candidate ${candidateId.slice(0, 8)}`;
  };

  return (
    <Box>
      <Typography variant="h4" mb={3}>
        Background Verification
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
      {candidatesLoadFailed && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Couldn't load candidate names — candidates below may show as raw IDs.
        </Alert>
      )}

      {!selectedJobId ? (
        <Typography color="text.secondary">Select a job to manage background verification.</Typography>
      ) : loading ? (
        <CircularProgress />
      ) : applications.length === 0 ? (
        <Typography color="text.secondary">No applications in the BGV pipeline for this job.</Typography>
      ) : (
        <Stack spacing={2}>
          {applications.map((app) => {
            const docs = documents[app.id] || [];
            return (
              <Card key={app.id} variant="outlined">
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                    <Typography variant="h6">{candidateLabel(app.candidate_id)}</Typography>
                    <StatusChip status={app.status} />
                  </Stack>

                  {canWrite && app.status === "salary_approved" && (
                    <Box mt={2}>
                      <Button
                        size="small"
                        variant="contained"
                        onClick={() => handleRequestBgv(app.id)}
                        disabled={actionId === app.id}
                      >
                        {actionId === app.id ? "Requesting..." : "Request BGV"}
                      </Button>
                    </Box>
                  )}

                  {(IN_PROGRESS_STATUSES.includes(app.status) || app.status === "bgv_cleared" || app.status === "bgv_rejected") && (
                    <Box mt={2}>
                      <Divider sx={{ mb: 1.5 }} />
                      {IN_PROGRESS_STATUSES.includes(app.status) && (
                        <Box mb={2}>
                          <BgvUploadForm onUpload={(docType, file) => handleUpload(app.id, docType, file)} />
                        </Box>
                      )}

                      {docs.length === 0 ? (
                        <Typography variant="body2" color="text.secondary">
                          No documents uploaded yet.
                        </Typography>
                      ) : (
                        <Stack spacing={1.5}>
                          {docs.map((doc) => (
                            <Box key={doc.id} p={1.5} bgcolor="action.hover" borderRadius={1}>
                              <Stack direction="row" justifyContent="space-between" alignItems="center">
                                <Typography variant="body2" fontWeight="bold">
                                  {doc.doc_type}
                                </Typography>
                                <Stack direction="row" spacing={1} alignItems="center">
                                  <StatusChip status={doc.validation_status} />
                                  {canWrite && IN_PROGRESS_STATUSES.includes(app.status) && (
                                    <Button
                                      size="small"
                                      variant="outlined"
                                      onClick={() => handleValidateDoc(app.id, doc.id)}
                                      disabled={actionId === doc.id}
                                    >
                                      {actionId === doc.id ? "Validating..." : "Validate"}
                                    </Button>
                                  )}
                                </Stack>
                              </Stack>
                              {doc.validator_output && (
                                <Box mt={1}>
                                  <Typography variant="caption" color="text.secondary">
                                    Detected: {doc.validator_output.doc_type_detected} · Matches expected:{" "}
                                    {doc.validator_output.matches_expected_type ? "yes" : "no"}
                                  </Typography>
                                  <Typography variant="body2">
                                    {[
                                      doc.validator_output.extracted_fields.name,
                                      doc.validator_output.extracted_fields.id_number,
                                      doc.validator_output.extracted_fields.date,
                                    ]
                                      .filter(Boolean)
                                      .join(" · ") || "No fields extracted"}
                                  </Typography>
                                  {doc.validator_output.issues.length > 0 && (
                                    <Typography variant="body2" color="warning.main">
                                      Issues: {doc.validator_output.issues.join("; ")}
                                    </Typography>
                                  )}
                                </Box>
                              )}
                            </Box>
                          ))}
                        </Stack>
                      )}

                      {IN_PROGRESS_STATUSES.includes(app.status) && (
                        <BgvClearForm onSubmit={(payload) => handleClear(app.id, payload)} />
                      )}
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
