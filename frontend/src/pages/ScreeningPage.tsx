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

import { applicationsApi, candidatesApi, extractErrorMessage, jobsApi, screeningApi } from "../api/client";
import type { ApplicationRead, CandidateRead, JobRoleRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";

export default function ScreeningPage() {
  const { can } = useAuth();
  const canDecide = can(ROLE_MATRIX.screeningDecisions);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [applications, setApplications] = useState<ApplicationRead[]>([]);
  const [candidates, setCandidates] = useState<Record<string, CandidateRead>>({});
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

  const loadApplications = async (jobId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await applicationsApi.list(jobId);
      setApplications(data.filter((app) => app.status === "received" || app.status === "screened"));
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load applications"));
    } finally {
      setLoading(false);
    }
  };

  const handleJobChange = (jobId: string) => {
    setSelectedJobId(jobId);
    if (jobId) loadApplications(jobId);
    else setApplications([]);
  };

  const handleScreen = async (applicationId: string) => {
    setActionId(applicationId);
    setError(null);
    try {
      const updated = await screeningApi.screen(applicationId);
      setApplications((prev) => prev.map((app) => (app.id === applicationId ? updated : app)));
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to screen application"));
    } finally {
      setActionId(null);
    }
  };

  const handleRank = async (applicationId: string) => {
    setActionId(applicationId);
    setError(null);
    try {
      const updated = await screeningApi.rank(applicationId);
      setApplications((prev) => prev.map((app) => (app.id === applicationId ? updated : app)));
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to rank application"));
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
        Screening
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
      {candidatesLoadFailed && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Couldn't load candidate names — candidates below may show as raw IDs.
        </Alert>
      )}

      {!selectedJobId ? (
        <Typography color="text.secondary">Select a job to see its applications.</Typography>
      ) : loading ? (
        <CircularProgress />
      ) : applications.length === 0 ? (
        <Typography color="text.secondary">No applications awaiting screening for this job.</Typography>
      ) : (
        <Stack spacing={2}>
          {applications.map((app) => (
            <Card key={app.id} variant="outlined">
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                  <Typography variant="h6">{candidateLabel(app.candidate_id)}</Typography>
                  <Chip label={app.status} size="small" />
                </Stack>

                {app.match_score != null && (
                  <Box mt={1.5}>
                    <Divider sx={{ mb: 1.5 }} />
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
                  </Box>
                )}

                {app.ranking_score != null && (
                  <Box mt={2}>
                    <Divider sx={{ mb: 1.5 }} />
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

                {canDecide && (
                  <Stack direction="row" spacing={1} mt={2}>
                    {app.status === "received" && (
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => handleScreen(app.id)}
                        disabled={actionId === app.id}
                      >
                        {actionId === app.id ? "Screening..." : "Screen"}
                      </Button>
                    )}
                    {app.match_score != null && (
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => handleRank(app.id)}
                        disabled={actionId === app.id}
                      >
                        {actionId === app.id ? "Ranking..." : app.ranking_score != null ? "Re-rank" : "Rank"}
                      </Button>
                    )}
                  </Stack>
                )}
              </CardContent>
            </Card>
          ))}
        </Stack>
      )}
    </Box>
  );
}
