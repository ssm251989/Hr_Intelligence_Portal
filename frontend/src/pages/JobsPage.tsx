import { useEffect, useState } from "react";
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
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, jobsApi } from "../api/client";
import type { JobRoleCreate, JobRoleRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import StatusChip from "../components/StatusChip";
import { ROLE_MATRIX } from "../auth/roles";

const EMPTY_FORM = {
  title: "",
  department: "",
  location: "",
  experience_level: "",
  skills: "",
  salary_band_min: "",
  salary_band_max: "",
  positions_count: "1",
};

export default function JobsPage() {
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.jobsWrite);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [generatingId, setGeneratingId] = useState<string | null>(null);

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

  const handleCreate = async () => {
    setFormError(null);
    if (!form.title.trim()) {
      setFormError("Title is required");
      return;
    }
    const payload: JobRoleCreate = {
      title: form.title.trim(),
      department: form.department.trim() || null,
      location: form.location.trim() || null,
      experience_level: form.experience_level.trim() || null,
      skills: form.skills.trim()
        ? form.skills.split(",").map((skill) => skill.trim()).filter(Boolean)
        : null,
      salary_band_min: form.salary_band_min ? Number(form.salary_band_min) : null,
      salary_band_max: form.salary_band_max ? Number(form.salary_band_max) : null,
      positions_count: form.positions_count ? Number(form.positions_count) : 1,
    };

    setCreating(true);
    try {
      const created = await jobsApi.create(payload);
      setJobs((prev) => [created, ...prev]);
      setDialogOpen(false);
      setForm(EMPTY_FORM);
    } catch (err) {
      setFormError(extractErrorMessage(err, "Failed to create job"));
    } finally {
      setCreating(false);
    }
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
          <Button variant="contained" onClick={() => setDialogOpen(true)}>
            Create Job
          </Button>
        )}
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading ? (
        <CircularProgress />
      ) : jobs.length === 0 ? (
        <Typography color="text.secondary">No jobs yet. Create one to get started.</Typography>
      ) : (
        <Grid container spacing={2}>
          {jobs.map((job) => (
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

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Create Job</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            {formError && <Alert severity="error">{formError}</Alert>}
            <TextField
              label="Title"
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              fullWidth
            />
            <TextField
              label="Department"
              value={form.department}
              onChange={(e) => setForm({ ...form, department: e.target.value })}
              fullWidth
            />
            <TextField
              label="Location"
              value={form.location}
              onChange={(e) => setForm({ ...form, location: e.target.value })}
              fullWidth
            />
            <TextField
              label="Experience level"
              value={form.experience_level}
              onChange={(e) => setForm({ ...form, experience_level: e.target.value })}
              fullWidth
            />
            <TextField
              label="Skills (comma-separated)"
              value={form.skills}
              onChange={(e) => setForm({ ...form, skills: e.target.value })}
              fullWidth
            />
            <Stack direction="row" spacing={2}>
              <TextField
                label="Salary band min"
                type="number"
                value={form.salary_band_min}
                onChange={(e) => setForm({ ...form, salary_band_min: e.target.value })}
                fullWidth
              />
              <TextField
                label="Salary band max"
                type="number"
                value={form.salary_band_max}
                onChange={(e) => setForm({ ...form, salary_band_max: e.target.value })}
                fullWidth
              />
            </Stack>
            <TextField
              label="Positions count"
              type="number"
              value={form.positions_count}
              onChange={(e) => setForm({ ...form, positions_count: e.target.value })}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreate} disabled={creating}>
            {creating ? "Creating..." : "Create"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
