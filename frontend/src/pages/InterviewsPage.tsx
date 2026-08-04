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
import Divider from "@mui/material/Divider";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { ApiError, applicationsApi, candidatesApi, jobsApi, schedulingApi } from "../api/client";
import type {
  ApplicationRead,
  CandidateRead,
  InterviewFeedbackUpdate,
  InterviewQuestionsResponse,
  InterviewRead,
  JobRoleRead,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";

const SCHEDULED_STATUSES = ["interview_scheduled", "interview_selected", "interview_rejected"];

interface FeedbackFormState {
  technical_rating: string;
  communication_rating: string;
  overall_rating: string;
  comments: string;
  decision: "" | "selected" | "rejected";
}

function InterviewFeedbackForm({
  interview,
  onSubmit,
}: {
  interview: InterviewRead;
  onSubmit: (payload: InterviewFeedbackUpdate) => Promise<void>;
}) {
  const { can } = useAuth();
  const canEdit = can(ROLE_MATRIX.interviewsWrite);
  const [form, setForm] = useState<FeedbackFormState>({
    technical_rating: interview.technical_rating?.toString() ?? "",
    communication_rating: interview.communication_rating?.toString() ?? "",
    overall_rating: interview.overall_rating?.toString() ?? "",
    comments: interview.comments ?? "",
    decision: (interview.decision as "selected" | "rejected" | null) ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canEdit) {
    return null;
  }

  const handleSubmit = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        technical_rating: form.technical_rating ? Number(form.technical_rating) : null,
        communication_rating: form.communication_rating ? Number(form.communication_rating) : null,
        overall_rating: form.overall_rating ? Number(form.overall_rating) : null,
        comments: form.comments || null,
        decision: form.decision || null,
      });
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Failed to save feedback");
    } finally {
      setSaving(false);
    }
  };

  const ratingField = (label: string, key: "technical_rating" | "communication_rating" | "overall_rating") => (
    <TextField
      select
      label={label}
      value={form[key]}
      onChange={(e) => setForm({ ...form, [key]: e.target.value })}
      size="small"
      sx={{ minWidth: 140 }}
    >
      <MenuItem value="">—</MenuItem>
      {[1, 2, 3, 4, 5].map((n) => (
        <MenuItem key={n} value={n}>
          {n}
        </MenuItem>
      ))}
    </TextField>
  );

  return (
    <Box mt={2}>
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
        {ratingField("Technical", "technical_rating")}
        {ratingField("Communication", "communication_rating")}
        {ratingField("Overall", "overall_rating")}
        <TextField
          select
          label="Decision"
          value={form.decision}
          onChange={(e) => setForm({ ...form, decision: e.target.value as FeedbackFormState["decision"] })}
          size="small"
          sx={{ minWidth: 140 }}
        >
          <MenuItem value="">—</MenuItem>
          <MenuItem value="selected">Selected</MenuItem>
          <MenuItem value="rejected">Rejected</MenuItem>
        </TextField>
      </Stack>
      <TextField
        label="Comments"
        value={form.comments}
        onChange={(e) => setForm({ ...form, comments: e.target.value })}
        fullWidth
        multiline
        minRows={2}
        sx={{ mt: 2 }}
        size="small"
      />
      <Button size="small" variant="outlined" sx={{ mt: 1.5 }} onClick={handleSubmit} disabled={saving}>
        {saving ? "Saving..." : "Save Feedback"}
      </Button>
    </Box>
  );
}

export default function InterviewsPage() {
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.interviewsWrite);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [applications, setApplications] = useState<ApplicationRead[]>([]);
  const [candidates, setCandidates] = useState<Record<string, CandidateRead>>({});
  const [interviews, setInterviews] = useState<Record<string, InterviewRead[]>>({});
  const [prepQuestions, setPrepQuestions] = useState<Record<string, InterviewQuestionsResponse>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);

  const [scheduleApp, setScheduleApp] = useState<ApplicationRead | null>(null);
  const [scheduledAt, setScheduledAt] = useState("");
  const [meetingLink, setMeetingLink] = useState("");
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [scheduling, setScheduling] = useState(false);

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
      const relevant = allApplications.filter(
        (app) => app.status === "hr_selected" || SCHEDULED_STATUSES.includes(app.status)
      );
      setApplications(relevant);

      const scheduledApps = relevant.filter((app) => SCHEDULED_STATUSES.includes(app.status));
      const interviewLists = await Promise.all(scheduledApps.map((app) => schedulingApi.list(app.id)));
      const byApplication: Record<string, InterviewRead[]> = {};
      scheduledApps.forEach((app, idx) => {
        byApplication[app.id] = interviewLists[idx];
      });
      setInterviews(byApplication);
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Failed to load interview data");
    } finally {
      setLoading(false);
    }
  };

  const handleJobChange = (jobId: string) => {
    setSelectedJobId(jobId);
    setPrepQuestions({});
    if (jobId) loadJobData(jobId);
    else {
      setApplications([]);
      setInterviews({});
    }
  };

  const openScheduleDialog = (app: ApplicationRead) => {
    setScheduleApp(app);
    setScheduledAt("");
    setMeetingLink("");
    setScheduleError(null);
  };

  const handleSchedule = async () => {
    if (!scheduleApp) return;
    if (!scheduledAt) {
      setScheduleError("Pick a date and time");
      return;
    }
    setScheduling(true);
    setScheduleError(null);
    try {
      await schedulingApi.schedule(scheduleApp.id, {
        scheduled_at: new Date(scheduledAt).toISOString(),
        meeting_link: meetingLink || null,
      });
      setScheduleApp(null);
      await loadJobData(selectedJobId);
    } catch (err) {
      setScheduleError(err instanceof ApiError ? String(err.detail) : "Failed to schedule interview");
    } finally {
      setScheduling(false);
    }
  };

  const handleGenerateQuestions = async (applicationId: string) => {
    setActionId(applicationId);
    setError(null);
    try {
      const result = await schedulingApi.generateQuestions(applicationId);
      setPrepQuestions((prev) => ({ ...prev, [applicationId]: result }));
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "Failed to generate interview questions");
    } finally {
      setActionId(null);
    }
  };

  const handleFeedbackSubmit = async (
    applicationId: string,
    interviewId: string,
    payload: InterviewFeedbackUpdate
  ) => {
    const updated = await schedulingApi.submitFeedback(interviewId, payload);
    setInterviews((prev) => ({
      ...prev,
      [applicationId]: (prev[applicationId] || []).map((iv) => (iv.id === interviewId ? updated : iv)),
    }));
    if (payload.decision) {
      await loadJobData(selectedJobId);
    }
  };

  const candidateLabel = (candidateId: string) => {
    const candidate = candidates[candidateId];
    return candidate?.parsed_fields?.full_name || candidate?.full_name || `Candidate ${candidateId.slice(0, 8)}`;
  };

  const renderQuestions = (questions: InterviewQuestionsResponse) => (
    <Box mt={2}>
      <Divider sx={{ mb: 1.5 }} />
      <Typography variant="subtitle2">Technical Questions</Typography>
      {questions.technical_questions.map((q, idx) => (
        <Typography variant="body2" key={idx}>
          • {q}
        </Typography>
      ))}
      <Typography variant="subtitle2" mt={1.5}>
        Behavioral Questions
      </Typography>
      {questions.behavioral_questions.map((q, idx) => (
        <Typography variant="body2" key={idx}>
          • {q}
        </Typography>
      ))}
      <Typography variant="subtitle2" mt={1.5}>
        Questions to Probe Gaps
      </Typography>
      {questions.questions_to_probe_gaps.map((q, idx) => (
        <Typography variant="body2" key={idx}>
          • {q}
        </Typography>
      ))}
    </Box>
  );

  const readyToSchedule = applications.filter((app) => app.status === "hr_selected");
  const withInterviews = applications.filter((app) => SCHEDULED_STATUSES.includes(app.status));

  return (
    <Box>
      <Typography variant="h4" mb={3}>
        Interviews
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
        <Typography color="text.secondary">Select a job to manage its interviews.</Typography>
      ) : loading ? (
        <CircularProgress />
      ) : (
        <Stack spacing={4}>
          <Box>
            <Typography variant="h6" gutterBottom>
              Ready to Schedule
            </Typography>
            {readyToSchedule.length === 0 ? (
              <Typography color="text.secondary">No HR-selected candidates awaiting scheduling.</Typography>
            ) : (
              <Stack spacing={2}>
                {readyToSchedule.map((app) => (
                  <Card key={app.id} variant="outlined">
                    <CardContent>
                      <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                        <Typography variant="h6">{candidateLabel(app.candidate_id)}</Typography>
                        <Chip label={app.status} size="small" />
                      </Stack>
                      {canWrite && (
                        <Stack direction="row" spacing={1} mt={2}>
                          <Button size="small" variant="contained" onClick={() => openScheduleDialog(app)}>
                            Schedule Interview
                          </Button>
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => handleGenerateQuestions(app.id)}
                            disabled={actionId === app.id}
                          >
                            {actionId === app.id ? "Generating..." : "Generate Prep Questions"}
                          </Button>
                        </Stack>
                      )}
                      {prepQuestions[app.id] && renderQuestions(prepQuestions[app.id])}
                    </CardContent>
                  </Card>
                ))}
              </Stack>
            )}
          </Box>

          <Box>
            <Typography variant="h6" gutterBottom>
              Scheduled Interviews
            </Typography>
            {withInterviews.length === 0 ? (
              <Typography color="text.secondary">No interviews scheduled for this job yet.</Typography>
            ) : (
              <Stack spacing={2}>
                {withInterviews.map((app) => (
                  <Card key={app.id} variant="outlined">
                    <CardContent>
                      <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                        <Typography variant="h6">{candidateLabel(app.candidate_id)}</Typography>
                        <Chip label={app.status} size="small" />
                      </Stack>

                      {(interviews[app.id] || []).map((interview) => (
                        <Box key={interview.id} mt={2}>
                          <Divider sx={{ mb: 1.5 }} />
                          <Typography variant="body2" color="text.secondary">
                            Scheduled: {interview.scheduled_at ? new Date(interview.scheduled_at).toLocaleString() : "—"}
                            {interview.meeting_link ? ` · ${interview.meeting_link}` : ""}
                          </Typography>
                          <InterviewFeedbackForm
                            interview={interview}
                            onSubmit={(payload) => handleFeedbackSubmit(app.id, interview.id, payload)}
                          />
                        </Box>
                      ))}

                      {canWrite && (
                        <Box mt={2}>
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => handleGenerateQuestions(app.id)}
                            disabled={actionId === app.id}
                          >
                            {actionId === app.id ? "Generating..." : "Generate Prep Questions"}
                          </Button>
                        </Box>
                      )}
                      {prepQuestions[app.id] && renderQuestions(prepQuestions[app.id])}
                    </CardContent>
                  </Card>
                ))}
              </Stack>
            )}
          </Box>
        </Stack>
      )}

      <Dialog open={scheduleApp != null} onClose={() => setScheduleApp(null)} fullWidth maxWidth="sm">
        <DialogTitle>Schedule Interview{scheduleApp ? ` — ${candidateLabel(scheduleApp.candidate_id)}` : ""}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            {scheduleError && <Alert severity="error">{scheduleError}</Alert>}
            <TextField
              label="Date & Time"
              type="datetime-local"
              required
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <TextField
              label="Meeting link (optional)"
              value={meetingLink}
              onChange={(e) => setMeetingLink(e.target.value)}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setScheduleApp(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleSchedule} disabled={scheduling}>
            {scheduling ? "Scheduling..." : "Schedule"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
