import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Collapse from "@mui/material/Collapse";
import Grid from "@mui/material/Grid";
import MuiLink from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink, useSearchParams } from "react-router-dom";

import { ApiError, applicationsApi, candidatesApi, extractErrorMessage, integrationsApi, jobsApi, offersApi } from "../api/client";
import type { ApplicationRead, CandidateRead, JobRoleRead, OfferGenerateRequest, OfferRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import ConfirmDialog from "../components/ConfirmDialog";
import OfferTemplateEditor from "../components/offers/OfferTemplateEditor";
import OfferTimeline from "../components/offers/OfferTimeline";
import RefreshButton from "../components/RefreshButton";
import { Inset, JobPickerCard, PersonHeader, useOffersContext, useWhen } from "../components/offers/shared";
import { useT } from "../i18n";
import { celebrate, EmptyState, Emoji, FriendlyError, InfoTip, PageHeader, StatTile, useReducedMotion } from "../ui-kit";

const RELEVANT_STATUSES = ["bgv_cleared", "offer_sent", "onboarding_started", "onboarding_completed"];

function OfferGenerateForm({
  onSubmit,
  docusignConnected,
  candidateEmail,
}: {
  onSubmit: (payload: OfferGenerateRequest) => Promise<void>;
  docusignConnected: boolean | null;
  candidateEmail?: string | null;
}) {
  const { can } = useAuth();
  const t = useT();
  const f = useTheme().palette.fresh;
  const when = useWhen();
  const { offer_expiry_days: expiryDays } = useOffersContext();
  const canEdit = can(ROLE_MATRIX.offersWrite);
  const [startDate, setStartDate] = useState("");
  const [reportingManagerName, setReportingManagerName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canEdit) {
    return null;
  }

  const handleSubmit = async () => {
    if (!startDate) {
      setError(t("offers.generate.need_date"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ start_date: startDate, reporting_manager_name: reportingManagerName || null });
    } catch (err) {
      setError(extractErrorMessage(err, t("offers.error.generate")));
    } finally {
      setSaving(false);
    }
  };

  const expiresOn = new Date(Date.now() + expiryDays * 86_400_000).toISOString().slice(0, 10);

  return (
    <Inset title={<><Emoji name="envelope" size={16} /> {t("offers.generate.title")}</>}>
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      {docusignConnected === true && candidateEmail && (
        <Alert severity="info" sx={{ mb: 1.5 }}>
          {t("offers.esign.will_send", { email: candidateEmail })}
        </Alert>
      )}
      {docusignConnected === true && !candidateEmail && (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          {t("offers.esign.no_email")}
        </Alert>
      )}
      {docusignConnected === false && (
        <Alert severity="info" sx={{ mb: 1.5 }}>
          {t("offers.esign.not_connected")}{" "}
          <MuiLink component={RouterLink} to="/settings">
            {t("offers.esign.connect")}
          </MuiLink>
        </Alert>
      )}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }} flexWrap="wrap" useFlexGap>
        <TextField
          label={t("offers.generate.start_date")}
          type="date"
          required
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          InputLabelProps={{ shrink: true }}
          size="small"
        />
        <TextField
          label={t("offers.generate.manager")}
          value={reportingManagerName}
          onChange={(e) => setReportingManagerName(e.target.value)}
          size="small"
          sx={{ minWidth: 240 }}
        />
        <Button variant="contained" onClick={handleSubmit} disabled={saving} startIcon={<Emoji name="envelope" size={16} />}>
          {saving ? t("offers.generate.generating") : t("offers.generate.button")}
        </Button>
      </Stack>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mt: 1.25 }}>
        <Emoji name="alarm_clock" size={14} />
        <Typography sx={{ fontSize: 13, color: f.muted }}>
          {t("offers.generate.expiry_note", { count: expiryDays, date: when(expiresOn, false) })}
        </Typography>
      </Stack>
    </Inset>
  );
}

function MarkSignedForm({ onSubmit }: { onSubmit: (envelopeId: string | null) => Promise<void> }) {
  const { can } = useAuth();
  const t = useT();
  const f = useTheme().palette.fresh;
  const canEdit = can(ROLE_MATRIX.offersWrite);
  const [envelopeId, setEnvelopeId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  if (!canEdit) {
    return null;
  }

  const handleSubmit = async () => {
    setConfirmOpen(false);
    setSaving(true);
    setError(null);
    try {
      await onSubmit(envelopeId || null);
    } catch (err) {
      setError(extractErrorMessage(err, t("offers.error.mark_signed")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Inset title={<><Emoji name="writing_hand" size={16} /> {t("offers.manual.title")}</>}>
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("offers.manual.intro")}</Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }} flexWrap="wrap" useFlexGap>
        <TextField
          label={t("offers.manual.reference")}
          value={envelopeId}
          onChange={(e) => setEnvelopeId(e.target.value)}
          size="small"
          sx={{ minWidth: 260 }}
          InputProps={{ endAdornment: <InfoTip text={t("offers.manual.reference_tip")} /> }}
        />
        <Button variant="contained" onClick={() => setConfirmOpen(true)} disabled={saving}>
          {saving ? t("offers.manual.saving") : t("offers.manual.button")}
        </Button>
      </Stack>

      <ConfirmDialog
        open={confirmOpen}
        title={t("offers.manual.confirm_title")}
        message={t("offers.manual.confirm_message")}
        confirmLabel={t("offers.manual.button")}
        cancelLabel={t("action.cancel")}
        confirming={saving}
        onConfirm={handleSubmit}
        onCancel={() => setConfirmOpen(false)}
      />
    </Inset>
  );
}

function CheckSigningStatusButton({ onCheck }: { onCheck: () => Promise<void> }) {
  const { can } = useAuth();
  const t = useT();
  const f = useTheme().palette.fresh;
  const canEdit = can(ROLE_MATRIX.offersWrite);
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState<{ severity: "info" | "error"; text: string } | null>(null);

  if (!canEdit) {
    return null;
  }

  const handleCheck = async () => {
    setChecking(true);
    setMessage(null);
    try {
      await onCheck();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Envelope exists but isn't fully signed yet -- an expected, non-error outcome.
        setMessage({ severity: "info", text: t("offers.esign.not_yet") });
      } else {
        setMessage({
          severity: "error",
          text: extractErrorMessage(err, t("offers.error.check")),
        });
      }
    } finally {
      setChecking(false);
    }
  };

  return (
    <Inset title={<><Emoji name="writing_hand" size={16} /> {t("offers.esign.title")}</>}>
      {message && (
        <Alert severity={message.severity} sx={{ mb: 1.5 }}>
          {message.text}
        </Alert>
      )}
      <Typography sx={{ fontSize: 13, color: f.muted, mb: 1.5 }}>{t("offers.esign.sent_intro")}</Typography>
      <Button variant="contained" onClick={handleCheck} disabled={checking} startIcon={<Emoji name="magnifier" size={16} />}>
        {checking ? t("offers.esign.checking") : t("offers.esign.check")}
      </Button>
    </Inset>
  );
}

function OfferLetter({ text }: { text: string }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(false);
  return (
    <Box sx={{ mt: 2 }}>
      <Button size="small" onClick={() => setOpen((o) => !o)} aria-expanded={open} startIcon={<Emoji name="page" size={16} />}>
        {open ? t("offers.letter.hide") : t("offers.letter.show")}
      </Button>
      <Collapse in={open} timeout={reduced ? 0 : "auto"}>
        <Box sx={{ mt: 1, p: 2.5, borderRadius: "12px", bgcolor: f.surface, border: `1px solid ${f.line}`, boxShadow: f.shadow, maxHeight: 420, overflow: "auto" }}>
          <Typography sx={{ whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.7 }}>{text}</Typography>
        </Box>
      </Collapse>
    </Box>
  );
}

export default function OffersPage() {
  const { can } = useAuth();
  const t = useT();
  const canWrite = can(ROLE_MATRIX.offersWrite);
  const [searchParams] = useSearchParams();
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [applications, setApplications] = useState<ApplicationRead[]>([]);
  const [candidates, setCandidates] = useState<Record<string, CandidateRead>>({});
  const [offers, setOffers] = useState<Record<string, OfferRead>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);
  const [docusignConnected, setDocusignConnected] = useState<boolean | null>(null);
  const [candidatesLoadFailed, setCandidatesLoadFailed] = useState(false);
  const [docusignStatusLoadFailed, setDocusignStatusLoadFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const celebrated = useRef(new Set<string>());

  const loadInitial = () => {
    const jobsPromise = jobsApi
      .list()
      .then(setJobs)
      .catch((err) => setError(extractErrorMessage(err, t("offers.error.jobs"))));
    const candidatesPromise = candidatesApi
      .list()
      .then((data) => setCandidates(Object.fromEntries(data.map((c) => [c.id, c]))))
      .catch(() => setCandidatesLoadFailed(true));
    // Tells the generate-offer form whether the caller (whoever ends up generating the
    // offer) has DocuSign connected. A failure here must be visible -- otherwise the
    // "mark signed manually" guidance can silently show the wrong thing.
    const docusignPromise = integrationsApi
      .docusignStatus()
      .then((status) => setDocusignConnected(status.connected))
      .catch(() => setDocusignStatusLoadFailed(true));
    return Promise.all([jobsPromise, candidatesPromise, docusignPromise]);
  };

  useEffect(() => {
    loadInitial();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // L-V3: confetti when an offer is signed -- celebrate() itself makes sure each person
  // sees it once per offer (and never under reduced motion). Only offers signed and not
  // yet joined count as "new news" here.
  useEffect(() => {
    applications.forEach((app) => {
      const offer = offers[app.id];
      if (offer?.signed && app.status === "onboarding_started" && !celebrated.current.has(offer.id)) {
        celebrated.current.add(offer.id);
        void celebrate(`offer.signed:${offer.id}`);
      }
    });
  }, [applications, offers]);

  // No filters/search/pagination on this page to reset (its only real "filter" is which
  // job is selected, deliberately left alone -- clearing it would drop the recruiter out
  // of whatever job they were actively reviewing) -- Refresh just re-fetches the job
  // dropdown/candidate names/DocuSign status plus the currently selected job's own data,
  // if any.
  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await loadInitial();
      if (selectedJobId) await loadJobData(selectedJobId);
    } finally {
      setRefreshing(false);
    }
  };

  const loadJobData = async (jobId: string) => {
    setLoading(true);
    setError(null);
    try {
      const allApplications = await applicationsApi.list(jobId);
      const relevant = allApplications.filter((app) => RELEVANT_STATUSES.includes(app.status));
      setApplications(relevant);

      const withOffers = relevant.filter((app) => app.status !== "bgv_cleared");
      const offerResults = await Promise.all(withOffers.map((app) => offersApi.get(app.id)));
      const byApplication: Record<string, OfferRead> = {};
      withOffers.forEach((app, idx) => {
        byApplication[app.id] = offerResults[idx];
      });
      setOffers(byApplication);
    } catch (err) {
      setError(extractErrorMessage(err, t("offers.error.load")));
    } finally {
      setLoading(false);
    }
  };

  const handleJobChange = (jobId: string) => {
    setSelectedJobId(jobId);
    if (jobId) loadJobData(jobId);
    else {
      setApplications([]);
      setOffers({});
    }
  };

  // Deep-link support for the Candidate Detail page's "Move Stage" -> Generate Offer
  // action (see app/candidates/pipeline_actions.py's "navigate" actions).
  useEffect(() => {
    const jobId = searchParams.get("jobId");
    if (jobId && jobId !== selectedJobId && jobs.some((job) => job.id === jobId)) {
      handleJobChange(jobId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs, searchParams]);

  const handleGenerate = async (applicationId: string, payload: OfferGenerateRequest) => {
    const offer = await offersApi.generate(applicationId, payload);
    setOffers((prev) => ({ ...prev, [applicationId]: offer }));
    await loadJobData(selectedJobId);
  };

  const handleMarkSigned = async (applicationId: string, envelopeId: string | null) => {
    const offer = await offersApi.markSigned(applicationId, { docusign_envelope_id: envelopeId });
    setOffers((prev) => ({ ...prev, [applicationId]: offer }));
    await loadJobData(selectedJobId);
  };

  const handleCompleteOnboarding = async (applicationId: string) => {
    setActionId(applicationId);
    setError(null);
    try {
      const offer = await offersApi.completeOnboarding(applicationId);
      setOffers((prev) => ({ ...prev, [applicationId]: offer }));
      await loadJobData(selectedJobId);
    } catch (err) {
      setError(extractErrorMessage(err, t("offers.error.onboarding")));
    } finally {
      setActionId(null);
    }
  };

  const candidateLabel = (candidateId: string) => {
    const candidate = candidates[candidateId];
    return candidate?.parsed_fields?.full_name || candidate?.full_name || t("offers.shared.candidate_fallback", { id: candidateId.slice(0, 8) });
  };

  const count = (s: string) => applications.filter((a) => a.status === s).length;
  const stats = [
    { emoji: "clipboard", value: count("bgv_cleared"), key: "offers.stat.ready", tone: "sky" as const },
    { emoji: "envelope", value: count("offer_sent"), key: "offers.stat.sent", tone: "sun" as const },
    { emoji: "writing_hand", value: count("onboarding_started"), key: "offers.stat.signed", tone: "ok" as const },
    { emoji: "party", value: count("onboarding_completed"), key: "offers.stat.joined", tone: "brand" as const },
  ];

  return (
    <Box>
      <PageHeader
        emoji="envelope"
        title={t("offers.title")}
        purpose={t("offers.purpose")}
        tourKey="offers"
        extra={<RefreshButton loading={refreshing} onRefresh={handleRefresh} label={t("offers.shared.refresh")} />}
        primary={
          canWrite ? (
            <Button variant="contained" onClick={() => setEditorOpen(true)} startIcon={<Emoji name="memo" size={16} />}>
              {t("offers.edit_template")}
            </Button>
          ) : undefined
        }
      />
      {canWrite && <OfferTemplateEditor open={editorOpen} onClose={() => setEditorOpen(false)} />}

      <JobPickerCard jobs={jobs} value={selectedJobId} onChange={handleJobChange} hint={t("offers.pick_hint")} />

      {error && (
        <Box sx={{ mb: 2 }}>
          <FriendlyError compact what={error} fix={t("offers.error.fix")} onRetry={selectedJobId ? () => loadJobData(selectedJobId) : handleRefresh} />
        </Box>
      )}
      {candidatesLoadFailed && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t("offers.shared.names_failed")}
        </Alert>
      )}
      {docusignStatusLoadFailed && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t("offers.esign.status_failed")}
        </Alert>
      )}

      {!selectedJobId ? (
        <Card>
          <EmptyState illustration="job-offers" title={t("offers.empty.no_job")} hint={t("offers.empty.no_job_hint")} />
        </Card>
      ) : loading ? (
        <Box sx={{ display: "grid", placeItems: "center", py: 6 }} role="status" aria-label={t("offers.shared.loading")}>
          <CircularProgress />
        </Box>
      ) : applications.length === 0 ? (
        <Card>
          <EmptyState illustration="empty" title={t("offers.empty.none")} hint={t("offers.empty.none_hint")} />
        </Card>
      ) : (
        <>
          <Grid container spacing={2} sx={{ mb: 2.5 }}>
            {stats.map((s) => (
              <Grid key={s.key} size={{ xs: 6, md: 3 }}>
                <StatTile emoji={s.emoji} value={s.value} label={t(s.key, { count: s.value })} tone={s.tone} />
              </Grid>
            ))}
          </Grid>
          <Stack spacing={2}>
            {applications.map((app) => {
              const offer = offers[app.id];
              return (
                <Card key={app.id} sx={{ p: 2.5 }}>
                  <PersonHeader name={candidateLabel(app.candidate_id)} status={app.status} />

                  {app.status === "bgv_cleared" && (
                    <OfferGenerateForm
                      onSubmit={(payload) => handleGenerate(app.id, payload)}
                      docusignConnected={docusignConnected}
                      candidateEmail={candidates[app.candidate_id]?.email}
                    />
                  )}

                  {offer && (
                    <Inset title={<><Emoji name="compass" size={16} /> {t("offers.tl.title")}</>}>
                      <OfferTimeline
                        applicationId={app.id}
                        status={app.status}
                        signed={offer.signed}
                        reloadKey={`${app.status}:${offer.signed}:${offer.onboarding_status}`}
                      />
                      {offer.offer_letter_text && <OfferLetter text={offer.offer_letter_text} />}
                    </Inset>
                  )}

                  {app.status === "offer_sent" && offer?.docusign_sender_id && (
                    <CheckSigningStatusButton onCheck={() => handleMarkSigned(app.id, null)} />
                  )}
                  {app.status === "offer_sent" && !offer?.docusign_sender_id && (
                    <MarkSignedForm onSubmit={(envelopeId) => handleMarkSigned(app.id, envelopeId)} />
                  )}

                  {canWrite && app.status === "onboarding_started" && (
                    <Stack direction="row" spacing={1.5} alignItems="center" mt={2} flexWrap="wrap" useFlexGap>
                      <Button
                        variant="contained"
                        onClick={() => handleCompleteOnboarding(app.id)}
                        disabled={actionId === app.id}
                        startIcon={<Emoji name="party" size={16} />}
                      >
                        {actionId === app.id ? t("offers.onboarding.completing") : t("offers.onboarding.complete")}
                      </Button>
                      <Typography sx={{ fontSize: 13 }} color="text.secondary">{t("offers.onboarding.hint")}</Typography>
                    </Stack>
                  )}
                </Card>
              );
            })}
          </Stack>
        </>
      )}
    </Box>
  );
}
