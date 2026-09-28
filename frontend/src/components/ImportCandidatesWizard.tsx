import { Link as RouterLink } from "react-router-dom";
import { useEffect, useState } from "react";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import LanguageOutlinedIcon from "@mui/icons-material/LanguageOutlined";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Grid from "@mui/material/Grid";
import Step from "@mui/material/Step";
import StepLabel from "@mui/material/StepLabel";
import Stepper from "@mui/material/Stepper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Button from "@mui/material/Button";
import LinearProgress from "@mui/material/LinearProgress";
import { BoardResumeUpload, type BoardCode } from "./jobboards/JobBoardsPage";

import { candidatesApi, extractErrorMessage, localImportApi } from "../api/client";
import { candidateSourceLabel, CONNECTED_CANDIDATE_SOURCES, type CandidateSource } from "../api/types";
import type { LocalImportSettingsSaveResult } from "../api/types";
import { CANDIDATE_SOURCE_COLOR, CANDIDATE_SOURCE_ICON } from "../utils/candidateSourceIcons";
import { useT } from "../i18n";
import Emoji from "../ui-kit/Emoji";
import { useFresh } from "./candidates/stages";

const STEPS = ["Select Source", "Configure", "Import & Review", "Complete"];
// Part 15.4 page look (StepForm style): one emoji + translated title per step.
const STEP_META = [
  { emoji: "compass", key: "candidates.import.step_source" },
  { emoji: "gear", key: "candidates.import.step_configure" },
  { emoji: "eyes", key: "candidates.import.step_review" },
  { emoji: "party", key: "candidates.import.step_done" },
];

// "manual" is the existing single-resume-upload flow elsewhere in the app, not a bulk
// import source -- excluded here on purpose. Icon/color for the five named platforms come
// from the shared candidateSourceIcons map (also used by the Data Sources panel), so the
// two don't drift out of sync with each other again.
const IMPORT_SOURCES: { value: CandidateSource; icon: typeof WorkOutlineIcon; color?: string }[] = [
  { value: "career_portal", icon: LanguageOutlinedIcon },
  { value: "local_import", icon: UploadFileOutlinedIcon },
  { value: "linkedin", icon: CANDIDATE_SOURCE_ICON.linkedin ?? WorkOutlineIcon, color: CANDIDATE_SOURCE_COLOR.linkedin },
  { value: "naukri", icon: CANDIDATE_SOURCE_ICON.naukri ?? WorkOutlineIcon, color: CANDIDATE_SOURCE_COLOR.naukri },
  { value: "indeed", icon: CANDIDATE_SOURCE_ICON.indeed ?? WorkOutlineIcon, color: CANDIDATE_SOURCE_COLOR.indeed },
  { value: "monster", icon: CANDIDATE_SOURCE_ICON.monster ?? WorkOutlineIcon, color: CANDIDATE_SOURCE_COLOR.monster },
  { value: "shine", icon: CANDIDATE_SOURCE_ICON.shine ?? WorkOutlineIcon, color: CANDIDATE_SOURCE_COLOR.shine },
];

function isConnected(source: CandidateSource): boolean {
  return (CONNECTED_CANDIDATE_SOURCES as readonly string[]).includes(source);
}

interface Props {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
  initialSource?: CandidateSource | null;
  /** "page" renders in place on the Import page (step-form look); default stays a dialog. */
  variant?: "dialog" | "page";
}

export default function ImportCandidatesWizard({ open, onClose, onImported, initialSource, variant = "dialog" }: Props) {
  const t = useT();
  const f = useFresh();
  const [activeStep, setActiveStep] = useState(0);
  const [selectedSource, setSelectedSource] = useState<CandidateSource | "">("");
  const [careerPortalCount, setCareerPortalCount] = useState<number | null>(null);
  const [stepError, setStepError] = useState<string | null>(null);

  // Local Import (Part G): a one-time server-side folder configuration, not a per-visit
  // browser file upload -- resumes are dropped directly into the configured folders on the
  // server and picked up by the scheduled scan (interval configurable below, default 30
  // minutes), never uploaded through this dialog. See app/local_import/service.py.
  const [readyRoot, setReadyRoot] = useState("");
  const [alreadyRoot, setAlreadyRoot] = useState("");
  const [scanIntervalMinutes, setScanIntervalMinutes] = useState("30");
  const [loadingLocalImportSettings, setLoadingLocalImportSettings] = useState(false);
  const [savingLocalImportSettings, setSavingLocalImportSettings] = useState(false);
  const [localImportSaveResult, setLocalImportSaveResult] = useState<LocalImportSettingsSaveResult | null>(null);

  useEffect(() => {
    if (!open) return;
    setActiveStep(0);
    setSelectedSource(initialSource ?? "");
    setCareerPortalCount(null);
    setStepError(null);
    setReadyRoot("");
    setAlreadyRoot("");
    setScanIntervalMinutes("30");
    setLocalImportSaveResult(null);
  }, [open, initialSource]);

  useEffect(() => {
    if (activeStep === 1 && selectedSource === "career_portal") {
      candidatesApi
        .listApplications({ source: "career_portal", pageSize: 1 })
        .then((page) => setCareerPortalCount(page.total))
        .catch(() => setCareerPortalCount(null));
    }
  }, [activeStep, selectedSource]);

  // Prefills the two path fields with whatever's already configured, so re-opening this
  // step to change one path doesn't require retyping the other.
  useEffect(() => {
    if (activeStep === 1 && selectedSource === "local_import") {
      setLoadingLocalImportSettings(true);
      localImportApi
        .getSettings()
        .then((settings) => {
          setReadyRoot(settings.ready_to_upload_root ?? "");
          setAlreadyRoot(settings.already_uploaded_root ?? "");
          setScanIntervalMinutes(String(settings.scan_interval_minutes ?? 30));
        })
        .catch(() => {
          // Best-effort prefill -- an empty form is still usable if this fails.
        })
        .finally(() => setLoadingLocalImportSettings(false));
    }
  }, [activeStep, selectedSource]);

  const connected = selectedSource !== "" && isConnected(selectedSource);

  const handleClose = () => {
    onClose();
  };

  const handleNext = async () => {
    setStepError(null);
    if (activeStep === 0) {
      if (!selectedSource) {
        setStepError("Choose a source to continue");
        return;
      }
      setActiveStep(1);
      return;
    }
    if (activeStep === 1) {
      if (selectedSource === "local_import") {
        if (!readyRoot.trim() || !alreadyRoot.trim()) {
          setStepError("Both folder paths are required");
          return;
        }
        const interval = Number(scanIntervalMinutes);
        if (!Number.isFinite(interval) || interval < 5 || interval > 1440) {
          setStepError("Scan interval must be between 5 and 1440 minutes");
          return;
        }
        setSavingLocalImportSettings(true);
        try {
          const result = await localImportApi.updateSettings({
            ready_to_upload_root: readyRoot.trim(),
            already_uploaded_root: alreadyRoot.trim(),
            scan_interval_minutes: interval,
          });
          setLocalImportSaveResult(result);
          setActiveStep(2);
        } catch (err) {
          setStepError(extractErrorMessage(err, "Failed to save local-import folder settings"));
        } finally {
          setSavingLocalImportSettings(false);
        }
        return;
      }
      setActiveStep(2);
      return;
    }
    setActiveStep((s) => Math.min(STEPS.length - 1, s + 1));
  };

  const handleBack = () => {
    setStepError(null);
    setActiveStep((s) => Math.max(0, s - 1));
  };

  const renderSelectSource = () => (
    <Grid container spacing={2} mt={1}>
      {IMPORT_SOURCES.map(({ value, icon: Icon, color }) => {
        const isSelected = selectedSource === value;
        const sourceConnected = isConnected(value);
        return (
          <Grid key={value} size={{ xs: 12, sm: 6, md: 4 }}>
            <Card
              // Selected state matches the sidebar nav's own selected-item treatment
              // (see layout/AppLayout.tsx activeSx): a colored border plus a background
              // tint, not just a subtle color change -- constant 2px border width on
              // every card (transparent when unselected) so selecting one never shifts
              // the grid layout.
              sx={{
                border: "2px solid",
                borderColor: isSelected ? f.brand : f.line,
                bgcolor: isSelected ? f.brandSoft : f.surface,
                boxShadow: "none",
                height: "100%",
                transition: "border-color 120ms ease, background-color 120ms ease",
              }}
            >
              <CardActionArea onClick={() => setSelectedSource(value)} sx={{ height: "100%", p: 1 }}>
                <CardContent>
                  <Stack direction="row" spacing={1.5} alignItems="center" justifyContent="space-between" mb={1}>
                    <Stack direction="row" spacing={1.5} alignItems="center">
                      {/* A named platform keeps its own brand tint either way, rather than
                          the icon switching to the selected-state theme color and losing it. */}
                      {color ? <Icon sx={{ color }} /> : <Icon color={isSelected ? "primary" : "action"} />}
                      <Typography variant="subtitle1">{candidateSourceLabel(value)}</Typography>
                    </Stack>
                    {isSelected && <CheckCircleOutlineIcon color="primary" fontSize="small" />}
                  </Stack>
                  <Chip
                    label={sourceConnected ? t("boards.state.connected") : t("boards.complete_setup")}
                    size="small"
                    color={sourceConnected ? "success" : "warning"}
                    variant={sourceConnected ? "filled" : "outlined"}
                  />
                </CardContent>
              </CardActionArea>
            </Card>
          </Grid>
        );
      })}
    </Grid>
  );

  // Part 18.9: not "Coming soon" -- say what the board needs, open its settings, and offer
  // the ways that work today (upload the board's resumes, forward its emails).
  const renderComingSoon = () => {
    const board = selectedSource as BoardCode;
    return (
      <Stack spacing={1.5} sx={{ mt: 2 }}>
        <Alert severity="warning">
          <Typography sx={{ fontWeight: 700 }}>{t("boards.complete_setup_title", { board: candidateSourceLabel(selectedSource) })}</Typography>
          <Typography variant="body2">{t(`boards.${board}_needs`)}</Typography>
        </Alert>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <Button variant="contained" component={RouterLink} to="/settings/integrations/job-boards">{t("boards.open_settings")}</Button>
          <BoardResumeUpload code={board} onDone={(n) => { if (n > 0) onImported(); }} />
        </Stack>
        <Typography variant="caption" color="text.secondary">{t("boards.today_upload")}</Typography>
      </Stack>
    );
  };

  const renderConfigure = () => {
    if (!connected) return renderComingSoon();
    if (selectedSource === "career_portal") {
      return (
        <Stack spacing={2} mt={2}>
          <Alert severity="success">
            Career Portal is already connected -- it's your own live application pipeline. Candidates who apply via
            your published job postings are created automatically; there's nothing to configure here.
          </Alert>
          <Typography variant="body2" color="text.secondary">
            {careerPortalCount == null ? (
              <CircularProgress size={14} sx={{ mr: 1 }} />
            ) : (
              `${careerPortalCount} candidate${careerPortalCount === 1 ? "" : "s"} sourced via Career Portal so far.`
            )}
          </Typography>
        </Stack>
      );
    }
    // local_import -- one-time server folder configuration (Part G), not a browser file
    // picker. A subfolder per job (matching its title) is created under both roots the
    // moment this is saved, and again every 30 minutes for any newly published job.
    return (
      <Stack spacing={2} mt={2}>
        <Typography variant="body2" color="text.secondary">
          Configure the two folders on the server that automatic local import scans, and how often it scans them. A
          subfolder named after each published job is created under both -- drop a resume into the matching job's
          folder under "Ready to Upload," and it's picked up, parsed, screened, and linked to that exact job
          automatically on the next scan. Processed files move into the same-named folder under "Already Uploaded."
        </Typography>
        {loadingLocalImportSettings ? (
          <Stack direction="row" alignItems="center" spacing={1}>
            <CircularProgress size={16} />
            <Typography variant="body2" color="text.secondary">
              Loading current configuration...
            </Typography>
          </Stack>
        ) : (
          <>
            <TextField
              label="Ready to Upload root path"
              placeholder="e.g. /srv/hr-automation/ready-to-upload"
              required
              fullWidth
              value={readyRoot}
              onChange={(e) => setReadyRoot(e.target.value)}
              slotProps={{ input: { startAdornment: <FolderOutlinedIcon fontSize="small" sx={{ mr: 1, color: "text.secondary" }} /> } }}
            />
            <TextField
              label="Already Uploaded root path"
              placeholder="e.g. /srv/hr-automation/already-uploaded"
              required
              fullWidth
              value={alreadyRoot}
              onChange={(e) => setAlreadyRoot(e.target.value)}
              slotProps={{ input: { startAdornment: <FolderOutlinedIcon fontSize="small" sx={{ mr: 1, color: "text.secondary" }} /> } }}
            />
            <TextField
              label="Scan interval (minutes)"
              type="number"
              required
              fullWidth
              value={scanIntervalMinutes}
              onChange={(e) => setScanIntervalMinutes(e.target.value)}
              slotProps={{ htmlInput: { min: 5, max: 1440 } }}
              helperText="How often the server checks these folders for new resumes. Between 5 and 1440 minutes (24 hours)."
            />
            <Typography variant="caption" color="text.secondary">
              These are absolute paths on the server machine running this app, not your own computer.
            </Typography>
          </>
        )}
      </Stack>
    );
  };

  const renderImportAndReview = () => {
    if (!connected) return renderComingSoon();
    if (selectedSource === "career_portal") {
      return (
        <Alert severity="info" sx={{ mt: 2 }}>
          Nothing to review -- Career Portal imports continuously as applications come in. Visit the Candidates List
          and filter by Source: Career Portal to see them.
        </Alert>
      );
    }
    // local_import -- the save+sync already happened in handleNext; this just reports it.
    return (
      <Stack spacing={2} mt={2}>
        <Alert severity="success">Folder settings saved.</Alert>
        <Stack spacing={0.5}>
          <Typography variant="body2">
            <strong>Ready to Upload:</strong> {localImportSaveResult?.ready_to_upload_root}
          </Typography>
          <Typography variant="body2">
            <strong>Already Uploaded:</strong> {localImportSaveResult?.already_uploaded_root}
          </Typography>
          <Typography variant="body2">
            <strong>Scan interval:</strong> every {localImportSaveResult?.scan_interval_minutes} minutes
          </Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary">
          {localImportSaveResult?.folders_created ?? 0} job folder
          {(localImportSaveResult?.folders_created ?? 0) === 1 ? "" : "s"} created across both roots, for{" "}
          {localImportSaveResult?.jobs_considered ?? 0} currently published/ready-for-publishing job
          {(localImportSaveResult?.jobs_considered ?? 0) === 1 ? "" : "s"}. This also runs automatically at the start
          of every scheduled scan, so a job published later gets its folders too.
        </Typography>
      </Stack>
    );
  };

  const renderComplete = () => {
    if (!connected) {
      return (
        <Stack spacing={2} mt={2} alignItems="center" textAlign="center" py={2}>
          <CheckCircleOutlineIcon color="success" sx={{ fontSize: 48 }} />
          <Typography variant="h6">{candidateSourceLabel(selectedSource)} isn't available yet</Typography>
          <Typography variant="body2" color="text.secondary">
            Check back once this source is connected.
          </Typography>
        </Stack>
      );
    }
    if (selectedSource === "local_import") {
      return (
        <Stack spacing={2} mt={2} alignItems="center" textAlign="center" py={2}>
          <CheckCircleOutlineIcon color="success" sx={{ fontSize: 48 }} />
          <Typography variant="h6">Local import configured</Typography>
          <Typography variant="body2" color="text.secondary">
            Drop resumes into the matching job's folder under "Ready to Upload." They'll be picked up automatically
            within {localImportSaveResult?.scan_interval_minutes ?? 30} minutes -- no need to keep this dialog open.
          </Typography>
        </Stack>
      );
    }
    return (
      <Stack spacing={2} mt={2} alignItems="center" textAlign="center" py={2}>
        <CheckCircleOutlineIcon color="success" sx={{ fontSize: 48 }} />
        <Typography variant="h6">Import complete</Typography>
        <Typography variant="body2" color="text.secondary">
          The Candidates List has been refreshed with the latest data.
        </Typography>
      </Stack>
    );
  };

  const renderStep = () => {
    switch (activeStep) {
      case 0:
        return renderSelectSource();
      case 1:
        return renderConfigure();
      case 2:
        return renderImportAndReview();
      case 3:
        return renderComplete();
      default:
        return null;
    }
  };

  const isLastStep = activeStep === STEPS.length - 1;

  const handleDone = () => {
    if (selectedSource !== "local_import") {
      onImported();
    }
    handleClose();
  };

  const actions = isLastStep ? (
    <Button variant="contained" onClick={handleDone}>
      {t("action.done")}
    </Button>
  ) : (
    <>
      <Button onClick={handleClose}>{t("action.cancel")}</Button>
      <Button onClick={handleBack} disabled={activeStep === 0 || savingLocalImportSettings}>
        {t("action.back")}
      </Button>
      <Button variant="contained" onClick={handleNext} disabled={savingLocalImportSettings}>
        {savingLocalImportSettings ? t("candidates.saving") : t("action.next")}
      </Button>
    </>
  );

  if (variant === "page") {
    const pct = Math.round(((activeStep + 1) / STEPS.length) * 100);
    return (
      <Card sx={{ p: { xs: 2, sm: 3 } }}>
        <Typography sx={{ fontWeight: 700, mb: 1 }}>
          {t("candidates.import.step_of", { step: activeStep + 1, count: STEPS.length })}
        </Typography>
        <LinearProgress variant="determinate" value={pct} aria-label={t("candidates.import.progress", { pct })} />
        <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: "wrap", rowGap: 1 }} role="list" aria-label={t("candidates.import.steps")}>
          {STEP_META.map((meta, i) => (
            <Box
              key={meta.key}
              role="listitem"
              aria-current={i === activeStep ? "step" : undefined}
              sx={{
                display: "inline-flex", alignItems: "center", gap: 0.75, px: 1.25, py: 0.5, borderRadius: 999, fontSize: 12, fontWeight: 700,
                bgcolor: i === activeStep ? f.brandSoft : i < activeStep ? f.okSoft : f.surface2,
                color: i === activeStep ? f.brand : i < activeStep ? f.ok : f.muted,
              }}
            >
              <Emoji name={i < activeStep ? "check" : meta.emoji} size={14} />
              {t(meta.key)}
            </Box>
          ))}
        </Stack>
        <Box sx={{ mt: 3 }}>
          <Typography variant="h5" component="h2">{t(STEP_META[activeStep].key)}</Typography>
          <Typography sx={{ color: f.muted, mt: 0.5 }}>{t(`${STEP_META[activeStep].key}_hint`)}</Typography>
        </Box>
        {stepError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {stepError}
          </Alert>
        )}
        <Box>{renderStep()}</Box>
        <Stack direction="row" spacing={1} justifyContent="flex-end" sx={{ mt: 3 }}>
          {actions}
        </Stack>
      </Card>
    );
  }

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="md">
      <DialogTitle>Import from Source</DialogTitle>
      <DialogContent>
        <Stepper activeStep={activeStep} sx={{ mt: 1, mb: 1 }}>
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>

        {stepError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {stepError}
          </Alert>
        )}

        <Box>{renderStep()}</Box>
      </DialogContent>
      <DialogActions>{actions}</DialogActions>
    </Dialog>
  );
}
