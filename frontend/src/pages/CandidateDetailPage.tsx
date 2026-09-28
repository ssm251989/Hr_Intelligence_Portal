import { useEffect, useState, type ReactNode } from "react";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import EmailOutlinedIcon from "@mui/icons-material/EmailOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";

import { applicationsApi, candidatesApi, extractErrorMessage, integrationsApi, interviewSchedulingApi, runNextAction } from "../api/client";
import { candidatesExtraApi, type ApplicationEvidence } from "../api/candidatesExtra";
import { SHORTLIST_STATUS_LABELS, shortlistStatusOf, type AuditLogRead, type CandidateApplicationDetail, type NextAction } from "../api/types";
import CandidateAvatar from "../components/CandidateAvatar";
import ConfirmDialog from "../components/ConfirmDialog";
import ShortlistStatusPanel from "../components/ShortlistStatusPanel";
import SourceChip from "../components/SourceChip";
import ActivityTimeline from "../components/candidates/ActivityTimeline";
import ResumePreview from "../components/candidates/ResumePreview";
import ScoreCard from "../components/candidates/ScoreCard";
import WhyThisScore from "../components/scoring/WhyThisScore";
import { STEPPER_STAGES, stepperIndex, useFresh } from "../components/candidates/stages";
import { useAuth } from "../auth/AuthContext";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import DuplicateBanner from "../components/candidates/DuplicateBanner";
import CandidateTags from "../components/candidates/CandidateTags";
import RemoveCandidateDialog from "../components/candidates/RemoveCandidateDialog";
import { ROLE_MATRIX } from "../auth/roles";
import { useT } from "../i18n";
import { EmptyState, FriendlyError, InfoTip, PageHeader, StageStepper, StatusChip } from "../ui-kit";
import { downloadResume } from "../utils/resume";

// Part 15.4 C1: the candidate profile in two columns (mockup "Candidate profile") --
// details + stage stepper on the left; score ring with evidence and radar, then the tabbed
// activity / resume / history on the right. Same data and actions as before.

// Actions that belong to the Shortlisting Timeline -- the audit-log subset that is about a
// shortlisting decision.
const SHORTLISTING_TIMELINE_ACTIONS = new Set([
  "application_put_on_hold",
  "application_resumed_from_hold",
  "shortlist_status_updated",
  "hr_shortlisting_decision",
  "ai_shortlist_feedback_suggested",
  "interview_negotiation_skipped",
  "interview_negotiation_interviewer_batch_started",
  "interview_negotiation_candidate_round_started",
  "interview_negotiation_confirmed",
  "interview_negotiation_manual_scheduling_required",
  "interview_negotiation_retry_triggered",
  "interview_negotiation_stale_tokens_invalidated",
]);

// The subset of the above that represents "the current state of this application's
// negotiation" (latest-one-wins) -- mirrors backend app/interview_scheduling/negotiation.py
// NEGOTIATION_STATUS_ACTIONS. Used only to decide whether "Retry Scheduling" should show.
const NEGOTIATION_STATUS_ACTIONS = new Set([
  "interview_negotiation_skipped",
  "interview_negotiation_interviewer_batch_started",
  "interview_negotiation_candidate_round_started",
  "interview_negotiation_confirmed",
  "interview_negotiation_manual_scheduling_required",
]);

type TabKey = "activity" | "resume" | "experience" | "education" | "shortlisting";

function Fact({ label, children, info }: { label: string; children: ReactNode; info?: string }) {
  const f = useFresh();
  return (
    <>
      <Box component="dt" sx={{ color: f.muted }}>
        {label}
        {info && <InfoTip text={info} />}
      </Box>
      <Box component="dd" sx={{ m: 0, fontWeight: 600, minWidth: 0, overflowWrap: "anywhere" }}>{children}</Box>
    </>
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return <Typography sx={{ fontWeight: 700, mb: 1 }}>{children}</Typography>;
}

export default function CandidateDetailPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const navigate = useNavigate();
  const { can } = useAuth();
  const canWrite = can(ROLE_MATRIX.applicationsCreate);
  // Part 17.15: "Remove candidate" (Recycle bin) + the possible-duplicate banner
  const canRemove = useMeBootstrap().can("recruitment.candidate.delete");
  const [removeOpen, setRemoveOpen] = useState(false);
  const t = useT();
  const f = useFresh();

  const [detail, setDetail] = useState<CandidateApplicationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("activity");

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
  const [evidence, setEvidence] = useState<ApplicationEvidence | null>(null);

  const [retryingNegotiation, setRetryingNegotiation] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [retryNotice, setRetryNotice] = useState<string | null>(null);

  const [parsing, setParsing] = useState(false);
  const [resumeDownloading, setResumeDownloading] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);

  const [pendingAction, setPendingAction] = useState<NextAction | null>(null);
  const [runningAction, setRunningAction] = useState(false);

  const load = () => {
    if (!applicationId) return;
    setLoading(true);
    setError(null);
    applicationsApi
      .candidateDetail(applicationId)
      .then(setDetail)
      .catch((err) => setError(err))
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

  // The profile now shows the activity timeline (and the score parts that live in it)
  // straight away, so the audit trail loads with the page instead of on a tab click.
  useEffect(() => {
    if (!detail) return;
    setTimelineError(null);
    candidatesApi
      .timeline(detail.candidate.id)
      .then((res) => setTimeline(res.events))
      .catch((err) => setTimelineError(extractErrorMessage(err, t("candidates.detail.activity_failed"))));
    candidatesExtraApi.evidence(detail.application.id).then(setEvidence);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail]);

  if (loading) {
    return (
      <Box>
        <Skeleton variant="rounded" height={72} sx={{ mb: 2.5, borderRadius: "18px" }} />
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "340px 1fr" }, gap: 2.25 }}>
          <Skeleton variant="rounded" height={420} sx={{ borderRadius: "18px" }} />
          <Skeleton variant="rounded" height={420} sx={{ borderRadius: "18px" }} />
        </Box>
      </Box>
    );
  }

  if (error || !detail) {
    return (
      <Box>
        <Button startIcon={<ArrowBackIcon />} onClick={() => navigate("/candidates/list")} sx={{ mb: 2 }}>
          {t("candidates.detail.back")}
        </Button>
        <FriendlyError error={error ?? undefined} what={error ? undefined : t("candidates.detail.not_found")} onRetry={load} />
      </Box>
    );
  }

  const { application, candidate, job_title, next_actions, other_applications } = detail;
  const parsed = candidate.parsed_fields;
  const hasResume = Boolean(candidate.resume_path);
  const name = candidate.full_name || t("candidates.unnamed");

  const handleDownloadResume = async () => {
    setResumeDownloading(true);
    setResumeError(null);
    try {
      await downloadResume(candidate.id, candidate.resume_path, candidate.full_name);
    } catch (err) {
      setResumeError(extractErrorMessage(err, t("candidates.resume.download_failed")));
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
      setMessageError(extractErrorMessage(err, t("candidates.message.failed")));
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
      setActionError(extractErrorMessage(err, t("candidates.resume.parse_failed")));
    } finally {
      setParsing(false);
    }
  };

  const handleRetryNegotiation = async () => {
    setRetryingNegotiation(true);
    setRetryError(null);
    setRetryNotice(null);
    try {
      const result = await interviewSchedulingApi.retryNegotiation(application.id);
      setRetryNotice(
        result.outcome === "started"
          ? t("candidates.retry.started")
          : result.reason
            ? t("candidates.retry.not_started_reason", { reason: result.reason })
            : t("candidates.retry.not_started"),
      );
      load();
    } catch (err) {
      setRetryError(extractErrorMessage(err, t("candidates.retry.failed")));
    } finally {
      setRetryingNegotiation(false);
    }
  };

  const runAction = async (action: NextAction) => {
    setPendingAction(null);
    setRunningAction(true);
    setActionError(null);
    try {
      await runNextAction(action);
      load();
    } catch (err) {
      setActionError(extractErrorMessage(err, t("candidates.detail.action_failed")));
    } finally {
      setRunningAction(false);
    }
  };

  // ---- score parts: the latest AI screening entry for THIS application ----
  const applicationEvents = (timeline ?? []).filter((event) => event.entity_id === application.id);
  const latestScreeningEntry = applicationEvents.filter((event) => event.action === "ai_screening_scored").at(-1);
  const screeningDetails = (latestScreeningEntry?.details ?? {}) as Record<string, number | undefined>;
  const score = application.composite_score ?? screeningDetails.composite_score ?? application.match_score ?? null;
  const missingSkills = application.missing_skills ?? [];
  const matchedSkills = (parsed?.skills ?? []).filter((skill: string) => !missingSkills.includes(skill));

  // ---- shortlisting tab (unchanged logic) ----
  const latestShortlistUpdate = applicationEvents.filter((event) => event.action === "shortlist_status_updated").at(-1);
  const shortlistDetails = (latestShortlistUpdate?.details ?? {}) as { feedback?: string | null; reason?: string | null };
  const currentShortlistStatus = shortlistStatusOf(application.status);
  // Client-side mirror of backend check_retry_eligibility's coarsest condition plus "the
  // last attempt actually failed" -- the backend stays the real authority.
  const latestNegotiationEvent = applicationEvents.filter((event) => NEGOTIATION_STATUS_ACTIONS.has(event.action ?? "")).at(-1);
  const negotiationRetryEligible = currentShortlistStatus === "shortlisted" && latestNegotiationEvent?.action === "interview_negotiation_skipped";

  const stageNames = STEPPER_STAGES.map((s) => t(`candidates.stepper.${s}`));
  const stageIndex = stepperIndex(application.status, application.previous_status);

  const firstAction = next_actions[0];
  const actionButton = (action: NextAction, variant: "contained" | "outlined" = "contained") =>
    action.kind === "navigate" && action.route ? (
      <Button key={action.key} variant={variant} component={RouterLink} to={action.route}>{action.label}</Button>
    ) : (
      <Button key={action.key} variant={variant} disabled={runningAction || !canWrite} onClick={() => (action.confirm ? setPendingAction(action) : runAction(action))}>
        {action.label}
      </Button>
    );

  const messageButton = (
    <Tooltip title={googleConnected ? "" : t("candidates.message.connect_first")}>
      <span>
        <Button variant={firstAction ? "outlined" : "contained"} startIcon={<EmailOutlinedIcon />} onClick={openMessageDialog} disabled={!googleConnected || !candidate.email}>
          {t("candidates.message.button")}
        </Button>
      </span>
    </Tooltip>
  );

  return (
    <Box>
      <PageHeader
        emoji="technologist"
        title={name}
        purpose={t("candidates.detail.purpose", { job: job_title })}
        tourKey="candidates"
        primary={firstAction ? actionButton(firstAction) : messageButton}
        extra={
          <>
            <Button variant="outlined" startIcon={<ArrowBackIcon />} onClick={() => navigate("/candidates/list")}>
              {t("candidates.detail.back")}
            </Button>
            {firstAction && messageButton}
            <IconButton aria-label={t("candidates.detail.more")} onClick={(e) => setMoreAnchor(e.currentTarget)}>
              <MoreVertIcon />
            </IconButton>
            <Menu anchorEl={moreAnchor} open={Boolean(moreAnchor)} onClose={() => setMoreAnchor(null)}>
              <MenuItem
                onClick={() => {
                  navigator.clipboard?.writeText(candidate.id);
                  setMoreAnchor(null);
                }}
              >
                {t("candidates.detail.copy_id")}
              </MenuItem>
              <MenuItem
                onClick={() => {
                  setTab("activity");
                  setMoreAnchor(null);
                }}
              >
                {t("candidates.detail.view_activity")}
              </MenuItem>
              {canRemove && (
                <MenuItem
                  sx={{ color: "error.main" }}
                  onClick={() => {
                    setRemoveOpen(true);
                    setMoreAnchor(null);
                  }}
                >
                  {t("removal.action")}
                </MenuItem>
              )}
            </Menu>
          </>
        }
      />

      <DuplicateBanner candidateId={candidate.id} />
      <Box sx={{ mb: 2, maxWidth: 560 }}>
        <CandidateTags candidateId={candidate.id} initial={candidate.tags ?? []} canEdit={canWrite} />
      </Box>
      {canRemove && (
        <RemoveCandidateDialog
          open={removeOpen}
          candidateIds={[candidate.id]}
          name={candidate.full_name}
          onClose={() => setRemoveOpen(false)}
          onDone={() => {
            setRemoveOpen(false);
            navigate("/candidates/list");
          }}
        />
      )}
      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "340px minmax(0, 1fr)" }, gap: 2.25, alignItems: "start" }}>
        {/* ---------------- left: who they are ---------------- */}
        <Stack spacing={2.25} sx={{ minWidth: 0 }}>
          <Card sx={{ p: 2.25 }}>
            <Stack direction="row" spacing={1.75} alignItems="center">
              <CandidateAvatar candidateId={candidate.id} photoPath={candidate.photo_path} name={candidate.full_name} email={candidate.email} sx={{ width: 64, height: 64, fontSize: 22, borderRadius: "20px" }} />
              <Box sx={{ minWidth: 0 }}>
                <Typography sx={{ fontWeight: 800, fontSize: 20, lineHeight: 1.2 }}>{name}</Typography>
                <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("candidates.detail.applied_for", { job: job_title })}</Typography>
              </Box>
            </Stack>
            <Stack direction="row" spacing={0.75} sx={{ mt: 1.5, flexWrap: "wrap", rowGap: 0.75 }}>
              <StatusChip status={application.status} />
              <SourceChip source={candidate.source} />
              {score != null && <StatusChip tone="brand" emoji="star" label={t("candidates.score_short", { score: Math.round(score) })} />}
            </Stack>
            <Box component="dl" sx={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 12px", m: 0, mt: 1.75, fontSize: 13 }}>
              <Fact label={t("candidates.fact.email")}>{candidate.email || "—"}</Fact>
              <Fact label={t("candidates.fact.phone")}>{candidate.phone || "—"}</Fact>
              <Fact label={t("candidates.fact.location")}>{candidate.location || "—"}</Fact>
              {parsed?.total_experience_years != null && (
                <Fact label={t("candidates.fact.experience")}>{t("candidates.years", { count: parsed.total_experience_years })}</Fact>
              )}
              {application.expected_salary != null && (
                <Fact label={t("candidates.fact.expected_salary")}>{application.expected_salary.toLocaleString()}</Fact>
              )}
              <Fact label={t("candidates.fact.applied_on")}>{new Date(application.created_at).toLocaleString()}</Fact>
              {application.ranking_score != null && (
                <Fact label={t("candidates.fact.ranking")} info={t("candidates.fact.ranking_info")}>{Math.round(application.ranking_score)}%</Fact>
              )}
            </Box>
            <Box sx={{ mt: 2.25 }}>
              <StageStepper stages={stageNames} current={stageIndex} />
            </Box>
            {next_actions.length === 0 && (
              <Typography sx={{ mt: 1.75, fontSize: 13, color: f.muted, bgcolor: f.surface2, borderRadius: "10px", p: 1.25 }} role="status">
                {application.status === "on_hold"
                  ? t("candidates.detail.on_hold_note")
                  : application.status.endsWith("_completed")
                    ? t("candidates.detail.completed_note")
                    : t("candidates.detail.final_note")}
              </Typography>
            )}
            {next_actions.length > 1 && (
              <Stack direction="row" spacing={1} sx={{ mt: 1.75, flexWrap: "wrap", rowGap: 1 }}>
                {next_actions.slice(1).map((a) => actionButton(a, "outlined"))}
              </Stack>
            )}
            <Stack direction="row" spacing={1} sx={{ mt: 1.75, flexWrap: "wrap", rowGap: 1 }}>
              <Tooltip title={hasResume ? "" : t("candidates.resume.none")}>
                <span>
                  <Button variant="outlined" startIcon={<DescriptionOutlinedIcon />} onClick={handleDownloadResume} disabled={!hasResume || resumeDownloading}>
                    {resumeDownloading ? t("candidates.resume.downloading") : t("candidates.resume.download")}
                  </Button>
                </span>
              </Tooltip>
            </Stack>
            {resumeError && (
              <Alert severity="error" sx={{ mt: 1.5 }} onClose={() => setResumeError(null)}>
                {resumeError}
              </Alert>
            )}
          </Card>

          <Card sx={{ p: 2.25 }}>
            <SectionTitle>{t("candidates.detail.skills")}</SectionTitle>
            {parsed && parsed.skills?.length > 0 ? (
              <Stack direction="row" spacing={0.75} sx={{ flexWrap: "wrap", rowGap: 0.75 }}>
                {parsed.skills.map((skill) => (
                  <StatusChip key={skill} tone={missingSkills.includes(skill) ? "muted" : "sky"} emoji="label" label={skill} />
                ))}
              </Stack>
            ) : (
              <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("candidates.detail.no_skills")}</Typography>
            )}
            {other_applications.length > 0 && (
              <Box sx={{ mt: 2 }}>
                <SectionTitle>{t("candidates.detail.other_applications")}</SectionTitle>
                <Stack spacing={0.75}>
                  {other_applications.map((other) => (
                    <Stack key={other.application_id} component={RouterLink} to={`/candidates/${other.application_id}`} direction="row" spacing={1} alignItems="center" justifyContent="space-between"
                      sx={{ textDecoration: "none", color: "text.primary", p: 1, borderRadius: "10px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                      <Typography sx={{ fontSize: 13, fontWeight: 600 }} noWrap>{other.job_title}</Typography>
                      <StatusChip status={other.status} />
                    </Stack>
                  ))}
                </Stack>
              </Box>
            )}
          </Card>
        </Stack>

        {/* ---------------- right: score, then activity / resume / history ---------------- */}
        <Stack spacing={2.25} sx={{ minWidth: 0 }}>
          <ScoreCard
            score={score}
            candidateName={name}
            rationale={application.ranking_rationale}
            evidence={evidence}
            missingSkills={missingSkills}
            parts={{
              skills: screeningDetails.skills_score ?? application.skill_match_pct,
              experience: screeningDetails.experience_score,
              location: screeningDetails.location_score,
              certificates: screeningDetails.certificates_score,
              resumeMatch: screeningDetails.resume_matcher_score ?? application.match_score,
              composite: screeningDetails.composite_score ?? application.composite_score,
              jobNeeds: screeningDetails.shortlist_threshold ?? screeningDetails.interview_threshold_min ?? screeningDetails.threshold_min,
            }}
          />

          <WhyThisScore applicationId={application.id} refreshKey={`${application.composite_score ?? ""}-${application.status}`} />

          <Card>
            <Tabs value={tab} onChange={(_e, value: TabKey) => setTab(value)} variant="scrollable" allowScrollButtonsMobile sx={{ px: 1, borderBottom: `1px solid ${f.line}` }}>
              <Tab value="activity" label={t("candidates.tab.activity")} />
              <Tab value="resume" label={t("candidates.tab.resume")} />
              <Tab value="experience" label={t("candidates.tab.experience")} />
              <Tab value="education" label={t("candidates.tab.education")} />
              <Tab value="shortlisting" label={t("candidates.tab.shortlisting")} />
            </Tabs>
            <Box sx={{ p: 2.25 }}>
              {tab === "activity" &&
                (timelineError ? (
                  <FriendlyError compact what={timelineError} fix={t("candidates.detail.activity_fix")} />
                ) : timeline == null ? (
                  <CircularProgress size={20} />
                ) : (
                  <ActivityTimeline events={timeline} />
                ))}

              {tab === "resume" && (
                <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 1.4fr) minmax(0, 1fr)" }, gap: 2.25 }}>
                  <ResumePreview candidateId={candidate.id} resumePath={candidate.resume_path} downloading={resumeDownloading} onDownload={handleDownloadResume} />
                  <Box>
                    <SectionTitle>{t("candidates.resume.parsed_title")}</SectionTitle>
                    {parsed ? (
                      <Stack spacing={1.5}>
                        <Box component="dl" sx={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 12px", m: 0, fontSize: 13 }}>
                          <Fact label={t("candidates.fact.name")}>{parsed.full_name || "—"}</Fact>
                          <Fact label={t("candidates.fact.email")}>{parsed.email || "—"}</Fact>
                          <Fact label={t("candidates.fact.phone")}>{parsed.phone || "—"}</Fact>
                          <Fact label={t("candidates.fact.experience")}>{parsed.total_experience_years != null ? t("candidates.years", { count: parsed.total_experience_years }) : "—"}</Fact>
                        </Box>
                        {parsed.work_history?.length > 0 && (
                          <Box>
                            <SectionTitle>{t("candidates.tab.experience")}</SectionTitle>
                            {parsed.work_history.slice(0, 4).map((w, i) => (
                              <Typography key={i} sx={{ fontSize: 13 }}>{[w.title, w.company].filter(Boolean).join(" · ")}</Typography>
                            ))}
                          </Box>
                        )}
                        {parsed.certificates?.length > 0 && (
                          <Box>
                            <SectionTitle>{t("candidates.resume.certificates")}</SectionTitle>
                            <Stack direction="row" spacing={0.75} sx={{ flexWrap: "wrap", rowGap: 0.75 }}>
                              {parsed.certificates.map((c) => <StatusChip key={c} tone="ok" emoji="graduation" label={c} />)}
                            </Stack>
                          </Box>
                        )}
                      </Stack>
                    ) : (
                      <Stack spacing={1.5} alignItems="flex-start">
                        <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("candidates.resume.not_parsed")}</Typography>
                        {canWrite && hasResume && (
                          <Button variant="contained" onClick={handleParseResume} disabled={parsing}>
                            {parsing ? t("candidates.resume.parsing") : t("candidates.resume.parse")}
                          </Button>
                        )}
                      </Stack>
                    )}
                  </Box>
                </Box>
              )}

              {tab === "experience" &&
                (parsed && parsed.work_history?.length > 0 ? (
                  <Stack spacing={1.25}>
                    {parsed.work_history.map((entry, idx) => (
                      <Box key={idx} sx={{ p: 1.25, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                        <Typography sx={{ fontWeight: 700 }}>{[entry.title, entry.company].filter(Boolean).join(" · ")}</Typography>
                        {(entry.start || entry.end) && (
                          <Typography sx={{ fontSize: 12, color: f.muted }}>
                            {entry.start ?? "?"} – {entry.end ?? t("candidates.detail.present")}
                          </Typography>
                        )}
                      </Box>
                    ))}
                  </Stack>
                ) : (
                  <EmptyState compact illustration="resume" title={t("candidates.detail.no_work")} />
                ))}

              {tab === "education" &&
                (parsed && parsed.education?.length > 0 ? (
                  <Stack spacing={1.25}>
                    {parsed.education.map((entry, idx) => (
                      <Box key={idx} sx={{ p: 1.25, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                        <Typography sx={{ fontWeight: 700 }}>{entry.degree || t("candidates.detail.degree")}</Typography>
                        <Typography sx={{ fontSize: 12, color: f.muted }}>{[entry.institution, entry.year].filter(Boolean).join(" · ")}</Typography>
                      </Box>
                    ))}
                  </Stack>
                ) : (
                  <EmptyState compact illustration="resume" title={t("candidates.detail.no_education")} />
                ))}

              {tab === "shortlisting" && (
                <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", lg: "5fr 7fr" }, gap: 3 }}>
                  <Box>
                    <SectionTitle>{t("candidates.shortlist.matched")}</SectionTitle>
                    {matchedSkills.length > 0 ? (
                      <Stack direction="row" spacing={0.75} sx={{ flexWrap: "wrap", rowGap: 0.75, mb: 2.5 }}>
                        {matchedSkills.map((skill: string) => <StatusChip key={skill} tone="ok" emoji="check" label={skill} />)}
                      </Stack>
                    ) : (
                      <Typography sx={{ color: f.muted, fontSize: 13, mb: 2.5 }}>{t("candidates.shortlist.no_matched")}</Typography>
                    )}

                    <SectionTitle>{t("candidates.shortlist.summary")}</SectionTitle>
                    <Typography sx={{ fontSize: 13, mb: 2.5 }}>
                      {t(score != null ? "candidates.shortlist.summary_scored" : "candidates.shortlist.summary_unscored", {
                        name,
                        score: application.composite_score != null ? Math.round(application.composite_score) : 0,
                        job: job_title,
                      })}
                      {missingSkills.length > 0 ? ` ${t("candidates.shortlist.summary_missing", { skills: missingSkills.join(", ") })}` : ""}{" "}
                      {currentShortlistStatus
                        ? t("candidates.shortlist.summary_now", { status: SHORTLIST_STATUS_LABELS[currentShortlistStatus] })
                        : t("candidates.shortlist.summary_not_in_stage")}
                    </Typography>

                    <SectionTitle>{t("candidates.shortlist.notes")}</SectionTitle>
                    {shortlistDetails.feedback || shortlistDetails.reason ? (
                      <Box sx={{ px: 1.25, py: 1, borderLeft: `3px solid ${f.brand}`, bgcolor: f.surface2, borderRadius: "0 8px 8px 0" }}>
                        {shortlistDetails.reason && <Box sx={{ mb: 0.75 }}><StatusChip tone="sky" emoji="memo" label={shortlistDetails.reason} /></Box>}
                        {shortlistDetails.feedback && <Typography sx={{ fontSize: 13, whiteSpace: "pre-wrap" }}>{shortlistDetails.feedback}</Typography>}
                        {latestShortlistUpdate && (
                          <Typography sx={{ display: "block", mt: 0.5, fontSize: 12, color: f.muted }}>
                            {latestShortlistUpdate.actor} · {new Date(latestShortlistUpdate.created_at).toLocaleString()}
                          </Typography>
                        )}
                      </Box>
                    ) : (
                      <Typography sx={{ color: f.muted, fontSize: 13 }}>{t("candidates.shortlist.no_notes")}</Typography>
                    )}
                  </Box>

                  <Box>
                    <SectionTitle>{t("candidates.shortlist.update")}</SectionTitle>
                    <Box sx={{ mb: 3 }}>
                      {canWrite ? (
                        <ShortlistStatusPanel applicationId={application.id} candidateName={candidate.full_name} currentApplicationStatus={application.status} onSaved={load} />
                      ) : (
                        <Alert severity="info">{t("candidates.shortlist.no_permission")}</Alert>
                      )}
                    </Box>

                    {negotiationRetryEligible && canWrite && (
                      <Box sx={{ mb: 3 }}>
                        <SectionTitle>{t("candidates.retry.title")}</SectionTitle>
                        <Alert severity="warning" sx={{ mb: 1 }}>{t("candidates.retry.warning")}</Alert>
                        {retryError && <Alert severity="error" sx={{ mb: 1 }}>{retryError}</Alert>}
                        {retryNotice && <Alert severity="info" sx={{ mb: 1 }}>{retryNotice}</Alert>}
                        <Button size="small" variant="outlined" disabled={retryingNegotiation} onClick={handleRetryNegotiation}>
                          {retryingNegotiation ? t("candidates.retry.retrying") : t("candidates.retry.button")}
                        </Button>
                      </Box>
                    )}

                    <SectionTitle>{t("candidates.shortlist.timeline")}</SectionTitle>
                    {timelineError ? (
                      <Alert severity="error">{timelineError}</Alert>
                    ) : timeline == null ? (
                      <CircularProgress size={20} />
                    ) : (
                      <ActivityTimeline events={applicationEvents} filter={(e) => SHORTLISTING_TIMELINE_ACTIONS.has(e.action ?? "")} />
                    )}
                  </Box>
                </Box>
              )}
            </Box>
          </Card>
        </Stack>
      </Box>

      <Dialog open={messageOpen} onClose={() => setMessageOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{t("candidates.message.title", { name })}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} mt={1}>
            {messageError && <Alert severity="error">{messageError}</Alert>}
            {messageSentTo ? (
              <Alert severity="success">{t("candidates.message.sent", { email: messageSentTo })}</Alert>
            ) : (
              <>
                <TextField label={t("candidates.message.subject")} value={messageSubject} onChange={(e) => setMessageSubject(e.target.value)} fullWidth />
                <TextField label={t("candidates.message.body")} value={messageBody} onChange={(e) => setMessageBody(e.target.value)} fullWidth multiline minRows={5} />
                <Typography variant="caption" color="text.secondary">
                  {t("candidates.message.hint", { email: candidate.email ?? "" })}
                </Typography>
              </>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMessageOpen(false)}>{messageSentTo ? t("action.close") : t("action.cancel")}</Button>
          {!messageSentTo && (
            <Button variant="contained" onClick={handleSendMessage} disabled={messageSending || !messageSubject.trim() || !messageBody.trim()}>
              {messageSending ? t("candidates.message.sending") : t("candidates.message.send")}
            </Button>
          )}
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={Boolean(pendingAction)}
        title={pendingAction?.label ?? ""}
        message={pendingAction?.description || t("candidates.detail.confirm_action", { name })}
        confirmLabel={pendingAction?.label ?? t("action.done")}
        confirming={runningAction}
        destructive={false}
        onConfirm={() => pendingAction && runAction(pendingAction)}
        onCancel={() => setPendingAction(null)}
      />
    </Box>
  );
}
