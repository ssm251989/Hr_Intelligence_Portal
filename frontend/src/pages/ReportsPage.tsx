import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, jobsApi, reportsApi } from "../api/client";
import type { AuditLogPage, ApplicationTimelineResponse, JobRoleRead, JobSummaryResponse, PipelineResponse } from "../api/types";
import RefreshButton from "../components/RefreshButton";

const AUDIT_PAGE_SIZE = 20;

function StatusBarTable({ total, byStatus }: { total: number; byStatus: { status: string; count: number }[] }) {
  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Status</TableCell>
            <TableCell align="right">Count</TableCell>
            <TableCell>Share</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {byStatus.map((row) => (
            <TableRow key={row.status}>
              <TableCell>{row.status}</TableCell>
              <TableCell align="right">{row.count}</TableCell>
              <TableCell sx={{ width: "40%" }}>
                <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                  <Box
                    sx={{
                      height: 8,
                      borderRadius: 1,
                      bgcolor: "primary.main",
                      width: total > 0 ? `${(row.count / total) * 100}%` : "0%",
                      minWidth: row.count > 0 ? 4 : 0,
                    }}
                  />
                  <Typography variant="caption" color="text.secondary">
                    {total > 0 ? `${Math.round((row.count / total) * 100)}%` : "0%"}
                  </Typography>
                </Box>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function PipelineView({ jobs }: { jobs: JobRoleRead[] }) {
  const [jobId, setJobId] = useState("");
  const [data, setData] = useState<PipelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (selectedJobId: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await reportsApi.pipeline(selectedJobId || undefined);
      setData(result);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load pipeline"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(jobId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleJobChange = (value: string) => {
    setJobId(value);
    load(value);
  };

  return (
    <Box>
      <TextField select label="Filter by job (optional)" value={jobId} onChange={(e) => handleJobChange(e.target.value)} sx={{ minWidth: 260, mb: 2 }}>
        <MenuItem value="">All jobs</MenuItem>
        {jobs.map((job) => (
          <MenuItem key={job.id} value={job.id}>
            {job.title}
          </MenuItem>
        ))}
      </TextField>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading ? (
        <CircularProgress />
      ) : data ? (
        <>
          <Typography variant="body2" color="text.secondary" mb={1.5}>
            Total applications: {data.total}
          </Typography>
          {data.by_status.length === 0 ? (
            <Typography color="text.secondary">No applications yet.</Typography>
          ) : (
            <StatusBarTable total={data.total} byStatus={data.by_status} />
          )}
        </>
      ) : null}
    </Box>
  );
}

export function JobSummaryView({ jobs }: { jobs: JobRoleRead[] }) {
  const [jobId, setJobId] = useState("");
  const [data, setData] = useState<JobSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleJobChange = async (value: string) => {
    setJobId(value);
    setData(null);
    if (!value) return;
    setLoading(true);
    setError(null);
    try {
      const result = await reportsApi.jobSummary(value);
      setData(result);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load job summary"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box>
      <TextField select label="Select job" value={jobId} onChange={(e) => handleJobChange(e.target.value)} sx={{ minWidth: 260, mb: 2 }}>
        {jobs.length === 0 && <MenuItem disabled value="">No jobs available</MenuItem>}
        {jobs.map((job) => (
          <MenuItem key={job.id} value={job.id}>
            {job.title}
          </MenuItem>
        ))}
      </TextField>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {!jobId ? (
        <Typography color="text.secondary">Select a job to see its summary.</Typography>
      ) : loading ? (
        <CircularProgress />
      ) : data ? (
        <>
          <Stack direction="row" spacing={3} mb={2}>
            <Typography variant="body2">Total applications: {data.total_applications}</Typography>
            <Typography variant="body2">
              Avg match score: {data.average_match_score != null ? data.average_match_score.toFixed(1) : "—"}
            </Typography>
            <Typography variant="body2">
              Avg ranking score: {data.average_ranking_score != null ? data.average_ranking_score.toFixed(1) : "—"}
            </Typography>
          </Stack>
          {data.by_status.length === 0 ? (
            <Typography color="text.secondary">No applications yet for this job.</Typography>
          ) : (
            <StatusBarTable total={data.total_applications} byStatus={data.by_status} />
          )}
        </>
      ) : null}
    </Box>
  );
}

function AuditTrailView() {
  const [entityType, setEntityType] = useState("");
  const [entityId, setEntityId] = useState("");
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<AuditLogPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (nextOffset: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await reportsApi.auditLog({
        entityType: entityType || undefined,
        entityId: entityId || undefined,
        action: action || undefined,
        limit: AUDIT_PAGE_SIZE,
        offset: nextOffset,
      });
      setData(result);
      setOffset(nextOffset);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load audit trail"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFilter = () => load(0);

  return (
    <Box>
      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap mb={2}>
        <TextField label="Entity type" value={entityType} onChange={(e) => setEntityType(e.target.value)} size="small" placeholder="application" />
        <TextField label="Entity ID" value={entityId} onChange={(e) => setEntityId(e.target.value)} size="small" sx={{ minWidth: 240 }} />
        <TextField label="Action" value={action} onChange={(e) => setAction(e.target.value)} size="small" placeholder="salary_validated" />
        <Button variant="outlined" size="small" onClick={handleFilter} disabled={loading}>
          Filter
        </Button>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading ? (
        <CircularProgress />
      ) : data ? (
        <>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Created At</TableCell>
                  <TableCell>Entity Type</TableCell>
                  <TableCell>Entity ID</TableCell>
                  <TableCell>Action</TableCell>
                  <TableCell>Actor</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>{new Date(item.created_at).toLocaleString()}</TableCell>
                    <TableCell>{item.entity_type}</TableCell>
                    <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>{item.entity_id}</TableCell>
                    <TableCell>{item.action}</TableCell>
                    <TableCell>{item.actor}</TableCell>
                  </TableRow>
                ))}
                {data.items.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5}>
                      <Typography color="text.secondary">No matching audit events.</Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
          <Stack direction="row" spacing={2} alignItems="center" mt={2}>
            <Button size="small" disabled={offset === 0 || loading} onClick={() => load(Math.max(0, offset - AUDIT_PAGE_SIZE))}>
              Previous
            </Button>
            <Button
              size="small"
              disabled={loading || offset + AUDIT_PAGE_SIZE >= data.total}
              onClick={() => load(offset + AUDIT_PAGE_SIZE)}
            >
              Next
            </Button>
            <Typography variant="body2" color="text.secondary">
              {data.total === 0 ? "0" : `${offset + 1}-${Math.min(offset + AUDIT_PAGE_SIZE, data.total)}`} of {data.total}
            </Typography>
          </Stack>
        </>
      ) : null}
    </Box>
  );
}

function TimelineView() {
  const [applicationId, setApplicationId] = useState("");
  const [data, setData] = useState<ApplicationTimelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLoad = async () => {
    if (!applicationId) {
      setError("Enter an application ID");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await reportsApi.applicationTimeline(applicationId);
      setData(result);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load timeline"));
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box>
      <Stack direction="row" spacing={2} mb={2}>
        <TextField
          label="Application ID"
          value={applicationId}
          onChange={(e) => setApplicationId(e.target.value)}
          size="small"
          sx={{ minWidth: 320 }}
        />
        <Button variant="outlined" onClick={handleLoad} disabled={loading}>
          {loading ? "Loading..." : "Load Timeline"}
        </Button>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {data && (
        data.events.length === 0 ? (
          <Typography color="text.secondary">No events recorded for this application.</Typography>
        ) : (
          <Stack spacing={1.5}>
            {data.events.map((event) => (
              <Card key={event.id} variant="outlined">
                <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Typography variant="body2" fontWeight="bold">
                      {event.action}
                    </Typography>
                    <Chip label={event.actor} size="small" />
                  </Stack>
                  <Typography variant="caption" color="text.secondary">
                    {new Date(event.created_at).toLocaleString()}
                  </Typography>
                </CardContent>
              </Card>
            ))}
          </Stack>
        )
      )}
    </Box>
  );
}

export default function ReportsPage() {
  const [tab, setTab] = useState(0);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [error, setError] = useState<string | null>(null);
  // `refreshing` tracks only this page's own jobs fetch (always runs, always resolves) --
  // not any of the 4 tab views' own fetches below, two of which (Job Summary before a job
  // is picked, Timeline before an ID is entered) never auto-fetch at all, so gating the
  // button on them could leave it disabled forever. Each tab already shows its own
  // CircularProgress while its own fetch is in flight, unaffected by this.
  const [refreshing, setRefreshing] = useState(false);
  // Bumped on Refresh and used as each tab view's `key` -- remounting resets that view's
  // own internal filter state (job selection, audit filters, timeline application id) back
  // to its defaults and re-runs whatever fetch it does on mount, without needing to lift
  // any of those 4 views' state up into this page.
  const [resetKey, setResetKey] = useState(0);

  const loadJobs = () =>
    jobsApi
      .list()
      .then(setJobs)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load jobs")));

  useEffect(() => {
    loadJobs();
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    setTab(0);
    setResetKey((k) => k + 1);
    try {
      await loadJobs();
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4">Reports & Status</Typography>
        <RefreshButton loading={refreshing} onRefresh={handleRefresh} />
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Card variant="outlined">
        <Tabs value={tab} onChange={(_e, value) => setTab(value)} sx={{ borderBottom: 1, borderColor: "divider" }}>
          <Tab label="Pipeline" />
          <Tab label="Job Summary" />
          <Tab label="Audit Trail" />
          <Tab label="Timeline" />
        </Tabs>
        <CardContent>
          {tab === 0 && <PipelineView key={resetKey} jobs={jobs} />}
          {tab === 1 && <JobSummaryView key={resetKey} jobs={jobs} />}
          {tab === 2 && <AuditTrailView key={resetKey} />}
          {tab === 3 && <TimelineView key={resetKey} />}
        </CardContent>
      </Card>
    </Box>
  );
}
