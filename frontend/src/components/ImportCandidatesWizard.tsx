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
import Step from "@mui/material/Step";
import StepLabel from "@mui/material/StepLabel";
import Stepper from "@mui/material/Stepper";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import { candidatesApi, extractErrorMessage } from "../api/client";
import { candidateSourceLabel, CONNECTED_CANDIDATE_SOURCES, type CandidateSource, type CsvImportSummary } from "../api/types";

const STEPS = ["Select Source", "Configure", "Import & Review", "Complete"];

// "manual" is the existing single-resume-upload flow elsewhere in the app, not a bulk
// import source -- excluded here on purpose.
const IMPORT_SOURCES: { value: CandidateSource; icon: typeof WorkOutlineIcon }[] = [
  { value: "career_portal", icon: LanguageOutlinedIcon },
  { value: "csv_import", icon: UploadFileOutlinedIcon },
  { value: "linkedin", icon: WorkOutlineIcon },
  { value: "naukri", icon: WorkOutlineIcon },
  { value: "indeed", icon: WorkOutlineIcon },
  { value: "monster", icon: WorkOutlineIcon },
  { value: "shine", icon: WorkOutlineIcon },
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
  const [file, setFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<CsvImportSummary | null>(null);
  const [careerPortalCount, setCareerPortalCount] = useState<number | null>(null);
  const [stepError, setStepError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setActiveStep(0);
    setSelectedSource(initialSource ?? "");
    setFile(null);
    setImportResult(null);
    setCareerPortalCount(null);
    setStepError(null);
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
      if (selectedSource === "csv_import") {
        if (!file) {
          setStepError("Choose a CSV file to import");
          return;
        }
        setImporting(true);
        try {
          const result = await candidatesApi.importCsv(file);
          setImportResult(result);
          setActiveStep(2);
          onImported();
        } catch (err) {
          setStepError(extractErrorMessage(err, "Failed to import CSV"));
        } finally {
          setImporting(false);
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
      {IMPORT_SOURCES.map(({ value, icon: Icon }) => {
        const isSelected = selectedSource === value;
        const sourceConnected = isConnected(value);
        return (
          <Grid key={value} size={{ xs: 12, sm: 6, md: 4 }}>
            <Card variant="outlined" sx={{ borderColor: isSelected ? "primary.main" : undefined, height: "100%" }}>
              <CardActionArea onClick={() => setSelectedSource(value)} sx={{ height: "100%", p: 1 }}>
                <CardContent>
                  <Stack direction="row" spacing={1.5} alignItems="center" mb={1}>
                    <Icon color={isSelected ? "primary" : "action"} />
                    <Typography variant="subtitle1">{candidateSourceLabel(value)}</Typography>
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
    // csv_import
    return (
      <Stack spacing={2} mt={2}>
        <Typography variant="body2" color="text.secondary">
          Upload a CSV with columns for name, email, phone (optional), and a resume link (optional, must be an
          http(s) URL -- a bare filename can't refer to anything on the server). Header names are matched
          case-insensitively.
        </Typography>
        <Stack direction="row" spacing={2} alignItems="center">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </Stack>
        {file && (
          <Typography variant="caption" color="text.secondary">
            Selected: {file.name}
          </Typography>
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
    if (!importResult) {
      return (
        <Box mt={2}>
          <CircularProgress size={20} />
        </Box>
      );
    }
    return (
      <Stack spacing={2} mt={2}>
        <Alert severity={importResult.skipped === 0 ? "success" : "warning"}>
          Imported {importResult.imported}, skipped {importResult.skipped}.
        </Alert>
        {importResult.errors.length > 0 && (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Row</TableCell>
                <TableCell>Reason</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {importResult.errors.map((err) => (
                <TableRow key={err.row}>
                  <TableCell>{err.row}</TableCell>
                  <TableCell>{err.reason}</TableCell>
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
