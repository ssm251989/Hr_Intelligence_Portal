import { useEffect, useRef, useState } from "react";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import LanguageOutlinedIcon from "@mui/icons-material/LanguageOutlined";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
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
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Step from "@mui/material/Step";
import StepLabel from "@mui/material/StepLabel";
import Stepper from "@mui/material/Stepper";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { applicationsApi, candidatesApi, extractErrorMessage, jobsApi } from "../api/client";
import { candidateSourceLabel, CONNECTED_CANDIDATE_SOURCES, type CandidateSource, type JobRoleRead } from "../api/types";
import { CANDIDATE_SOURCE_COLOR, CANDIDATE_SOURCE_ICON } from "../utils/candidateSourceIcons";

const STEPS = ["Select Source", "Configure", "Import & Review", "Complete"];
const LOCAL_IMPORT_ACCEPT = ".pdf,.docx";

interface LocalImportResult {
  filename: string;
  status: "success" | "error";
  reason?: string;
}

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
}

export default function ImportCandidatesWizard({ open, onClose, onImported, initialSource }: Props) {
  const [activeStep, setActiveStep] = useState(0);
  const [selectedSource, setSelectedSource] = useState<CandidateSource | "">("");
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [linkJobId, setLinkJobId] = useState("");
  const [localFiles, setLocalFiles] = useState<File[]>([]);
  const [importing, setImporting] = useState(false);
  const [importTotal, setImportTotal] = useState(0);
  const [importResults, setImportResults] = useState<LocalImportResult[]>([]);
  const [careerPortalCount, setCareerPortalCount] = useState<number | null>(null);
  const [stepError, setStepError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setActiveStep(0);
    setSelectedSource(initialSource ?? "");
    setLinkJobId("");
    setLocalFiles([]);
    setImportTotal(0);
    setImportResults([]);
    setCareerPortalCount(null);
    setStepError(null);
    jobsApi.list().then(setJobs).catch(() => setJobs([]));
  }, [open, initialSource]);

  useEffect(() => {
    if (activeStep === 1 && selectedSource === "career_portal") {
      candidatesApi
        .listApplications({ source: "career_portal", pageSize: 1 })
        .then((page) => setCareerPortalCount(page.total))
        .catch(() => setCareerPortalCount(null));
    }
  }, [activeStep, selectedSource]);

  const connected = selectedSource !== "" && isConnected(selectedSource);

  const handleClose = () => {
    onClose();
  };

  // Loops over the exact same single-file upload+parse endpoints the "Upload Resume"
  // dialog uses, one file at a time (not in parallel -- each parse call hits the AI
  // service, and a real, honest progress readout needs each file to actually finish
  // before the next one starts). A file that fails to upload (bad type, unreadable) is
  // recorded as a failure with its reason; a file that uploads but fails to parse still
  // counts as imported (the candidate record exists, just unparsed) -- same best-effort
  // treatment the single-upload dialog already gives a parse failure.
  //
  // Every successfully-uploaded candidate is then linked to jobId as a real application
  // (status='received', same as any other new application) -- the Candidates List shows
  // one row per application, not per candidate, so a candidate created here without one
  // would exist in the database but never appear anywhere reachable. If linking fails
  // (the candidate row itself still exists), that's reported as this file's failure too --
  // "success" here means the candidate is actually visible in the pipeline afterward, not
  // just that a database row was created.
  const runLocalImport = async (files: File[], jobId: string) => {
    setImporting(true);
    setImportTotal(files.length);
    setImportResults([]);
    for (const file of files) {
      try {
        const candidate = await candidatesApi.upload(file, "local_import");
        try {
          await candidatesApi.parseResume(candidate.id);
        } catch {
          // best-effort, same as the single-upload dialog
        }
        try {
          await applicationsApi.create({ job_role_id: jobId, candidate_id: candidate.id });
        } catch (err) {
          setImportResults((prev) => [
            ...prev,
            {
              filename: file.name,
              status: "error",
              reason: extractErrorMessage(err, "Uploaded, but could not be linked to the job"),
            },
          ]);
          continue;
        }
        setImportResults((prev) => [...prev, { filename: file.name, status: "success" }]);
      } catch (err) {
        setImportResults((prev) => [
          ...prev,
          { filename: file.name, status: "error", reason: extractErrorMessage(err, "Failed to upload") },
        ]);
      }
    }
    setImporting(false);
    onImported();
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
        if (!linkJobId) {
          setStepError("Select a job to link these candidates to");
          return;
        }
        if (localFiles.length === 0) {
          setStepError("Choose at least one resume file to import");
          return;
        }
        setActiveStep(2);
        runLocalImport(localFiles, linkJobId);
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
                borderColor: isSelected ? "primary.main" : "divider",
                bgcolor: isSelected ? "action.selected" : "transparent",
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
                    label={sourceConnected ? "Connected" : "Coming soon"}
                    size="small"
                    color={sourceConnected ? "success" : "default"}
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

  const renderComingSoon = () => (
    <Alert severity="info" sx={{ mt: 2 }}>
      {candidateSourceLabel(selectedSource)} candidate sourcing isn't available yet -- this integration is defined in
      the data model so it can slot in later with no schema change, but nothing imports from it today.
    </Alert>
  );

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
    // local_import
    return (
      <Stack spacing={2} mt={2}>
        <Typography variant="body2" color="text.secondary">
          Select one or more resumes (PDF or DOCX) to import from your computer. Each file becomes its own candidate,
          is automatically parsed for name, email, phone, skills, and photo -- the same pipeline the single-resume
          "Upload Resume" button uses, just run for every file you pick -- and is linked to the job below as a new
          application, so it shows up in the Candidates List afterward.
        </Typography>
        <TextField select label="Job" required value={linkJobId} onChange={(e) => setLinkJobId(e.target.value)} fullWidth>
          {jobs.length === 0 && <MenuItem disabled value="">No jobs available</MenuItem>}
          {jobs.map((job) => (
            <MenuItem key={job.id} value={job.id}>
              {job.title}
            </MenuItem>
          ))}
        </TextField>
        <Stack direction="row" spacing={2} alignItems="center">
          <Button variant="outlined" component="label" startIcon={<UploadFileOutlinedIcon />}>
            Import from Local
            <input
              ref={fileInputRef}
              type="file"
              accept={LOCAL_IMPORT_ACCEPT}
              multiple
              hidden
              onChange={(e) => setLocalFiles(Array.from(e.target.files ?? []))}
            />
          </Button>
        </Stack>
        {localFiles.length > 0 && (
          <Stack spacing={0.25}>
            <Typography variant="caption" color="text.secondary">
              {localFiles.length} file{localFiles.length === 1 ? "" : "s"} selected:
            </Typography>
            {localFiles.map((f, i) => (
              <Typography key={`${f.name}-${i}`} variant="caption" color="text.secondary">
                • {f.name}
              </Typography>
            ))}
          </Stack>
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
    // local_import -- real, live progress (each file takes a few seconds to parse), not a
    // simulated bar: importResults grows by one entry per file as runLocalImport's loop
    // actually completes each upload+parse round trip.
    const processed = importResults.length;
    const successCount = importResults.filter((r) => r.status === "success").length;
    const failed = importResults.filter((r) => r.status === "error");
    return (
      <Stack spacing={2} mt={2}>
        {importing ? (
          <Stack spacing={1}>
            <Typography variant="body2" color="text.secondary">
              Processing {processed} of {importTotal}...
            </Typography>
            <LinearProgress variant="determinate" value={importTotal === 0 ? 0 : (processed / importTotal) * 100} />
          </Stack>
        ) : (
          <Alert severity={failed.length === 0 ? "success" : "warning"}>
            Imported {successCount} of {importTotal}
            {failed.length > 0 ? `, ${failed.length} failed` : ""}.
          </Alert>
        )}
        {failed.length > 0 && (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>File</TableCell>
                <TableCell>Reason</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {failed.map((result) => (
                <TableRow key={result.filename}>
                  <TableCell>{result.filename}</TableCell>
                  <TableCell>{result.reason}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Stack>
    );
  };

  const renderComplete = () => (
    <Stack spacing={2} mt={2} alignItems="center" textAlign="center" py={2}>
      <CheckCircleOutlineIcon color="success" sx={{ fontSize: 48 }} />
      <Typography variant="h6">
        {connected ? "Import complete" : `${candidateSourceLabel(selectedSource)} isn't available yet`}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {connected
          ? "The Candidates List has been refreshed with the latest data."
          : "Check back once this source is connected."}
      </Typography>
    </Stack>
  );

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
      <DialogActions>
        {isLastStep ? (
          <Button variant="contained" onClick={handleClose}>
            Done
          </Button>
        ) : (
          <>
            <Button onClick={handleClose}>Cancel</Button>
            <Button onClick={handleBack} disabled={activeStep === 0 || importing}>
              Back
            </Button>
            <Button variant="contained" onClick={handleNext} disabled={importing}>
              {importing ? "Importing..." : "Next"}
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
