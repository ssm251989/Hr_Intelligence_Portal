import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Autocomplete from "@mui/material/Autocomplete";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { candidatesApi, extractErrorMessage, integrationsApi, schedulingApi, usersApi } from "../api/client";
import type { CandidateApplicationRow, InterviewRead, UserRead } from "../api/types";
import { istLocalInputToUtcIso } from "../utils/datetime";

// The manual "Schedule Interview" flow, extracted out of the old InterviewsPage so both
// the Interview List's header button and (eventually) any other entry point share exactly
// one implementation of POST /applications/{id}/interviews -- never a second, drifting
// copy of this form. Unlike the old page (which only ever scheduled for an application
// already selected via a job dropdown), this dialog also lets the caller pick *which*
// HR-selected application to schedule for, since the List page has no such context handed
// to it already.
export default function ScheduleInterviewDialog({
  open,
  onClose,
  onScheduled,
}: {
  open: boolean;
  onClose: () => void;
  onScheduled: (interview: InterviewRead) => void;
}) {
  const [candidateOptions, setCandidateOptions] = useState<CandidateApplicationRow[]>([]);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [selectedApplication, setSelectedApplication] = useState<CandidateApplicationRow | null>(null);

  const [scheduledAt, setScheduledAt] = useState("");
  const [meetingLink, setMeetingLink] = useState("");
  const [interviewerId, setInterviewerId] = useState("");
  const [interviewers, setInterviewers] = useState<UserRead[]>([]);
  const [interviewerCalendarConnected, setInterviewerCalendarConnected] = useState<boolean | null>(null);
  const [checkingInterviewerCalendar, setCheckingInterviewerCalendar] = useState(false);
  const [calendarStatusCheckFailed, setCalendarStatusCheckFailed] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [scheduling, setScheduling] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSelectedApplication(null);
    setScheduledAt("");
    setMeetingLink("");
    setInterviewerId("");
    setInterviewerCalendarConnected(null);
    setError(null);

    setLoadingCandidates(true);
    candidatesApi
      .listApplications({ status: "hr_selected", pageSize: 200 })
      .then((result) => setCandidateOptions(result.items))
      .catch(() => setCandidateOptions([]))
      .finally(() => setLoadingCandidates(false));
    usersApi
      .list()
      .then(setInterviewers)
      .catch(() => setInterviewers([]));
  }, [open]);

  useEffect(() => {
    if (!interviewerId) {
      setInterviewerCalendarConnected(null);
      setCalendarStatusCheckFailed(false);
      return;
    }
    setCheckingInterviewerCalendar(true);
    setCalendarStatusCheckFailed(false);
    integrationsApi
      .googleStatus(interviewerId)
      .then((status) => setInterviewerCalendarConnected(status.connected))
      .catch(() => {
        setInterviewerCalendarConnected(null);
        setCalendarStatusCheckFailed(true);
      })
      .finally(() => setCheckingInterviewerCalendar(false));
  }, [interviewerId]);

  const interviewerLabel = (id: string) => {
    const interviewer = interviewers.find((u) => u.id === id);
    return interviewer?.full_name || interviewer?.email || `Interviewer ${id.slice(0, 8)}`;
  };

  const handleSchedule = async () => {
    if (!selectedApplication) {
      setError("Pick a candidate to schedule");
      return;
    }
    if (!scheduledAt) {
      setError("Pick a date and time");
      return;
    }
    setScheduling(true);
    setError(null);
    try {
      const interview = await schedulingApi.schedule(selectedApplication.application_id, {
        scheduled_at: istLocalInputToUtcIso(scheduledAt),
        meeting_link: meetingLink || null,
        interviewer_id: interviewerId || null,
      });
      onScheduled(interview);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to schedule interview"));
    } finally {
      setScheduling(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Schedule Interview</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          {error && <Alert severity="error">{error}</Alert>}

          <Autocomplete
            options={candidateOptions}
            loading={loadingCandidates}
            value={selectedApplication}
            onChange={(_event, value) => setSelectedApplication(value)}
            getOptionLabel={(option) => `${option.candidate_name || "Unnamed candidate"} — ${option.job_title}`}
            isOptionEqualToValue={(option, value) => option.application_id === value.application_id}
            renderInput={(params) => (
              <TextField {...params} label="Candidate (HR-selected, awaiting scheduling)" required />
            )}
          />

          <TextField
            label="Date & Time (IST)"
            type="datetime-local"
            required
            value={scheduledAt}
            onChange={(e) => setScheduledAt(e.target.value)}
            InputLabelProps={{ shrink: true }}
            fullWidth
          />
          <TextField
            select
            label="Interviewer (optional)"
            value={interviewerId}
            onChange={(e) => setInterviewerId(e.target.value)}
            fullWidth
          >
            <MenuItem value="">— Unassigned —</MenuItem>
            {interviewers.map((interviewer) => (
              <MenuItem key={interviewer.id} value={interviewer.id}>
                {interviewer.full_name || interviewer.email} ({interviewer.role})
              </MenuItem>
            ))}
          </TextField>
          {interviewerId &&
            (checkingInterviewerCalendar ? (
              <Alert severity="info" icon={false}>
                Checking {interviewerLabel(interviewerId)}'s Google Calendar connection...
              </Alert>
            ) : calendarStatusCheckFailed ? (
              <Alert severity="warning">
                Couldn't verify {interviewerLabel(interviewerId)}'s Google Calendar connection — assuming the
                manual meeting link below will be used.
              </Alert>
            ) : interviewerCalendarConnected ? (
              <Alert severity="success">
                {interviewerLabel(interviewerId)} has Google Calendar connected — a real Calendar event with an
                invite will be created automatically.
              </Alert>
            ) : (
              <Alert severity="info">
                {interviewerLabel(interviewerId)} hasn't connected Google Calendar — the manual meeting link below
                will be used instead.
              </Alert>
            ))}
          <TextField
            label="Meeting link (optional)"
            helperText="Used as a fallback if the interviewer hasn't connected Google Calendar"
            value={meetingLink}
            onChange={(e) => setMeetingLink(e.target.value)}
            fullWidth
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSchedule} disabled={scheduling}>
          {scheduling ? "Scheduling..." : "Schedule"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
