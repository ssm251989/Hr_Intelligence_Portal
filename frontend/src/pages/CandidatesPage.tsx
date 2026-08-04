import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { ApiError, applicationsApi, candidatesApi, jobsApi } from "../api/client";
import type { CandidateRead, JobRoleRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";

export default function CandidatesPage() {
  const { can } = useAuth();
  const canUpload = can(ROLE_MATRIX.candidatesWrite);
  const canLink = can(ROLE_MATRIX.applicationsCreate);
  const [candidates, setCandidates] = useState<CandidateRead[]>([]);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [parsingId, setParsingId] = useState<string | null>(null);

  const [linkCandidate, setLinkCandidate] = useState<CandidateRead | null>(null);
  const [linkJobId, setLinkJobId] = useState("");
  const [linkExpectedSalary, setLinkExpectedSalary] = useState("");
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [linkedMessage, setLinkedMessage] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [candidateData, jobData] = await Promise.all([candidatesApi.list(), jobsApi.list()]);
      setCandidates(candidateData);
      setJobs(jobData);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Failed to load candidates");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleUpload = async () => {
    if (!selectedFile) {
      setUploadError("Choose a resume file first");
      return;
    }
    setUploadError(null);
    setUploading(true);
    try {
      const created = await candidatesApi.upload(selectedFile);
      setCandidates((prev) => [created, ...prev]);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setUploadError(err instanceof ApiError ? String(err.detail) : "Failed to upload resume");
    } finally {
      setUploading(false);
    }
  };

  const handleParse = async (candidateId: string) => {
    setParsingId(candidateId);
    setError(null);
    try {
      const updated = await candidatesApi.parseResume(candidateId);
      setCandidates((prev) => prev.map((c) => (c.id === candidateId ? updated : c)));
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Failed to parse resume");
    } finally {
      setParsingId(null);
    }
  };

  const openLinkDialog = (candidate: CandidateRead) => {
    setLinkCandidate(candidate);
    setLinkJobId("");
    setLinkExpectedSalary("");
    setLinkError(null);
  };

  const handleLink = async () => {
    if (!linkCandidate) return;
    if (!linkJobId) {
      setLinkError("Select a job");
      return;
    }
    setLinking(true);
    setLinkError(null);
    try {
      await applicationsApi.create({
        job_role_id: linkJobId,
        candidate_id: linkCandidate.id,
        expected_salary: linkExpectedSalary ? Number(linkExpectedSalary) : null,
      });
      const job = jobs.find((j) => j.id === linkJobId);
      setLinkedMessage(`Linked ${linkCandidate.full_name || "candidate"} to ${job?.title ?? "job"}`);
      setLinkCandidate(null);
    } catch (err) {
      setLinkError(err instanceof ApiError ? String(err.detail) : "Failed to link candidate to job");
    } finally {
      setLinking(false);
    }
  };

  return (
    <Box>
      <Typography variant="h4" mb={3}>
        Candidates
      </Typography>

      {canUpload && (
        <Card variant="outlined" sx={{ mb: 3 }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Upload Resume
            </Typography>
            {uploadError && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {uploadError}
              </Alert>
            )}
            <Stack direction="row" spacing={2} alignItems="center">
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx"
                onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
              />
              <Button variant="contained" onClick={handleUpload} disabled={uploading}>
                {uploading ? "Uploading..." : "Upload"}
              </Button>
            </Stack>
            <Typography variant="caption" color="text.secondary">
              PDF or DOCX only.
            </Typography>
          </CardContent>
        </Card>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {linkedMessage && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setLinkedMessage(null)}>
          {linkedMessage}
        </Alert>
      )}

      {loading ? (
        <CircularProgress />
      ) : candidates.length === 0 ? (
        <Typography color="text.secondary">No candidates yet. Upload a resume to get started.</Typography>
      ) : (
        <Grid container spacing={2}>
          {candidates.map((candidate) => {
            const parsed = candidate.parsed_fields;
            return (
              <Grid key={candidate.id} size={{ xs: 12, md: 6 }}>
                <Card variant="outlined">
                  <CardContent>
                    <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                      <Box>
                        <Typography variant="h6">
                          {parsed?.full_name || candidate.full_name || "Unnamed candidate"}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {[parsed?.email || candidate.email, parsed?.phone || candidate.phone]
                            .filter(Boolean)
                            .join(" · ") || "No contact details yet"}
                        </Typography>
                      </Box>
                      {candidate.resume_path && (
                        <Chip
                          label="Resume"
                          size="small"
                          component="a"
                          href={candidatesApi.resumeDownloadUrl(candidate.id)}
                          target="_blank"
                          clickable
                        />
                      )}
                    </Stack>

                    <Stack direction="row" spacing={1} mt={2}>
                      {canUpload && (
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => handleParse(candidate.id)}
                          disabled={!candidate.resume_path || parsingId === candidate.id}
                        >
                          {parsingId === candidate.id ? "Parsing..." : "Parse Resume"}
                        </Button>
                      )}
                      {canLink && (
                        <Button size="small" variant="outlined" onClick={() => openLinkDialog(candidate)}>
                          Link to Job
                        </Button>
                      )}
                    </Stack>

                    {parsed && (
                      <Box mt={2}>
                        <Divider sx={{ mb: 1.5 }} />
                        {parsed.total_experience_years != null && (
                          <Typography variant="body2" color="text.secondary" mb={1}>
                            Experience: {parsed.total_experience_years} years
                          </Typography>
                        )}

                        {parsed.skills?.length > 0 && (
                          <Box mb={1.5}>
                            <Typography variant="subtitle2">Skills</Typography>
                            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap mt={0.5}>
                              {parsed.skills.map((skill) => (
                                <Chip key={skill} label={skill} size="small" variant="outlined" />
                              ))}
                            </Stack>
                          </Box>
                        )}

                        {parsed.education?.length > 0 && (
                          <Box mb={1.5}>
                            <Typography variant="subtitle2">Education</Typography>
                            {parsed.education.map((edu, idx) => (
                              <Typography variant="body2" key={idx}>
                                {[edu.degree, edu.institution, edu.year].filter(Boolean).join(" — ")}
                              </Typography>
                            ))}
                          </Box>
                        )}

                        {parsed.work_history?.length > 0 && (
                          <Box>
                            <Typography variant="subtitle2">Work History</Typography>
                            {parsed.work_history.map((job, idx) => (
                              <Typography variant="body2" key={idx}>
                                {[job.title, job.company].filter(Boolean).join(" at ")}
                                {(job.start || job.end) && ` (${job.start ?? "?"} – ${job.end ?? "present"})`}
                              </Typography>
                            ))}
                          </Box>
                        )}
                      </Box>
                    )}
                  </CardContent>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      )}

      <Dialog open={linkCandidate != null} onClose={() => setLinkCandidate(null)} fullWidth maxWidth="sm">
        <DialogTitle>Link {linkCandidate?.full_name || "Candidate"} to a Job</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            {linkError && <Alert severity="error">{linkError}</Alert>}
            <TextField
              select
              label="Job"
              required
              value={linkJobId}
              onChange={(e) => setLinkJobId(e.target.value)}
              fullWidth
            >
              {jobs.length === 0 && <MenuItem disabled value="">No jobs available</MenuItem>}
              {jobs.map((job) => (
                <MenuItem key={job.id} value={job.id}>
                  {job.title}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Expected salary (optional)"
              type="number"
              value={linkExpectedSalary}
              onChange={(e) => setLinkExpectedSalary(e.target.value)}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setLinkCandidate(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleLink} disabled={linking}>
            {linking ? "Linking..." : "Link"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
