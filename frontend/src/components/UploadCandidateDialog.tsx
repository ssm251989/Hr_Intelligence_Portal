import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { Link as RouterLink } from "react-router-dom";

import { applicationsApi, candidatesApi, extractErrorMessage, jobsApi } from "../api/client";
import type { CandidateApplicationRow, CandidateRead, JobRoleRead } from "../api/types";
import { useT } from "../i18n";
import CandidateAvatar from "./CandidateAvatar";
import ParseProblem, { type ParseProblemInfo, parseProblemFrom } from "./candidates/ParseProblem";
import { useFresh } from "./candidates/stages";

// Manual single-candidate upload + link-to-job -- the only existing real functionality
// from the old flat Candidates page, kept as a secondary action for attaching one resume
// at a time and immediately linking it to a job (bulk local import, which just creates
// candidates without linking them anywhere, lives on its own page -- see
// /candidates/import). Shared between the Candidates List page ("Upload Resume") and the
// Candidates Dashboard ("Add Candidate") so the flow only exists once.
export default function UploadCandidateDialog({
  open,
  onClose,
  onLinked,
}: {
  open: boolean;
  onClose: () => void;
  onLinked?: () => void;
}) {
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadedCandidate, setUploadedCandidate] = useState<CandidateRead | null>(null);
  // Auto-parse runs right after upload, same as the public careers portal's background
  // parsing -- distinct from `uploading` so the dialog can show "Uploading..." then
  // "Parsing resume..." as two separate, honest stages rather than one long spinner.
  const [parsing, setParsing] = useState(false);
  const [parseProblem, setParseProblem] = useState<ParseProblemInfo | null>(null);
  const [linkJobId, setLinkJobId] = useState("");
  const [linkExpectedSalary, setLinkExpectedSalary] = useState("");
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Part 15.4 C3: after parsing, a best-effort look-up of someone already on file with the
  // same email. There is no merge endpoint, so this only stops and offers their existing
  // profile -- the recruiter can still carry on and link this upload.
  const [possibleDuplicate, setPossibleDuplicate] = useState<CandidateApplicationRow | null>(null);
  const t = useT();
  const f = useFresh();

  useEffect(() => {
    if (!open) return;
    setSelectedFile(null);
    setUploadError(null);
    setUploadedCandidate(null);
    setParsing(false);
    setParseProblem(null);
    setLinkJobId("");
    setLinkExpectedSalary("");
    setLinkError(null);
    setPossibleDuplicate(null);
    jobsApi.list().then(setJobs).catch(() => setJobs([]));
  }, [open]);

  const handleUpload = async () => {
    if (!selectedFile) {
      setUploadError("Choose a resume file first");
      return;
    }
    setUploadError(null);
    setUploading(true);
    let created: CandidateRead;
    try {
      created = await candidatesApi.upload(selectedFile);
      setUploadedCandidate(created);
    } catch (err) {
      setUploadError(extractErrorMessage(err, "Failed to upload resume"));
      setUploading(false);
      return;
    }
    setUploading(false);

    // Best-effort, matching the public careers portal's background parsing -- the
    // candidate already exists regardless of whether this succeeds, so a parse failure
    // here must never surface as an upload failure or block linking to a job below.
    await runParse(created.id);
  };

  // Also used by "Retry parsing" -- the real reason is shown when it fails (key, model, limit, file).
  const runParse = async (candidateId: string) => {
    setParsing(true);
    setParseProblem(null);
    try {
      const parsed = await candidatesApi.parseResume(candidateId);
      setUploadedCandidate(parsed);
      const email = parsed.email?.trim().toLowerCase();
      if (email) {
        try {
          const page = await candidatesApi.listApplications({ search: email, pageSize: 5 });
          setPossibleDuplicate(
            page.items.find((row) => row.candidate_id !== parsed.id && row.candidate_email?.trim().toLowerCase() === email) ?? null,
          );
        } catch {
          // Best-effort only -- never blocks linking.
        }
      }
    } catch (err) {
      setParseProblem(parseProblemFrom(err, t("candidates.parse.unknown")));
    } finally {
      setParsing(false);
    }
  };

  const handleLink = async () => {
    if (!uploadedCandidate) return;
    if (!linkJobId) {
      setLinkError("Select a job");
      return;
    }
    setLinking(true);
    setLinkError(null);
    try {
      await applicationsApi.create({
        job_role_id: linkJobId,
        candidate_id: uploadedCandidate.id,
        expected_salary: linkExpectedSalary ? Number(linkExpectedSalary) : null,
      });
      onClose();
      onLinked?.();
    } catch (err) {
      setLinkError(extractErrorMessage(err, "Failed to link candidate to job"));
    } finally {
      setLinking(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{uploadedCandidate ? "Link to a Job" : "Upload Resume"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          {!uploadedCandidate ? (
            <>
              {uploadError && <Alert severity="error">{uploadError}</Alert>}
              <Stack direction="row" spacing={2} alignItems="center">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx,.doc,.jpg,.jpeg,.png"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
                />
              </Stack>
              <Typography variant="caption" color="text.secondary">
                PDF, Word (.docx / .doc) or a photo / scan (JPG, PNG). Creates a candidate with source "Manual" -- link them to a job next.
              </Typography>
            </>
          ) : (
            <>
              {linkError && <Alert severity="error">{linkError}</Alert>}
              <Alert severity="success">Resume uploaded. Link this candidate to a job to add them to the pipeline.</Alert>

              {parsing && (
                <Stack direction="row" spacing={1.5} alignItems="center">
                  <CircularProgress size={20} />
                  <Typography variant="body2" color="text.secondary">
                    Parsing resume...
                  </Typography>
                </Stack>
              )}

              {!parsing && !parseProblem && (uploadedCandidate.full_name || uploadedCandidate.photo_path) && (
                <Stack direction="row" spacing={1.5} alignItems="center">
                  <CandidateAvatar
                    candidateId={uploadedCandidate.id}
                    photoPath={uploadedCandidate.photo_path}
                    name={uploadedCandidate.full_name}
                    email={uploadedCandidate.email}
                    sx={{ width: 40, height: 40 }}
                  />
                  <Typography variant="body2">
                    Parsed: <strong>{uploadedCandidate.full_name || "Unnamed candidate"}</strong>
                  </Typography>
                </Stack>
              )}

              {!parsing && possibleDuplicate && (
                <Alert
                  severity="warning"
                  sx={{ bgcolor: f.sunSoft, color: f.ink }}
                  action={
                    <Button color="inherit" size="small" component={RouterLink} to={`/candidates/${possibleDuplicate.application_id}`} onClick={onClose}>
                      {t("candidates.upload.open_existing")}
                    </Button>
                  }
                >
                  <strong>{t("candidates.upload.duplicate_title", { name: possibleDuplicate.candidate_name || possibleDuplicate.candidate_email || "" })}</strong>
                  <br />
                  {t("candidates.upload.duplicate_body", { job: possibleDuplicate.job_title })}
                </Alert>
              )}

              {!parsing && parseProblem && (
                <ParseProblem problem={parseProblem} onRetry={() => runParse(uploadedCandidate.id)} retrying={parsing} />
              )}
              {!parsing && !parseProblem && uploadedCandidate.parsed_fields?.read_with === "ocr" && (
                <Alert severity="info">{t("candidates.parse.ocr_used")}</Alert>
              )}

              <TextField select label="Job" required value={linkJobId} onChange={(e) => setLinkJobId(e.target.value)} fullWidth>
                {jobs.length === 0 && <MenuItem disabled value="">No jobs available</MenuItem>}
                {jobs.map((job) => (
                  <MenuItem key={job.id} value={job.id}>
                    {job.title}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label="Expected salary (optional)"
                type="number"
                value={linkExpectedSalary}
                onChange={(e) => setLinkExpectedSalary(e.target.value)}
                fullWidth
              />
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={parsing}>
          {uploadedCandidate ? "Skip for now" : "Cancel"}
        </Button>
        {!uploadedCandidate ? (
          <Button variant="contained" onClick={handleUpload} disabled={uploading}>
            {uploading ? "Uploading..." : "Upload"}
          </Button>
        ) : (
          <Button variant="contained" onClick={handleLink} disabled={linking || parsing}>
            {linking ? "Linking..." : "Link to Job"}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
