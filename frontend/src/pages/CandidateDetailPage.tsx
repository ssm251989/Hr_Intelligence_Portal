import { useEffect, useState, type ReactNode } from "react";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import EmailOutlinedIcon from "@mui/icons-material/EmailOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
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
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";

import { applicationsApi, candidatesApi, extractErrorMessage, integrationsApi } from "../api/client";
import type { AuditLogRead, CandidateApplicationDetail } from "../api/types";
import CandidateAvatar from "../components/CandidateAvatar";
import SourceChip from "../components/SourceChip";
import StatusChip from "../components/StatusChip";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { downloadResume } from "../utils/resume";

function TabPanel({ active, children }: { active: boolean; children: ReactNode }) {
  if (!active) return null;
  return <Box mt={3}>{children}</Box>;
}

function timeAgo(isoTimestamp: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(isoTimestamp).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function humanizeAction(action: string | null | undefined): string {
  const text = (action || "").replace(/_/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "Activity";
}

export default function CandidateDetailPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const navigate = useNavigate();
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.applicationsCreate);

  const [detail, setDetail] = useState<CandidateApplicationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState(0);

  const [moreAnchor, setMoreAnchor] = useState<HTMLElement | null>(null);

  const [googleConnected, setGoogleConnected] = useState<boolean | null>(null);
  const [messageOpen, setMessageOpen] = useState(false);
  const [messageSubject, setMessageSubject] = useState("");
  const [messageBody, setMessageBody] = useState("");
  const [messageSending, setMessageSending] = useState(false);
  const [messageError, setMessageError] = useState<string | null>(null);
  const [messageSentTo, setMessageSentTo] = useState<string | null>(null);

  const [timeline, setTimeline] = useState<AuditLogRead[] | null>(null);
  const [timelineError, setTimelineError] = useState<string | null>(null);

  const [parsing, setParsing] = useState(false);
  const [resumeDownloading, setResumeDownloading] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);

  const load = () => {
    if (!applicationId) return;
    setLoading(true);
    setError(null);
    applicationsApi
      .candidateDetail(applicationId)
      .then(setDetail)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load candidate")))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId]);

  useEffect(() => {
    integrationsApi
      .googleStatus()
      .then((status) => setGoogleConnected(status.connected))
      .catch(() => setGoogleConnected(false));
  }, []);

  useEffect(() => {
    if (tab !== 4 || !detail) return; // Activity tab
    setTimelineError(null);
    candidatesApi
      .timeline(detail.candidate.id)
      .then((res) => setTimeline(res.events))
      .catch((err) => setTimelineError(extractErrorMessage(err, "Failed to load activity")));
  }, [tab, detail]);

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" py={6}>
        <CircularProgress />
      </Box>
    );
  }

  if (error || !detail) {
    return (
      <Box>
        <Button startIcon={<ArrowBackIcon />} onClick={() => navigate("/candidates/list")} sx={{ mb: 2 }}>
          Back to List
        </Button>
        <Alert severity="error">{error || "Candidate not found"}</Alert>
      </Box>
    );
  }

  const { application, candidate, job_title, next_actions, other_applications } = detail;
  const parsed = candidate.parsed_fields;
  const hasResume = Boolean(candidate.resume_path);

  const handleDownloadResume = async () => {
    setResumeDownloading(true);
    setResumeError(null);
    try {
      await downloadResume(candidate.id, candidate.resume_path, candidate.full_name);
    } catch (err) {
      setResumeError(extractErrorMessage(err, "Failed to download resume"));
    } finally {
      setResumeDownloading(false);
    }
  };

  const openMessageDialog = () => {
    setMessageSubject("");
    setMessageBody("");
    setMessageError(null);
    setMessageSentTo(null);
    setMessageOpen(true);
  };

  const handleSendMessage = async () => {
    if (!candidate.email) return;
    setMessageSending(true);
    setMessageError(null);
    try {
      const result = await applicationsApi.message(application.id, { subject: messageSubject, body: messageBody });
      setMessageSentTo(result.to);
    } catch (err) {
      setMessageError(extractErrorMessage(err, "Failed to send message"));
    } finally {
      setMessageSending(false);
    }
  };

  const handleParseResume = async () => {
    setParsing(true);
    try {
      await candidatesApi.parseResume(candidate.id);
      load();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to parse resume"));
    } finally {
      setParsing(false);
    }
  };

  return (
    <Box>
      <Button startIcon={<ArrowBackIcon />} onClick={() => navigate("/candidates/list")} sx={{ mb: 2 }}>
        Back to List
      </Button>

      <Card variant="outlined" sx={{ mb: 3 }}>
        <CardContent>
          <Stack direction="row" justifyContent="space-between" alignItems="flex-start" flexWrap="wrap" gap={2}>
            <Stack direction="row" spacing={2} alignItems="center">
              <CandidateAvatar
                candidateId={candidate.id}
                photoPath={candidate.photo_path}
                name={candidate.full_name}
                email={candidate.email}
                sx={{ width: 56, height: 56, fontSize: 20 }}
              />
              <Box>
                <Typography variant="h5">{candidate.full_name || "Unnamed candidate"}</Typography>
                <Stack direction="row" spacing={1} alignItems="center" mt={0.5} flexWrap="wrap" useFlexGap>
                  <Typography variant="body2" color="text.secondary">
                    Applied for {job_title}
                  </Typography>
                  <StatusChip status={application.status} />
                  <SourceChip source={candidate.source} />
                </Stack>
              </Box>
            </Stack>

            <Stack direction="row" spacing={1}>
              <Tooltip title={hasResume ? "" : "No resume on file"}>
                <span>
                  <Button
                    variant="outlined"
                    startIcon={<DescriptionOutlinedIcon />}
                    onClick={handleDownloadResume}
                    disabled={!hasResume || resumeDownloading}
                  >
                    {resumeDownloading ? "Downloading..." : "Download Resume"}
                  </Button>
                </span>
              </Tooltip>
              <Tooltip title={googleConnected ? "" : "Connect Google in Settings to send email"}>
                <span>
                  <Button
                    variant="outlined"
                    startIcon={<EmailOutlinedIcon />}
                    onClick={openMessageDialog}
                    disabled={!googleConnected || !candidate.email}
                  >
                    Message
                  </Button>
                </span>
              </Tooltip>

              <IconButton onClick={(e) => setMoreAnchor(e.currentTarget)}>
                <MoreVertIcon />
              </IconButton>
              <Menu anchorEl={moreAnchor} open={Boolean(moreAnchor)} onClose={() => setMoreAnchor(null)}>
                <MenuItem
                  onClick={() => {
                    navigator.clipboard?.writeText(candidate.id);
                    setMoreAnchor(null);
                  }}
                >
                  Copy candidate ID
                </MenuItem>
                <MenuItem
                  onClick={() => {
                    setTab(4);
                    setMoreAnchor(null);
                  }}
                >
                  View activity log
                </MenuItem>
              </Menu>
            </Stack>
          </Stack>

          {next_actions.length === 0 && (
            <Alert severity="info" sx={{ mt: 2 }}>
              {application.status === "on_hold"
                ? "This application is on hold -- resume it from the Candidates List page to continue the pipeline."
                : application.status.endsWith("_completed")
                  ? "This application has completed the pipeline -- onboarding is done."
                  : "This application is at a terminal stage -- no further pipeline action is available."}
            </Alert>
          )}
          {resumeError && (
            <Alert severity="error" sx={{ mt: 2 }} onClose={() => setResumeError(null)}>
              {resumeError}
            </Alert>
          )}
        </CardContent>
      </Card>

      <Card variant="outlined">
        <Tabs value={tab} onChange={(_e, value) => setTab(value)} sx={{ borderBottom: 1, borderColor: "divider" }}>
          <Tab label="Overview" />
          <Tab label="Resume" />
          <Tab label="Experience" />
          <Tab label="Education" />
          <Tab label="Activity" />
        </Tabs>
        <CardContent>
          <TabPanel active={tab === 0}>
            <Grid container spacing={3}>
              <Grid size={{ xs: 12, md: 4 }}>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  Match Score
                </Typography>
                <Typography variant="h3" fontWeight={700}>
                  {application.match_score != null ? `${Math.round(application.match_score)}%` : "—"}
                </Typography>
                {application.ranking_score != null && (
                  <Typography variant="body2" color="text.secondary">
                    Ranking score: {Math.round(application.ranking_score)}%
                  </Typography>
                )}
                {application.ranking_rationale && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1, whiteSpace: "pre-wrap" }}>
                    {application.ranking_rationale}
                  </Typography>
                )}
              </Grid>
              <Grid size={{ xs: 12, md: 8 }}>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  Profile
                </Typography>
                <Stack spacing={0.5} mb={2}>
                  <Typography variant="body2">Email: {candidate.email || "—"}</Typography>
                  <Typography variant="body2">Phone: {candidate.phone || "—"}</Typography>
                  <Typography variant="body2">Location: {candidate.location || "—"}</Typography>
                  <Typography variant="body2">Applied on: {new Date(application.created_at).toLocaleString()}</Typography>
                </Stack>

                {parsed && parsed.skills?.length > 0 && (
                  <Box mb={2}>
                    <Typography variant="subtitle2" gutterBottom>
                      Skills
                    </Typography>
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                      {parsed.skills.map((skill) => (
                        <Chip key={skill} label={skill} size="small" variant="outlined" />
                      ))}
                    </Stack>
                  </Box>
                )}

                {other_applications.length > 0 && (
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>
                      Other Applications
                    </Typography>
                    <Stack spacing={0.5}>
                      {other_applications.map((other) => (
                        <Stack
                          key={other.application_id}
                          component={RouterLink}
                          to={`/candidates/${other.application_id}`}
                          direction="row"
                          spacing={1}
                          alignItems="center"
                          sx={{ textDecoration: "none", color: "text.primary" }}
                        >
                          <Typography variant="body2">{other.job_title}</Typography>
                          <StatusChip status={other.status} />
                        </Stack>
                      ))}
                    </Stack>
                  </Box>
                )}
              </Grid>
            </Grid>
          </TabPanel>

          <TabPanel active={tab === 1}>
            {candidate.resume_path ? (
              <Stack spacing={2} alignItems="flex-start">
                <Button
                  variant="contained"
                  startIcon={<DescriptionOutlinedIcon />}
                  onClick={handleDownloadResume}
                  disabled={resumeDownloading}
                >
                  {resumeDownloading ? "Downloading..." : "Download Resume"}
                </Button>
                {canWrite && !parsed && (
                  <Button variant="outlined" onClick={handleParseResume} disabled={parsing}>
                    {parsing ? "Parsing..." : "Parse Resume"}
                  </Button>
                )}
              </Stack>
            ) : (
              <Typography color="text.secondary">No resume uploaded for this candidate.</Typography>
            )}
          </TabPanel>

          <TabPanel active={tab === 2}>
            {parsed && parsed.work_history?.length > 0 ? (
              <Stack spacing={1.5} divider={<Divider />}>
                {parsed.work_history.map((entry, idx) => (
                  <Box key={idx}>
                    <Typography variant="subtitle2">{[entry.title, entry.company].filter(Boolean).join(" at ")}</Typography>
                    {(entry.start || entry.end) && (
                      <Typography variant="body2" color="text.secondary">
                        {entry.start ?? "?"} – {entry.end ?? "present"}
                      </Typography>
                    )}
                  </Box>
                ))}
              </Stack>
            ) : (
              <Typography color="text.secondary">No work history parsed yet.</Typography>
            )}
          </TabPanel>

          <TabPanel active={tab === 3}>
            {parsed && parsed.education?.length > 0 ? (
              <Stack spacing={1.5} divider={<Divider />}>
                {parsed.education.map((entry, idx) => (
                  <Box key={idx}>
                    <Typography variant="subtitle2">{entry.degree || "Degree"}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {[entry.institution, entry.year].filter(Boolean).join(" — ")}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            ) : (
              <Typography color="text.secondary">No education parsed yet.</Typography>
            )}
          </TabPanel>

          <TabPanel active={tab === 4}>
            {timelineError ? (
              <Alert severity="error">{timelineError}</Alert>
            ) : timeline == null ? (
              <CircularProgress size={20} />
            ) : timeline.length === 0 ? (
              <Typography color="text.secondary">No activity recorded yet.</Typography>
            ) : (
              <Stack spacing={1.5} divider={<Divider />}>
                {timeline.map((event) => (
                  <Box key={event.id}>
                    <Typography variant="body2">
                      {humanizeAction(event.action)}
                      {event.actor && event.actor !== "system" ? ` — ${event.actor}` : ""}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {timeAgo(event.created_at)} · {new Date(event.created_at).toLocaleString()}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            )}
          </TabPanel>
        </CardContent>
      </Card>

      <Dialog open={messageOpen} onClose={() => setMessageOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Message {candidate.full_name || "Candidate"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            {messageError && <Alert severity="error">{messageError}</Alert>}
            {messageSentTo ? (
              <Alert severity="success">Email sent to {messageSentTo} via your connected Gmail.</Alert>
            ) : (
              <>
                <TextField label="Subject" value={messageSubject} onChange={(e) => setMessageSubject(e.target.value)} fullWidth />
                <TextField
                  label="Message"
                  value={messageBody}
                  onChange={(e) => setMessageBody(e.target.value)}
                  fullWidth
                  multiline
                  minRows={5}
                />
                <Typography variant="caption" color="text.secondary">
                  Sends a real email to {candidate.email} via your connected Gmail account.
                </Typography>
              </>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMessageOpen(false)}>{messageSentTo ? "Close" : "Cancel"}</Button>
          {!messageSentTo && (
            <Button
              variant="contained"
              onClick={handleSendMessage}
              disabled={messageSending || !messageSubject.trim() || !messageBody.trim()}
            >
              {messageSending ? "Sending..." : "Send"}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  );
}
