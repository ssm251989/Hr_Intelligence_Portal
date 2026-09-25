import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { Link as RouterLink } from "react-router-dom";

import { candidatesApi, extractErrorMessage, jobsApi, reportsApi } from "../api/client";
import type { CandidateRead, JobRoleRead, PipelineResponse } from "../api/types";
import AdminHomeChecklist from "../components/AdminHomeChecklist";
import RefreshButton from "../components/RefreshButton";
import StatCard from "../components/StatCard";
import StatusChip, { statusColor } from "../components/StatusChip";
import { JobSummaryView } from "./ReportsPage";

function barColor(status: string) {
  const color = statusColor(status);
  return color === "default" ? "grey.400" : `${color}.main`;
}

function PipelineFunnel({ pipeline }: { pipeline: PipelineResponse }) {
  if (pipeline.by_status.length === 0) {
    return <Typography color="text.secondary">No applications yet.</Typography>;
  }

  return (
    <Stack spacing={1.5}>
      {pipeline.by_status.map((row) => (
        <Stack key={row.status} direction="row" alignItems="center" spacing={2}>
          <Box sx={{ minWidth: 160 }}>
            <StatusChip status={row.status} />
          </Box>
          <Box sx={{ flexGrow: 1, display: "flex", alignItems: "center" }}>
            <Box
              sx={{
                height: 8,
                borderRadius: 1,
                bgcolor: barColor(row.status),
                width: pipeline.total > 0 ? `${(row.count / pipeline.total) * 100}%` : "0%",
                minWidth: row.count > 0 ? 4 : 0,
              }}
            />
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ minWidth: 90, textAlign: "right" }}>
            {row.count} ({pipeline.total > 0 ? Math.round((row.count / pipeline.total) * 100) : 0}%)
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}

export default function OverviewPage() {
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [candidates, setCandidates] = useState<CandidateRead[]>([]);
  const [pipeline, setPipeline] = useState<PipelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadOverview = () => {
    setLoading(true);
    setError(null);
    return Promise.all([jobsApi.list(), candidatesApi.list(), reportsApi.pipeline()])
      .then(([jobsData, candidatesData, pipelineData]) => {
        setJobs(jobsData);
        setCandidates(candidatesData);
        setPipeline(pipelineData);
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load overview data")))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadOverview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeJobsCount = jobs.filter((job) => job.status === "published").length;

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4">Overview</Typography>
        <RefreshButton loading={loading} onRefresh={loadOverview} />
      </Stack>

      <AdminHomeChecklist />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading ? (
        <CircularProgress />
      ) : (
        <>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap mb={3}>
            <StatCard label="Active Jobs" value={activeJobsCount} />
            <StatCard label="Total Candidates" value={candidates.length} />
            <StatCard label="Total Applications" value={pipeline?.total ?? 0} />
          </Stack>

          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="h6" mb={2}>
                Pipeline Funnel
              </Typography>
              {pipeline && <PipelineFunnel pipeline={pipeline} />}
            </CardContent>
          </Card>

          <Card variant="outlined">
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
                <Typography variant="h6">Job Summary</Typography>
                <Button component={RouterLink} to="/reports" size="small">
                  Full Reports &rarr;
                </Button>
              </Stack>
              <JobSummaryView jobs={jobs} />
            </CardContent>
          </Card>
        </>
      )}
    </Box>
  );
}
