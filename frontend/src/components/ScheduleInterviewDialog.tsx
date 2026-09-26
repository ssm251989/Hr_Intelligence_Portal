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
import { useT } from "../i18n";
import Emoji from "../ui-kit/Emoji";
import { humanise } from "../ui-kit/StatusChip";
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
  const t = useT();
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
    return interviewer?.full_name || interviewer?.email || t("interviews.schedule.someone");
  };

  const handleSchedule = async () => {
    if (!selectedApplication) {
      setError(t("interviews.schedule.pick_candidate"));
      return;
    }
    if (!scheduledAt) {
      setError(t("interviews.schedule.pick_time"));
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
      setError(extractErrorMessage(err, t("interviews.schedule.failed")));
    } finally {
      setScheduling(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm" aria-labelledby="schedule-interview-title">
      <DialogTitle id="schedule-interview-title">
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Emoji name="calendar" size={24} />
          <span>{t("interviews.schedule.title")}</span>
        </Stack>
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          {error && <Alert severity="error">{error}</Alert>}

          <Autocomplete
            options={candidateOptions}
            loading={loadingCandidates}
            value={selectedApplication}
            onChange={(_event, value) => setSelectedApplication(value)}
            getOptionLabel={(option) => `${option.candidate_name || t("interviews.unnamed")} — ${option.job_title}`}
            isOptionEqualToValue={(option, value) => option.application_id === value.application_id}
            renderInput={(params) => (
              <TextField {...params} label={t("interviews.schedule.candidate")} helperText={t("interviews.schedule.candidate_hint")} required />
            )}
          />

          <TextField
            label={t("interviews.schedule.when")}
            type="datetime-local"
            required
            value={scheduledAt}
            onChange={(e) => setScheduledAt(e.target.value)}
            InputLabelProps={{ shrink: true }}
            fullWidth
          />
          <TextField
            select
            label={t("interviews.schedule.interviewer")}
            value={interviewerId}
            onChange={(e) => setInterviewerId(e.target.value)}
            fullWidth
          >
            <MenuItem value="">{t("interviews.schedule.no_interviewer")}</MenuItem>
            {interviewers.map((interviewer) => (
              <MenuItem key={interviewer.id} value={interviewer.id}>
                {interviewer.full_name || interviewer.email} ({humanise(interviewer.role)})
              </MenuItem>
            ))}
          </TextField>
          {interviewerId &&
            (checkingInterviewerCalendar ? (
              <Alert severity="info" icon={false}>
                {t("interviews.schedule.cal_checking", { name: interviewerLabel(interviewerId) })}
              </Alert>
            ) : calendarStatusCheckFailed ? (
              <Alert severity="warning">
                {t("interviews.schedule.cal_unknown", { name: interviewerLabel(interviewerId) })}
              </Alert>
            ) : interviewerCalendarConnected ? (
              <Alert severity="success">
                {t("interviews.schedule.cal_connected", { name: interviewerLabel(interviewerId) })}
              </Alert>
            ) : (
              <Alert severity="info">
                {t("interviews.schedule.cal_missing", { name: interviewerLabel(interviewerId) })}
              </Alert>
            ))}
          <TextField
            label={t("interviews.schedule.link")}
            helperText={t("interviews.schedule.link_hint")}
            value={meetingLink}
            onChange={(e) => setMeetingLink(e.target.value)}
            fullWidth
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={handleSchedule} disabled={scheduling}>
          {scheduling ? t("interviews.schedule.saving") : t("interviews.schedule.save")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
