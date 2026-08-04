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

import { ApiError, candidatesApi, jobsApi, shortlistingApi } from "../api/client";
import type { ApplicationRead, CandidateRead, JobRoleRead } from "../api/types";

export default function ShortlistingPage() {
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [applications, setApplications] = useState<ApplicationRead[]>([]);
  const [candidates, setCandidates] = useState<Record<string, CandidateRead>>({});
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

  const loadShortlist = async (jobId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await shortlistingApi.list(jobId);
      setApplications(data);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Failed to load shortlist");
    } finally {
      setLoading(false);
    }
  };

  const handleJobChange = (jobId: string) => {
    setSelectedJobId(jobId);
    if (jobId) loadShortlist(jobId);
    else setApplications([]);
  };

  const handleDecision = async (applicationId: string, decision: "select" | "reject") => {
    setActionId(applicationId);
    setError(null);
    try {
      await shortlistingApi.decide(applicationId, { decision });
      setApplications((prev) => prev.filter((app) => app.id !== applicationId));
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Failed to record decision");
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
        Shortlisting
      </Typography>

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

      {!selectedJobId ? (
        <Typography color="text.secondary">Select a job to see its shortlist queue.</Typography>
      ) : loading ? (
        <CircularProgress />
      ) : applications.length === 0 ? (
        <Typography color="text.secondary">No screened applications awaiting a shortlisting decision.</Typography>
      ) : (
        <Stack spacing={2}>
          {applications.map((app) => (
            <Card key={app.id} variant="outlined">
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                  <Typography variant="h6">{candidateLabel(app.candidate_id)}</Typography>
                  <Chip label={app.status} size="small" />
                </Stack>

                <Divider sx={{ my: 1.5 }} />
                <Typography variant="body2">
                  Match score: {app.match_score}% · Skill match: {app.skill_match_pct}%
                </Typography>
                {app.missing_skills && app.missing_skills.length > 0 && (
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap mt={1}>
                    <Typography variant="body2" color="text.secondary">
                      Missing skills:
                    </Typography>
                    {app.missing_skills.map((skill) => (
                      <Chip key={skill} label={skill} size="small" variant="outlined" color="warning" />
                    ))}
                  </Stack>
                )}

                {app.ranking_score != null && (
                  <Box mt={1.5}>
                    <Typography variant="body2" fontWeight="bold">
                      Ranking score: {app.ranking_score}
                    </Typography>
                    {app.ranking_rationale && (
                      <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }} mt={1}>
                        {app.ranking_rationale}
                      </Typography>
                    )}
                  </Box>
                )}

                <Stack direction="row" spacing={1} mt={2}>
                  <Button
                    size="small"
                    variant="contained"
                    color="success"
                    onClick={() => handleDecision(app.id, "select")}
                    disabled={actionId === app.id}
                  >
                    Select
                  </Button>
                  <Button
                    size="small"
                    variant="outlined"
                    color="error"
                    onClick={() => handleDecision(app.id, "reject")}
                    disabled={actionId === app.id}
                  >
                    Reject
                  </Button>
                </Stack>
              </CardContent>
            </Card>
          ))}
        </Stack>
      )}
    </Box>
  );
}
