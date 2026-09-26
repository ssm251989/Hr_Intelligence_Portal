import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, DragEvent, FormEvent } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";

import { ApiError, publicApi } from "../api/client";
import type { PublicJobRead } from "../api/types";
import { useT } from "../i18n";
import { EmptyState, Emoji, FriendlyError, Illustration } from "../ui-kit";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx"];

// A5: the SHORT apply form -- resume + contact details only; everything else is collected
// later in the process. Same fields and API call as before.
export default function CareersApplyPage() {
  const f = useTheme().palette.fresh;
  const t = useT();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const fileInput = useRef<HTMLInputElement>(null);
  const [job, setJob] = useState<PublicJobRead | null>(null);
  const [notFound, setNotFound] = useState(false);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [resume, setResume] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [dragging, setDragging] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!id) return;
    publicApi
      .getJob(id)
      .then(setJob)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) setNotFound(true);
      });
  }, [id]);

  const pickFile = (file: File | null) => {
    if (file && !ACCEPTED_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext))) {
      setProblem(t("careers.apply.bad_file"));
      setResume(null);
      if (fileInput.current) fileInput.current.value = "";
      return;
    }
    setProblem(null);
    setResume(file);
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => pickFile(e.target.files?.[0] ?? null);
  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    pickFile(e.dataTransfer.files?.[0] ?? null);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!id) return;
    if (!resume) {
      setProblem(t("careers.apply.need_resume"));
      return;
    }
    if (!consent) {
      setProblem(t("careers.apply.need_consent"));
      return;
    }

    setSubmitting(true);
    setProblem(null);
    setError(null);
    try {
      await publicApi.apply({ jobId: id, fullName, email, phone: phone || undefined, resume, consent });
      navigate(`/careers/${id}/thank-you`);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  if (notFound) {
    return (
      <Card>
        <EmptyState
          illustration="page-not-found"
          title={t("careers.gone_title")}
          hint={t("careers.gone_hint")}
          action={<Button component={RouterLink} to="/careers" variant="contained">{t("careers.view_open")}</Button>}
        />
      </Card>
    );
  }

  return (
    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "minmax(0, 560px) 1fr" }, gap: 4, alignItems: "start" }}>
      <Card sx={{ p: { xs: 2.5, sm: 4 } }}>
        <Typography variant="h1" component="h1" sx={{ fontSize: 28 }}>{t("careers.apply.title")}</Typography>
        <Typography sx={{ color: f.muted, mt: 0.5, mb: 3 }}>
          {job ? t("careers.apply.for", { title: job.title }) : t("careers.apply.loading")}
        </Typography>

        <Box component="form" onSubmit={handleSubmit}>
          <Stack spacing={2.5}>
            {problem && <FriendlyError compact what={problem} fix={t("careers.apply.fix")} />}
            {error !== null && <FriendlyError compact error={error} />}

            <Box
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
              sx={{
                border: `2px dashed ${dragging || resume ? f.brand : f.line}`, borderRadius: "16px", p: 2.5, textAlign: "center",
                bgcolor: resume ? f.brandSoft : f.surface2, transition: "background-color 160ms ease",
              }}
            >
              <Emoji name={resume ? "check" : "page"} size={32} />
              <Typography sx={{ fontWeight: 700, mt: 1 }}>{resume ? resume.name : t("careers.apply.resume_title")}</Typography>
              <Typography sx={{ color: f.muted, fontSize: 13, mb: 1.5 }}>{t("careers.apply.resume_hint")}</Typography>
              <Button component="label" variant={resume ? "outlined" : "contained"}>
                {resume ? t("careers.apply.resume_change") : t("careers.apply.resume_pick")}
                <input ref={fileInput} type="file" hidden accept=".pdf,.docx" onChange={handleFileChange} aria-label={t("careers.apply.resume_title")} />
              </Button>
            </Box>

            <TextField label={t("careers.apply.name")} required fullWidth autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
            <TextField label={t("careers.apply.email")} type="email" required fullWidth autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            <TextField label={t("careers.apply.phone")} fullWidth autoComplete="tel" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />

            <FormControlLabel
              control={<Checkbox checked={consent} onChange={(e) => setConsent(e.target.checked)} />}
              label={t("careers.apply.consent")}
            />

            <Button type="submit" variant="contained" size="large" disabled={submitting}>
              {submitting ? t("careers.apply.sending") : t("careers.apply.submit")}
            </Button>
            <Typography sx={{ color: f.muted, fontSize: 13, textAlign: "center" }}>{t("careers.apply.short_note")}</Typography>
          </Stack>
        </Box>
      </Card>
      <Box sx={{ display: { xs: "none", md: "block" }, pt: 4 }}>
        <Illustration name="resume" height={260} />
      </Box>
    </Box>
  );
}
