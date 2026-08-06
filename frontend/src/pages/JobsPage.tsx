import { useEffect, useMemo, useState } from "react";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, jobsApi } from "../api/client";
import type { JobRoleRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import CreateJobWizard from "../components/CreateJobWizard";
import JobFiltersPanel, { applyJobFilters, EMPTY_JOB_FILTERS } from "../components/JobFiltersPanel";
import type { JobFilters } from "../components/JobFiltersPanel";
import JobsDashboardStats from "../components/JobsDashboardStats";
import PostingLinksEditor from "../components/PostingLinksEditor";
import StatusChip from "../components/StatusChip";
import { downloadCsv } from "../utils/csv";
import { ROLE_MATRIX } from "../auth/roles";

export default function JobsPage() {
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.jobsWrite);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [wizardOpen, setWizardOpen] = useState(false);
  const [dashboardRefreshSignal, setDashboardRefreshSignal] = useState(0);
  const [filters, setFilters] = useState<JobFilters>(EMPTY_JOB_FILTERS);

  const [generatingId, setGeneratingId] = useState<string | null>(null);

  const filteredJobs = useMemo(() => applyJobFilters(jobs, filters), [jobs, filters]);

  const loadJobs = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await jobsApi.list();
      setJobs(data);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load jobs"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadJobs();
  }, []);

  const handleJobPublished = () => {
    loadJobs();
    setDashboardRefreshSignal((s) => s + 1);
  };

  const handleExportCsv = () => {
    downloadCsv(
      "jobs.csv",
      ["Title", "Department", "Location", "Experience Level", "Status", "Positions", "Salary Min", "Salary Max", "Created At"],
      filteredJobs.map((job) => [
        job.title,
        job.department,
        job.location,
        job.experience_level,
        job.status,
        job.positions_count,
        job.salary_band_min,
        job.salary_band_max,
        job.created_at,
      ]),
    );
  };

  const handleGenerateJd = async (jobId: string) => {
    setGeneratingId(jobId);
    setError(null);
    try {
      const updated = await jobsApi.generateJd(jobId);
      setJobs((prev) => prev.map((job) => (job.id === jobId ? updated : job)));
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to generate JD"));
    } finally {
      setGeneratingId(null);
    }
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4">Jobs</Typography>
        {canWrite && (
          <Button variant="contained" onClick={() => setWizardOpen(true)}>
            Create Job
          </Button>
        )}
      </Stack>

      <JobsDashboardStats refreshSignal={dashboardRefreshSignal} onCreateJob={() => setWizardOpen(true)} />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Stack direction="row" spacing={2} alignItems="center" mb={2}>
        <JobFiltersPanel jobs={jobs} filters={filters} onChange={setFilters} />
        <Button variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={handleExportCsv} disabled={filteredJobs.length === 0}>
          Export CSV
        </Button>
        {filteredJobs.length !== jobs.length && (
          <Typography variant="body2" color="text.secondary">
            Showing {filteredJobs.length} of {jobs.length} jobs
          </Typography>
        )}
      </Stack>

      {loading ? (
        <CircularProgress />
      ) : filteredJobs.length === 0 ? (
        <Typography color="text.secondary">
          {jobs.length === 0 ? "No jobs yet. Create one to get started." : "No jobs match the current filters."}
        </Typography>
      ) : (
        <Grid container spacing={2}>
          {filteredJobs.map((job) => (
            <Grid key={job.id} size={{ xs: 12, md: 6 }}>
              <Card variant="outlined">
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                    <Box>
                      <Typography variant="h6">{job.title}</Typography>
                      <Typography variant="body2" color="text.secondary">
                        {[job.department, job.location, job.experience_level].filter(Boolean).join(" · ") ||
                          "No details set"}
                      </Typography>
                    </Box>
                    <StatusChip status={job.status} />
                  </Stack>

                  {job.skills && job.skills.length > 0 && (
                    <Stack direction="row" spacing={1} mt={1} flexWrap="wrap" useFlexGap>
                      {job.skills.map((skill) => (
                        <Chip key={skill} label={skill} size="small" variant="outlined" />
                      ))}
                    </Stack>
                  )}

                  <Typography variant="body2" color="text.secondary" mt={1}>
                    Positions: {job.positions_count}
                    {job.salary_band_min != null && job.salary_band_max != null
                      ? ` · Salary band: ${job.salary_band_min} - ${job.salary_band_max}`
                      : ""}
                  </Typography>

                  <PostingLinksEditor
                    job={job}
                    canWrite={canWrite}
                    onUpdated={(updated) =>
                      setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)))
                    }
                  />

                  {canWrite && (
                    <Box mt={2}>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => handleGenerateJd(job.id)}
                        disabled={generatingId === job.id}
                      >
                        {generatingId === job.id ? "Generating..." : "Generate JD"}
                      </Button>
                    </Box>
                  )}

                  {job.jd_text && (
                    <Box mt={2} p={1.5} bgcolor="action.hover" borderRadius={1}>
                      <Typography variant="subtitle2" gutterBottom>
                        Job Description
                      </Typography>
                      <Typography
                        variant="body2"
                        sx={{ whiteSpace: "pre-wrap", fontFamily: "monospace" }}
                      >
                        {job.jd_text}
                      </Typography>
                    </Box>
                  )}
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      <CreateJobWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onPublished={handleJobPublished}
      />
    </Box>
  );
}
