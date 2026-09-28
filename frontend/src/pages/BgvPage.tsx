import StageTable, { type StageRow } from "../components/stage/StageTable";
import DocumentsReviewDrawer from "../components/documents/DocumentsReviewDrawer";
import BgvDecisionBox from "../components/bgv/BgvDecisionBox";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { applicationsApi, bgvApi, candidatesApi, extractErrorMessage, jobsApi } from "../api/client";
import type { ApplicationRead, BgvClearRequest, BgvDocumentRead, CandidateRead, JobRoleRead } from "../api/types";
import { BGV_DOC_TYPES } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import BgvChecklist, { mismatchFlags } from "../components/bgv/BgvChecklist";
import BgvTimeline from "../components/bgv/BgvTimeline";
import ConfirmDialog from "../components/ConfirmDialog";
import RefreshButton from "../components/RefreshButton";
import { Inset, JobPickerCard, PersonHeader } from "../components/offers/shared";
import { useT } from "../i18n";
import { EmptyState, Emoji, FriendlyError, InfoTip, PageHeader, StageStepper, StatTile, useReducedMotion } from "../ui-kit";

const RELEVANT_STATUSES = ["salary_approved", "bgv_requested", "bgv_pending", "bgv_cleared", "bgv_rejected"];
const IN_PROGRESS_STATUSES = ["bgv_requested", "bgv_pending"];
const STAGE_INDEX: Record<string, number> = { salary_approved: 0, bgv_requested: 1, bgv_pending: 2, bgv_cleared: 3, bgv_rejected: 3 };

function BgvUploadForm({ onUpload }: { onUpload: (docType: string, file: File) => Promise<void> }) {
  const { can } = useAuth();
  const t = useT();
  const f = useTheme().palette.fresh;
  const canEdit = can(ROLE_MATRIX.bgvWrite);
  const [docType, setDocType] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  if (!canEdit) {
    return null;
  }

  const handleUpload = async () => {
    if (!docType || !file) {
      setError(t("bgv.upload.need_both"));
      return;
    }
    setUploading(true);
    setError(null);
    try {
      await onUpload(docType, file);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(extractErrorMessage(err, t("bgv.error.upload")));
    } finally {
      setUploading(false);
    }
  };

  return (
    <Inset title={<><Emoji name="page" size={16} /> {t("bgv.upload.title")}</>}>
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }} flexWrap="wrap" useFlexGap>
        <TextField select label={t("bgv.upload.type")} value={docType} onChange={(e) => setDocType(e.target.value)} size="small" sx={{ minWidth: 200 }}>
          {BGV_DOC_TYPES.map((type) => (
            <MenuItem key={type} value={type}>
              {t(`bgv.doc.${type}`)}
            </MenuItem>
          ))}
        </TextField>
        <Button component="label" variant="outlined" startIcon={<Emoji name="file_folder" size={16} />}>
          {file ? t("bgv.upload.change_file") : t("bgv.upload.choose_file")}
          <input
            ref={inputRef}
            type="file"
            hidden
            accept=".pdf,.docx,.jpg,.jpeg,.png"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </Button>
        <Typography sx={{ fontSize: 13, color: f.muted, maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {file ? file.name : t("bgv.upload.file_types")}
        </Typography>
        <Button variant="contained" onClick={handleUpload} disabled={uploading}>
          {uploading ? t("bgv.upload.uploading") : t("bgv.upload.button")}
        </Button>
      </Stack>
    </Inset>
  );
}

export function BgvClearForm({ onSubmit }: { onSubmit: (payload: BgvClearRequest) => Promise<void> }) {
  const { can } = useAuth();
  const t = useT();
  const f = useTheme().palette.fresh;
  const canEdit = can(ROLE_MATRIX.bgvWrite);
  const [decision, setDecision] = useState<"clear" | "reject" | "">("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  if (!canEdit) {
    return null;
  }

  const doSubmit = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ decision: decision as "clear" | "reject", notes: notes || null });
    } catch (err) {
      setError(extractErrorMessage(err, t("bgv.error.decision")));
    } finally {
      setSaving(false);
    }
  };

  // One click picks the decision; the confirm step stays, exactly as before.
  const ask = (d: "clear" | "reject") => {
    setDecision(d);
    setConfirmOpen(true);
  };

  const handleConfirm = async () => {
    setConfirmOpen(false);
    await doSubmit();
  };

  return (
    <Inset title={<><Emoji name="writing_hand" size={16} /> {t("bgv.decide.title")}</>}>
      <Typography sx={{ fontSize: 14, color: f.muted, mb: 1.5 }}>{t("bgv.decide.intro")}</Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      )}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }} flexWrap="wrap" useFlexGap>
        <TextField label={t("bgv.decide.notes")} value={notes} onChange={(e) => setNotes(e.target.value)} size="small" sx={{ minWidth: 260 }} />
        <Button variant="contained" onClick={() => ask("clear")} disabled={saving} startIcon={<Emoji name="shield" size={16} />}>
          {saving && decision === "clear" ? t("bgv.decide.saving") : t("bgv.decide.clear")}
        </Button>
        <Button variant="outlined" color="error" onClick={() => ask("reject")} disabled={saving}>
          {saving && decision === "reject" ? t("bgv.decide.saving") : t("bgv.decide.reject")}
        </Button>
      </Stack>

      <ConfirmDialog
        open={confirmOpen}
        title={decision === "reject" ? t("bgv.decide.reject_title") : t("bgv.decide.clear_title")}
        message={decision === "reject" ? t("bgv.decide.reject_message") : t("bgv.decide.clear_message")}
        confirmLabel={decision === "reject" ? t("bgv.decide.reject") : t("bgv.decide.clear")}
        cancelLabel={t("action.cancel")}
        destructive={decision === "reject"}
        confirming={saving}
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </Inset>
  );
}

export default function BgvPage() {
  const { can } = useAuth();
  const t = useT();
  const f = useTheme().palette.fresh;
  const reduced = useReducedMotion();
  const canWrite = can(ROLE_MATRIX.bgvWrite);
  const [searchParams] = useSearchParams();
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [focusApp, setFocusApp] = useState<string | null>(null); // Part 18.11
  const [reviewing, setReviewing] = useState<StageRow | null>(null); // Part 18.17
  const [stageRefresh, setStageRefresh] = useState(0);
  const [applications, setApplications] = useState<ApplicationRead[]>([]);
  useEffect(() => setStageRefresh((k) => k + 1), [applications]);
  const [candidates, setCandidates] = useState<Record<string, CandidateRead>>({});
  const [documents, setDocuments] = useState<Record<string, BgvDocumentRead[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);
  const [candidatesLoadFailed, setCandidatesLoadFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const loadInitial = () => {
    const jobsPromise = jobsApi
      .list()
      .then(setJobs)
      .catch((err) => setError(extractErrorMessage(err, t("bgv.error.jobs"))));
    const candidatesPromise = candidatesApi
      .list()
      .then((data) => setCandidates(Object.fromEntries(data.map((c) => [c.id, c]))))
      .catch(() => setCandidatesLoadFailed(true));
    return Promise.all([jobsPromise, candidatesPromise]);
  };

  useEffect(() => {
    loadInitial();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // No filters/search/pagination on this page to reset (its only real "filter" is which
  // job is selected, deliberately left alone -- clearing it would drop the recruiter out
  // of whatever job they were actively reviewing) -- Refresh just re-fetches the job
  // dropdown/candidate names plus the currently selected job's own data, if any.
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

      const withDocs = relevant.filter((app) => app.status !== "salary_approved");
      const docLists = await Promise.all(withDocs.map((app) => bgvApi.listDocuments(app.id)));
      const byApplication: Record<string, BgvDocumentRead[]> = {};
      withDocs.forEach((app, idx) => {
        byApplication[app.id] = docLists[idx];
      });
      setDocuments(byApplication);
    } catch (err) {
      setError(extractErrorMessage(err, t("bgv.error.load")));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!focusApp || loading) return;
    const el = document.getElementById(`bgv-card-${focusApp}`);
    if (el) { el.scrollIntoView({ behavior: "smooth", block: "start" }); el.focus(); setFocusApp(null); }
  }, [focusApp, loading, applications]);

  const handleJobChange = (jobId: string) => {
    setSelectedJobId(jobId);
    if (jobId) loadJobData(jobId);
    else {
      setApplications([]);
      setDocuments({});
    }
  };

  // Deep-link support for the Candidate Detail page's "Move Stage" -> Manage BGV
  // Documents action (see app/candidates/pipeline_actions.py's "navigate" actions).
  useEffect(() => {
    const jobId = searchParams.get("jobId");
    if (jobId && jobId !== selectedJobId && jobs.some((job) => job.id === jobId)) {
      handleJobChange(jobId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs, searchParams]);

  const handleRequestBgv = async (applicationId: string) => {
    setActionId(applicationId);
    setError(null);
    try {
      const updated = await bgvApi.request(applicationId);
      setApplications((prev) => prev.map((app) => (app.id === applicationId ? updated : app)));
      setDocuments((prev) => ({ ...prev, [applicationId]: [] }));
    } catch (err) {
      setError(extractErrorMessage(err, t("bgv.error.request")));
    } finally {
      setActionId(null);
    }
  };

  const handleUpload = async (applicationId: string, docType: string, file: File) => {
    const doc = await bgvApi.uploadDocument(applicationId, docType, file);
    setDocuments((prev) => ({ ...prev, [applicationId]: [...(prev[applicationId] || []), doc] }));
    const updated = await applicationsApi.list(selectedJobId);
    setApplications(updated.filter((app) => RELEVANT_STATUSES.includes(app.status)));
  };

  const handleValidateDoc = async (applicationId: string, docId: string) => {
    setActionId(docId);
    setError(null);
    try {
      const updated = await bgvApi.validateDocument(applicationId, docId);
      setDocuments((prev) => ({
        ...prev,
        [applicationId]: (prev[applicationId] || []).map((doc) => (doc.id === docId ? updated : doc)),
      }));
    } catch (err) {
      setError(extractErrorMessage(err, t("bgv.error.validate")));
    } finally {
      setActionId(null);
    }
  };

  const candidateLabel = (candidateId: string) => {
    const candidate = candidates[candidateId];
    return candidate?.parsed_fields?.full_name || candidate?.full_name || t("offers.shared.candidate_fallback", { id: candidateId.slice(0, 8) });
  };

  const needsLook = (app: ApplicationRead) =>
    IN_PROGRESS_STATUSES.includes(app.status) &&
    (documents[app.id] || []).some((d) => d.validation_status === "needs_review" || mismatchFlags(d, candidateLabel(app.candidate_id), t).length > 0);
  const lookCount = applications.filter(needsLook).length;
  const firstToLook = applications.find(needsLook) ?? applications.find((a) => IN_PROGRESS_STATUSES.includes(a.status) || a.status === "salary_approved");

  const jumpTo = (id: string) => {
    const el = document.getElementById(`bgv-card-${id}`);
    el?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
    el?.focus({ preventScroll: true });
  };

  const stages = [t("bgv.stage.salary"), t("bgv.stage.requested"), t("bgv.stage.in_progress"), t("bgv.stage.done")];
  const stats = [
    { emoji: "clipboard", value: applications.filter((a) => a.status === "salary_approved").length, key: "bgv.stat.ready", tone: "sky" as const },
    { emoji: "hourglass", value: applications.filter((a) => IN_PROGRESS_STATUSES.includes(a.status)).length, key: "bgv.stat.running", tone: "sun" as const },
    { emoji: "eyes", value: lookCount, key: "bgv.stat.look", tone: "coral" as const },
    { emoji: "shield", value: applications.filter((a) => a.status === "bgv_cleared").length, key: "bgv.stat.cleared", tone: "ok" as const },
  ];

  return (
    <Box>
      <PageHeader
        emoji="shield"
        title={t("bgv.title")}
        purpose={t("bgv.purpose")}
        tourKey="bgv"
        extra={<RefreshButton loading={refreshing} onRefresh={handleRefresh} label={t("offers.shared.refresh")} />}
        primary={
          <Button variant="contained" onClick={() => firstToLook && jumpTo(firstToLook.id)} disabled={!firstToLook} startIcon={<Emoji name="eyes" size={16} />}>
            {lookCount > 0 ? t("bgv.next_look", { count: lookCount }) : t("bgv.next_work")}
          </Button>
        }
        below={
          <Stack direction="row" spacing={1} alignItems="flex-start" sx={{ p: 1.5, borderRadius: "12px", bgcolor: f.skySoft }}>
            <Emoji name="light_bulb" size={18} />
            <Typography sx={{ fontSize: 14 }}>{t("bgv.when_explained")}</Typography>
          </Stack>
        }
      />

      {/* Part 18.11: every candidate at this stage, across all jobs; a row opens its actions below */}
      <StageTable stage="bgv" refreshSignal={stageRefresh}
        bulkActions={canWrite ? (sel, clear) => {
          const ready = sel.filter((r) => r.status === "salary_approved");
          return ready.length > 0 ? (
            <Button size="small" variant="contained" onClick={async () => {
              for (const r of ready) { try { await bgvApi.request(r.application_id); } catch { /* shown per row on reload */ } }
              clear(); setStageRefresh((k) => k + 1); if (selectedJobId) void loadJobData(selectedJobId);
            }}>{t("stage.bulk_request_bgv", { count: ready.length })}</Button>
          ) : null;
        } : undefined}
        extraColumns={[
          { key: "joining", label: t("docrev.col"), render: (r) => r.status !== "salary_approved" ? "—" : !r.joining_docs ? t("docrev.none_yet") : (
            <Stack direction="row" spacing={0.5}>
              <Chip size="small" label={t("docrev.files", { count: r.joining_docs })} />
              {(r.joining_red ?? 0) > 0 && <Chip size="small" color="error" label={t("docrev.reds", { count: r.joining_red ?? 0 })} />}
              {(r.joining_amber ?? 0) > 0 && <Chip size="small" color="warning" label={t("docrev.ambers", { count: r.joining_amber ?? 0 })} />}
            </Stack>) },
          { key: "docs", label: t("stage.col.documents"), render: (r) => r.documents ? `${r.documents_ok ?? 0}/${r.documents}` : "—" },
        ]}
        onOpen={(r) => {
          // Part 18.17: before BGV starts, a row opens the joining-documents review
          if (r.status === "salary_approved") { setReviewing(r); return; }
          setFocusApp(r.application_id); if (r.job_id !== selectedJobId) handleJobChange(r.job_id);
        }} />
      <DocumentsReviewDrawer applicationId={reviewing?.application_id ?? null} name={reviewing?.name} onClose={() => setReviewing(null)}
        onChanged={() => setStageRefresh((k) => k + 1)} />
      <JobPickerCard jobs={jobs} value={selectedJobId} onChange={handleJobChange} hint={t("bgv.pick_hint")} />

      {error && (
        <Box sx={{ mb: 2 }}>
          <FriendlyError compact what={error} fix={t("bgv.error.fix")} onRetry={selectedJobId ? () => loadJobData(selectedJobId) : handleRefresh} />
        </Box>
      )}
      {candidatesLoadFailed && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t("offers.shared.names_failed")}
        </Alert>
      )}

      {!selectedJobId ? (
        <Card>
          <EmptyState illustration="personal-information" title={t("bgv.empty.no_job")} hint={t("bgv.empty.no_job_hint")} />
        </Card>
      ) : loading ? (
        <Box sx={{ display: "grid", placeItems: "center", py: 6 }} role="status" aria-label={t("offers.shared.loading")}>
          <CircularProgress />
        </Box>
      ) : applications.length === 0 ? (
        <Card>
          <EmptyState illustration="empty" title={t("bgv.empty.none")} hint={t("bgv.empty.none_hint")} />
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
              const docs = documents[app.id] || [];
              const name = candidateLabel(app.candidate_id);
              const showDocs = IN_PROGRESS_STATUSES.includes(app.status) || app.status === "bgv_cleared" || app.status === "bgv_rejected";
              return (
                <Card key={app.id} id={`bgv-card-${app.id}`} tabIndex={-1} sx={{ p: 2.5, outline: "none", scrollMarginTop: 80, "&:focus-visible": { boxShadow: `0 0 0 3px ${f.brand}` } }}>
                  <PersonHeader name={name} status={app.status} subtitle={t("bgv.docs_count", { count: docs.length })} />
                  <Box sx={{ mt: 2 }}>
                    <StageStepper stages={stages} current={STAGE_INDEX[app.status] ?? 0} />
                  </Box>

                  {canWrite && app.status === "salary_approved" && (
                    <Stack direction="row" spacing={1.5} alignItems="center" mt={2} flexWrap="wrap" useFlexGap>
                      <Button
                        variant="contained"
                        onClick={() => handleRequestBgv(app.id)}
                        disabled={actionId === app.id}
                        startIcon={<Emoji name="shield" size={16} />}
                      >
                        {actionId === app.id ? t("bgv.requesting") : t("bgv.request")}
                      </Button>
                      <Typography sx={{ fontSize: 13, color: f.muted }}>{t("bgv.request_hint")}</Typography>
                    </Stack>
                  )}

                  {showDocs && (
                    <Grid container spacing={2} sx={{ mt: 0 }}>
                      <Grid size={{ xs: 12, md: 7 }}>
                        <Inset title={<>{t("bgv.checklist.title")}<InfoTip text={t("bgv.checklist.tip")} /></>}>
                          <BgvChecklist
                            docs={docs}
                            candidateName={name}
                            canValidate={canWrite && IN_PROGRESS_STATUSES.includes(app.status)}
                            busyId={actionId}
                            onValidate={(docId) => handleValidateDoc(app.id, docId)}
                          />
                        </Inset>
                        {IN_PROGRESS_STATUSES.includes(app.status) && (
                          <BgvUploadForm onUpload={(docType, file) => handleUpload(app.id, docType, file)} />
                        )}
                      </Grid>
                      <Grid size={{ xs: 12, md: 5 }}>
                        <Inset title={t("bgv.timeline.title")}>
                          <BgvTimeline applicationId={app.id} reloadKey={`${app.status}:${docs.map((d) => `${d.id}${d.validation_status}`).join(",")}`} />
                        </Inset>
                      </Grid>
                    </Grid>
                  )}

                  {IN_PROGRESS_STATUSES.includes(app.status) && (
                    <BgvDecisionBox applicationId={app.id} notAllValid={docs.length === 0 || docs.some((d) => d.validation_status !== "valid")}
                      onDone={() => { if (selectedJobId) void loadJobData(selectedJobId); setStageRefresh((k) => k + 1); }} />
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
