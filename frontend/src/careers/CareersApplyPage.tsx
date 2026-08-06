import { useEffect, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";

import { ApiError, extractErrorMessage, publicApi } from "../api/client";
import type { PublicJobRead } from "../api/types";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx"];

export default function CareersApplyPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<PublicJobRead | null>(null);
  const [notFound, setNotFound] = useState(false);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [resume, setResume] = useState<File | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    publicApi
      .getJob(id)
      .then(setJob)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) setNotFound(true);
      });
  }, [id]);

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    if (file && !ACCEPTED_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext))) {
      setError("Please upload your resume as a PDF or DOCX file.");
      setResume(null);
      e.target.value = "";
      return;
    }
    setError(null);
    setResume(file);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!id) return;
    if (!resume) {
      setError("Please attach your resume.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await publicApi.apply({ jobId: id, fullName, email, phone: phone || undefined, resume });
      navigate(`/careers/${id}/thank-you`);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to submit your application. Please try again."));
    } finally {
      setSubmitting(false);
    }
  };

  if (notFound) {
    return (
      <Box>
        <Typography variant="h5" mb={2}>
          This position is no longer available.
        </Typography>
        <Button component={RouterLink} to="/careers" variant="contained">
          View open positions
        </Button>
      </Box>
    );
  }

  return (
    <Box maxWidth={520}>
      <Typography variant="h4" fontWeight={700} mb={1}>
        Apply
      </Typography>
      <Typography variant="body1" color="text.secondary" mb={4}>
        {job ? `Applying for ${job.title}` : "Loading position details..."}
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Box component="form" onSubmit={handleSubmit}>
        <Stack spacing={2.5}>
          <TextField
            label="Full name"
            required
            fullWidth
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
          <TextField
            label="Email"
            type="email"
            required
            fullWidth
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <TextField
            label="Phone (optional)"
            fullWidth
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />

          <Box>
            <Button component="label" variant="outlined">
              {resume ? resume.name : "Upload resume (PDF or DOCX)"}
              <input type="file" hidden accept=".pdf,.docx" onChange={handleFileChange} />
            </Button>
          </Box>

          <Button type="submit" variant="contained" size="large" disabled={submitting}>
            {submitting ? "Submitting..." : "Submit Application"}
          </Button>
        </Stack>
      </Box>
    </Box>
  );
}
