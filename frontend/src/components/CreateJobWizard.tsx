import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import FormControlLabel from "@mui/material/FormControlLabel";
import MuiLink from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Step from "@mui/material/Step";
import StepLabel from "@mui/material/StepLabel";
import Stepper from "@mui/material/Stepper";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, integrationsApi, jobsApi } from "../api/client";
import type { JobFieldSuggestionsResponse, JobRoleRead } from "../api/types";
import { formatExperienceRange } from "../utils/experience";

const EMPTY_SUGGESTIONS: JobFieldSuggestionsResponse = { departments: [], locations: [], skills: [] };

// JD generation moved to step 4 (after Requirements/Salary/Additional Info, not
// immediately after Job Details) specifically so the AI has skills, salary band,
// benefits, and additional notes to draw on -- see app/ai_services/jd_generator.py.
const STEPS = [
  "Job Details",
  "Requirements",
  "Salary & Benefits",
  "Additional Info",
  "Job Description",
  "Review & Publish",
];

const JOB_TYPES = ["Full-time", "Part-time", "Contract"];

// Same cross-category rule as the backend's JobRoleBase/JobRoleUpdate validators (see
// backend/app/schemas/job.py _find_skill_in_multiple_categories) -- checked client-side
// too so the wizard can flag it before a save round-trip. A skill repeated within the
// SAME category is left alone; only a skill appearing under more than one of the 4
// fields is a contradiction.
function findSkillInMultipleCategories(categories: string[][]): string | null {
  const seenInCategory = new Map<string, number>();
  for (let i = 0; i < categories.length; i++) {
    for (const skill of categories[i]) {
      const key = skill.trim().toLowerCase();
      const firstSeenIn = seenInCategory.get(key);
      if (firstSeenIn !== undefined && firstSeenIn !== i) return skill;
      seenInCategory.set(key, i);
    }
  }
  return null;
}

const EMPTY_STATE = {
  title: "",
  department: "",
  location: "",
  experienceMinYears: "",
  experienceMaxYears: "",
  jobType: "Full-time",
  positionsCount: "1",
  jdText: "",
  technicalSkillsMustHave: [] as string[],
  technicalSkillsGoodToHave: [] as string[],
  softSkillsMustHave: [] as string[],
  softSkillsGoodToHave: [] as string[],
  salaryMin: "",
  salaryMax: "",
  benefits: "",
  additionalNotes: "",
  naukri: false,
  linkedin: false,
  careerPortal: true,
  postingUrlNaukri: "",
  postingUrlLinkedin: "",
  emailNotifications: false,
  applicationDeadline: "",
};

// Converts an existing job back into the wizard's flat form shape, for the jobs table's
// "Edit" action -- reopens this same wizard (rather than a separate edit screen) pre-filled
// so every step's existing save-as-you-go logic (jobId set -> update, not create) just works.
function formFromJob(job: JobRoleRead): typeof EMPTY_STATE {
  const platforms = job.published_platforms as Record<string, boolean>;
  const settings = job.publish_settings as Record<string, unknown>;
  return {
    ...EMPTY_STATE,
    title: job.title,
    department: job.department || "",
    location: job.location || "",
    experienceMinYears: job.experience_min_years != null ? String(job.experience_min_years) : "",
    experienceMaxYears: job.experience_max_years != null ? String(job.experience_max_years) : "",
    jobType: job.job_type || "Full-time",
    positionsCount: String(job.positions_count ?? 1),
    jdText: job.jd_text || "",
    technicalSkillsMustHave: job.technical_skills_must_have || [],
    technicalSkillsGoodToHave: job.technical_skills_good_to_have || [],
    softSkillsMustHave: job.soft_skills_must_have || [],
    softSkillsGoodToHave: job.soft_skills_good_to_have || [],
    salaryMin: job.salary_band_min != null ? String(job.salary_band_min) : "",
    salaryMax: job.salary_band_max != null ? String(job.salary_band_max) : "",
    benefits: job.benefits || "",
    additionalNotes: job.additional_notes || "",
    naukri: Boolean(platforms?.naukri),
    linkedin: Boolean(platforms?.linkedin),
    careerPortal: Boolean(platforms?.career_portal),
    postingUrlNaukri: job.posting_url_naukri || "",
    postingUrlLinkedin: job.posting_url_linkedin || "",
    emailNotifications: Boolean(settings?.email_notifications),
    applicationDeadline: (settings?.application_deadline as string) || "",
  };
}

interface Props {
  open: boolean;
  onClose: () => void;
  onPublished: (job: JobRoleRead) => void;
  // When set, the wizard opens pre-filled for this existing job (the jobs table's "Edit"
  // action) instead of starting a new one.
  initialJob?: JobRoleRead | null;
}

export default function CreateJobWizard({ open, onClose, onPublished, initialJob }: Props) {
  const [activeStep, setActiveStep] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobRoleRead | null>(null);
  const [form, setForm] = useState(EMPTY_STATE);
  const [saving, setSaving] = useState(false);
  const [generatingJd, setGeneratingJd] = useState(false);
  const [stepError, setStepError] = useState<string | null>(null);
  const [published, setPublished] = useState<JobRoleRead | null>(null);
  const [googleConnected, setGoogleConnected] = useState<boolean | null>(null);
  const [linkedinConnected, setLinkedinConnected] = useState<boolean | null>(null);
  const [linkedinExpired, setLinkedinExpired] = useState(false);
  const [suggestions, setSuggestions] = useState<JobFieldSuggestionsResponse>(EMPTY_SUGGESTIONS);

  useEffect(() => {
    if (!open) return;
    if (initialJob) {
      setJobId(initialJob.id);
      setJob(initialJob);
      setForm(formFromJob(initialJob));
    }
    integrationsApi
      .googleStatus()
      .then((status) => setGoogleConnected(status.connected))
      .catch(() => setGoogleConnected(false));
    integrationsApi
      .linkedinStatus()
      .then((status) => {
        setLinkedinConnected(status.connected);
        setLinkedinExpired(Boolean(status.expired));
      })
      .catch(() => setLinkedinConnected(false));
    jobsApi
      .fieldSuggestions()
      .then(setSuggestions)
      .catch(() => setSuggestions(EMPTY_SUGGESTIONS));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialJob]);

  const set = <K extends keyof typeof EMPTY_STATE>(key: K, value: (typeof EMPTY_STATE)[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const reset = () => {
    setActiveStep(0);
    setJobId(null);
    setJob(null);
    setForm(EMPTY_STATE);
    setStepError(null);
    setPublished(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const validateStep = (step: number): string | null => {
    if (step === 0) {
      if (!form.title.trim()) return "Title is required";
      const positions = Number(form.positionsCount);
      if (!Number.isFinite(positions) || positions < 1) return "Positions must be at least 1";
      if (form.experienceMinYears.trim()) {
        const min = Number(form.experienceMinYears);
        if (!Number.isFinite(min) || min < 0) return "Min experience must be 0 or greater";
      }
      if (form.experienceMaxYears.trim()) {
        const max = Number(form.experienceMaxYears);
        if (!Number.isFinite(max) || max < 0) return "Max experience must be 0 or greater";
      }
      if (form.experienceMinYears.trim() && form.experienceMaxYears.trim()) {
        if (Number(form.experienceMaxYears) < Number(form.experienceMinYears)) {
          return "Max experience must be greater than or equal to min experience";
        }
      }
      return null;
    }
    if (step === 1) {
      const categories = [
        form.technicalSkillsMustHave, form.technicalSkillsGoodToHave,
        form.softSkillsMustHave, form.softSkillsGoodToHave,
      ];
      if (categories.every((category) => category.length === 0)) return "Add at least one skill";
      const duplicate = findSkillInMultipleCategories(categories);
      if (duplicate) return `"${duplicate}" cannot be in more than one skill category`;
      return null;
    }
    if (step === 2) {
      if (form.salaryMin && form.salaryMax && Number(form.salaryMax) < Number(form.salaryMin)) {
        return "Salary max must be greater than or equal to salary min";
      }
      return null;
    }
    if (step === 4) {
      if (!form.jdText.trim()) return "Generate or write a job description before continuing";
      return null;
    }
    return null;
  };

  // freeSolo + multiple normally adds whatever was typed/pasted as a single chip verbatim
  // -- "createOption" fires with the raw text as the newest entry in `newValue`, and
  // "blur" (via the Autocomplete's autoSelect prop below) fires the same way when focus
  // leaves without pressing Enter first. Splitting only on those two reasons -- never on
  // "selectOption"/"removeOption"/"clear" -- leaves picking a dropdown suggestion or
  // removing a chip completely untouched.
  const handleSkillsChange = (
    key: "technicalSkillsMustHave" | "technicalSkillsGoodToHave" | "softSkillsMustHave" | "softSkillsGoodToHave",
    newValue: string[],
    reason: string,
  ) => {
    const committedNewText = reason === "createOption" || reason === "blur";
    const raw = newValue[newValue.length - 1];
    if (committedNewText && typeof raw === "string" && raw.includes(",")) {
      const segments = raw
        .split(",")
        .map((segment) => segment.trim())
        .filter(Boolean);
      set(key, Array.from(new Set([...newValue.slice(0, -1), ...segments])));
      return;
    }
    set(key, newValue);
  };

  // One instance of the same creatable-autocomplete pattern the single "Skills" field
  // used to be, reused 4x (technical/soft x must-have/good-to-have) instead of 1x.
  const renderSkillsField = (
    key: "technicalSkillsMustHave" | "technicalSkillsGoodToHave" | "softSkillsMustHave" | "softSkillsGoodToHave",
    label: string,
  ) => (
    <Autocomplete
      multiple
      freeSolo
      autoSelect
      options={suggestions.skills}
      value={form[key]}
      onChange={(_e, value, reason) => handleSkillsChange(key, value, reason)}
      renderTags={(selected, getTagProps) =>
        selected.map((skill, index) => {
          const { key: tagKey, ...tagProps } = getTagProps({ index });
          return <Chip key={tagKey} label={skill} size="small" {...tagProps} />;
        })
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          helperText="Pick an existing skill, or type one (or several, comma-separated) and press Enter"
        />
      )}
    />
  );

  const handleGenerateJd = async () => {
    if (!jobId) return;
    setGeneratingJd(true);
    setStepError(null);
    try {
      const updated = await jobsApi.generateJd(jobId);
      setJob(updated);
      set("jdText", updated.jd_text || "");
    } catch (err) {
      setStepError(extractErrorMessage(err, "Failed to generate job description"));
    } finally {
      setGeneratingJd(false);
    }
  };

  const handleNext = async () => {
    const validationError = validateStep(activeStep);
    if (validationError) {
      setStepError(validationError);
      return;
    }
    setStepError(null);
    setSaving(true);
    try {
      if (activeStep === 0) {
        const payload = {
          title: form.title.trim(),
          department: form.department.trim() || null,
          location: form.location.trim() || null,
          experience_min_years: form.experienceMinYears.trim() ? Number(form.experienceMinYears) : null,
          experience_max_years: form.experienceMaxYears.trim() ? Number(form.experienceMaxYears) : null,
          job_type: form.jobType,
          positions_count: Number(form.positionsCount) || 1,
        };
        const updated = jobId ? await jobsApi.update(jobId, payload) : await jobsApi.create(payload);
        setJobId(updated.id);
        setJob(updated);
      } else if (activeStep === 1) {
        const updated = await jobsApi.update(jobId!, {
          technical_skills_must_have: form.technicalSkillsMustHave,
          technical_skills_good_to_have: form.technicalSkillsGoodToHave,
          soft_skills_must_have: form.softSkillsMustHave,
          soft_skills_good_to_have: form.softSkillsGoodToHave,
        });
        setJob(updated);
      } else if (activeStep === 2) {
        const updated = await jobsApi.update(jobId!, {
          salary_band_min: form.salaryMin ? Number(form.salaryMin) : null,
          salary_band_max: form.salaryMax ? Number(form.salaryMax) : null,
          benefits: form.benefits.trim() || null,
        });
        setJob(updated);
      } else if (activeStep === 3) {
        const updated = await jobsApi.update(jobId!, {
          additional_notes: form.additionalNotes.trim() || null,
        });
        setJob(updated);
      } else if (activeStep === 4) {
        if (jobId && job && job.jd_text !== form.jdText) {
          const updated = await jobsApi.update(jobId, { jd_text: form.jdText });
          setJob(updated);
        }
      }
      setActiveStep((s) => s + 1);
    } catch (err) {
      setStepError(extractErrorMessage(err, "Failed to save this step"));
    } finally {
      setSaving(false);
    }
  };

  const handleBack = () => {
    setStepError(null);
    setActiveStep((s) => Math.max(0, s - 1));
  };

  const handlePublish = async () => {
    if (!form.naukri && !form.linkedin && !form.careerPortal) {
      setStepError("Select at least one platform before publishing");
      return;
    }
    setStepError(null);
    setSaving(true);
    try {
      const updated = await jobsApi.publishPlatforms(jobId!, {
        naukri: form.naukri,
        linkedin: form.linkedin,
        career_portal: form.careerPortal,
        posting_url_naukri: form.postingUrlNaukri.trim() || null,
        posting_url_linkedin: form.postingUrlLinkedin.trim() || null,
        email_notifications: form.emailNotifications,
        application_deadline: form.applicationDeadline || null,
      });
      setJob(updated);
      setPublished(updated);
      onPublished(updated);
    } catch (err) {
      setStepError(extractErrorMessage(err, "Failed to publish job"));
    } finally {
      setSaving(false);
    }
  };

  const renderStep = () => {
    switch (activeStep) {
      case 0:
        return (
          <Stack spacing={2} mt={1}>
            <TextField label="Title" required value={form.title} onChange={(e) => set("title", e.target.value)} fullWidth autoFocus />
            <Autocomplete
              freeSolo
              options={suggestions.departments}
              value={form.department}
              onInputChange={(_e, value) => set("department", value)}
              renderInput={(params) => <TextField {...params} label="Department" fullWidth />}
            />
            <Autocomplete
              freeSolo
              options={suggestions.locations}
              value={form.location}
              onInputChange={(_e, value) => set("location", value)}
              renderInput={(params) => <TextField {...params} label="Location" fullWidth />}
            />
            <Stack direction="row" spacing={2}>
              <TextField
                label="Min Experience (years)"
                type="number"
                inputProps={{ min: 0, step: 0.5 }}
                value={form.experienceMinYears}
                onChange={(e) => set("experienceMinYears", e.target.value)}
                fullWidth
              />
              <TextField
                label="Max Experience (years)"
                type="number"
                inputProps={{ min: 0, step: 0.5 }}
                placeholder="Blank for open-ended (e.g. 5+ years)"
                value={form.experienceMaxYears}
                onChange={(e) => set("experienceMaxYears", e.target.value)}
                fullWidth
              />
            </Stack>
            <TextField
              select
              label="Job type"
              value={form.jobType}
              onChange={(e) => set("jobType", e.target.value)}
              fullWidth
            >
              {JOB_TYPES.map((type) => (
                <MenuItem key={type} value={type}>
                  {type}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Positions count"
              type="number"
              value={form.positionsCount}
              onChange={(e) => set("positionsCount", e.target.value)}
              fullWidth
            />
          </Stack>
        );
      case 1:
        return (
          <Stack spacing={3} mt={1}>
            <Stack spacing={2}>
              <Typography variant="subtitle2">Technical Skills</Typography>
              {renderSkillsField("technicalSkillsMustHave", "Must Have")}
              {renderSkillsField("technicalSkillsGoodToHave", "Good to Have")}
            </Stack>
            <Stack spacing={2}>
              <Typography variant="subtitle2">Soft Skills</Typography>
              {renderSkillsField("softSkillsMustHave", "Must Have")}
              {renderSkillsField("softSkillsGoodToHave", "Good to Have")}
            </Stack>
          </Stack>
        );
      case 2:
        return (
          <Stack spacing={2} mt={1}>
            <Stack direction="row" spacing={2}>
              <TextField
                label="Salary band min"
                type="number"
                value={form.salaryMin}
                onChange={(e) => set("salaryMin", e.target.value)}
                fullWidth
              />
              <TextField
                label="Salary band max"
                type="number"
                value={form.salaryMax}
                onChange={(e) => set("salaryMax", e.target.value)}
                fullWidth
              />
            </Stack>
            <TextField
              label="Benefits (optional)"
              value={form.benefits}
              onChange={(e) => set("benefits", e.target.value)}
              multiline
              minRows={3}
              fullWidth
            />
          </Stack>
        );
      case 3:
        return (
          <Stack spacing={2} mt={1}>
            <TextField
              label="Additional notes (optional)"
              value={form.additionalNotes}
              onChange={(e) => set("additionalNotes", e.target.value)}
              multiline
              minRows={4}
              fullWidth
            />
          </Stack>
        );
      case 4:
        return (
          <Stack spacing={2} mt={1}>
            <Typography variant="body2" color="text.secondary">
              Generate a job description with AI, using everything collected so far
              (requirements, salary band, benefits, and additional notes), or write your
              own below.
            </Typography>
            <Button variant="outlined" onClick={handleGenerateJd} disabled={generatingJd} sx={{ alignSelf: "flex-start" }}>
              {generatingJd ? "Generating..." : "Generate JD"}
            </Button>
            <TextField
              label="Job description"
              value={form.jdText}
              onChange={(e) => set("jdText", e.target.value)}
              multiline
              minRows={8}
              fullWidth
            />
          </Stack>
        );
      case 5:
        return published ? renderSuccess() : renderReviewAndPublish();
      default:
        return null;
    }
  };

  const reviewSkills = {
    mustHave: [...form.technicalSkillsMustHave, ...form.softSkillsMustHave],
    goodToHave: [...form.technicalSkillsGoodToHave, ...form.softSkillsGoodToHave],
  };

  const renderReviewAndPublish = () => (
    <Stack spacing={2} mt={1}>
      <Typography variant="subtitle1">Review</Typography>
      <Stack spacing={0.5}>
        <Typography variant="body2">
          <strong>{form.title}</strong>
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {[
            form.department,
            form.location,
            formatExperienceRange(
              form.experienceMinYears ? Number(form.experienceMinYears) : null,
              form.experienceMaxYears ? Number(form.experienceMaxYears) : null,
            ),
          ]
            .filter(Boolean)
            .join(" · ") || "No details set"}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {form.jobType} · Positions: {form.positionsCount}
          {form.salaryMin && form.salaryMax ? ` · Salary band: ${form.salaryMin} - ${form.salaryMax}` : ""}
        </Typography>
        {(reviewSkills.mustHave.length > 0 || reviewSkills.goodToHave.length > 0) && (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap mt={0.5}>
            {reviewSkills.mustHave.map((skill) => (
              <Chip key={`must-${skill}`} label={skill} size="small" />
            ))}
            {reviewSkills.goodToHave.map((skill) => (
              <Chip key={`good-${skill}`} label={skill} size="small" variant="outlined" />
            ))}
          </Stack>
        )}
        {form.benefits && (
          <Typography variant="body2" color="text.secondary" mt={0.5}>
            Benefits: {form.benefits}
          </Typography>
        )}
        {form.additionalNotes && (
          <Typography variant="body2" color="text.secondary">
            Notes: {form.additionalNotes}
          </Typography>
        )}
      </Stack>

      <Divider />

      <Typography variant="subtitle1">Publish to Platforms</Typography>
      <FormControlLabel
        control={<Switch checked={form.naukri} onChange={(e) => set("naukri", e.target.checked)} />}
        label="Naukri.com"
      />
      <Typography variant="caption" color="text.secondary" sx={{ mt: -1.5, ml: 4 }}>
        No posting API access available -- will be marked as posted here, but posting must be done manually on Naukri.com.
      </Typography>
      {form.naukri && (
        <TextField
          label="Job posting URL (paste after posting manually)"
          value={form.postingUrlNaukri}
          onChange={(e) => set("postingUrlNaukri", e.target.value)}
          size="small"
          fullWidth
          sx={{ ml: 4, maxWidth: 420 }}
        />
      )}
      <FormControlLabel
        control={<Switch checked={form.linkedin} onChange={(e) => set("linkedin", e.target.checked)} />}
        label="LinkedIn"
      />
      <Typography variant="caption" color="text.secondary" sx={{ mt: -1.5, ml: 4 }}>
        {linkedinConnected && !linkedinExpired
          ? "Real: a hiring announcement will be posted to your own LinkedIn feed."
          : linkedinExpired
            ? "Your LinkedIn connection has expired -- reconnect in Settings for a real post, or paste a manual link below for now."
            : "No LinkedIn connection -- connect in Settings for a real post, or paste a manual link below."}
      </Typography>
      {form.linkedin && !(linkedinConnected && !linkedinExpired) && (
        <TextField
          label="Job posting URL (paste after posting manually)"
          value={form.postingUrlLinkedin}
          onChange={(e) => set("postingUrlLinkedin", e.target.value)}
          size="small"
          fullWidth
          sx={{ ml: 4, maxWidth: 420 }}
        />
      )}
      <FormControlLabel
        control={<Switch checked={form.careerPortal} onChange={(e) => set("careerPortal", e.target.checked)} />}
        label="Career Portal"
      />
      <Typography variant="caption" color="text.secondary" sx={{ mt: -1.5, ml: 4 }}>
        Real: checking this publishes the job live on the public careers page immediately; unchecking un-publishes it.
      </Typography>
      {form.careerPortal && (
        <Box sx={{ ml: 4 }}>
          {job?.status === "published" ? (
            <Typography variant="body2">
              Live on Career Portal:{" "}
              <MuiLink href={`${window.location.origin}/careers/${job.id}`} target="_blank" rel="noopener noreferrer">
                {`${window.location.origin}/careers/${job.id}`}
              </MuiLink>
            </Typography>
          ) : (
            <Typography variant="caption" color="text.secondary">
              Will be live on the Career Portal once published.
            </Typography>
          )}
        </Box>
      )}

      <Divider />

      <Typography variant="subtitle2" color="text.secondary">
        Additional options
      </Typography>
      <FormControlLabel
        control={
          <Switch checked={form.emailNotifications} onChange={(e) => set("emailNotifications", e.target.checked)} />
        }
        label="Email notifications"
      />
      <Typography variant="caption" color="text.secondary" sx={{ mt: -1.5, ml: 4 }}>
        {googleConnected
          ? "Real: you'll get an email at your own inbox (via your connected Google account) when a new application comes in for this job."
          : "Coming soon for you -- connect Google in Settings first. Once connected, this sends a real email to your inbox when a new application comes in."}
      </Typography>
      <TextField
        label="Application deadline (optional)"
        type="date"
        value={form.applicationDeadline}
        onChange={(e) => set("applicationDeadline", e.target.value)}
        InputLabelProps={{ shrink: true }}
        helperText="Real: once this date passes, the job automatically closes and stops accepting applications."
        sx={{ maxWidth: 280 }}
      />
    </Stack>
  );

  const renderSuccess = () => {
    if (!published) return null;
    const platforms = published.published_platforms as Record<string, boolean>;
    const careersUrl = `${window.location.origin}/careers/${published.id}`;
    return (
      <Stack spacing={2} mt={1}>
        <Alert severity="success">Job published!</Alert>
        <Stack spacing={1}>
          {platforms.career_portal && (
            <Typography variant="body2">
              <strong>Career Portal</strong> — Published:{" "}
              <MuiLink href={careersUrl} target="_blank" rel="noopener noreferrer">
                {careersUrl}
              </MuiLink>
            </Typography>
          )}
          {platforms.naukri && (
            <Typography variant="body2">
              <strong>Naukri.com</strong> — Marked for manual posting (no automated posting; post this manually on
              Naukri.com)
              {published.posting_url_naukri && (
                <>
                  {" — "}
                  <MuiLink href={published.posting_url_naukri} target="_blank" rel="noopener noreferrer">
                    view posting
                  </MuiLink>
                </>
              )}
            </Typography>
          )}
          {platforms.linkedin && (
            <Typography variant="body2">
              <strong>LinkedIn</strong>{" "}
              {published.linkedin_post_urn ? (
                <>
                  — Published to your LinkedIn feed:{" "}
                  <MuiLink
                    href={`https://www.linkedin.com/feed/update/${published.linkedin_post_urn}/`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    view post
                  </MuiLink>
                </>
              ) : (
                <>
                  — Marked for manual posting (no automated posting; post this manually on LinkedIn)
                  {published.posting_url_linkedin && (
                    <>
                      {" — "}
                      <MuiLink href={published.posting_url_linkedin} target="_blank" rel="noopener noreferrer">
                        view posting
                      </MuiLink>
                    </>
                  )}
                </>
              )}
            </Typography>
          )}
        </Stack>
      </Stack>
    );
  };

  const isLastStep = activeStep === STEPS.length - 1;

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="md">
      <DialogTitle>{initialJob ? "Edit Job" : "Create Job"}</DialogTitle>
      <DialogContent>
        <Stepper activeStep={activeStep} sx={{ mt: 1, mb: 2 }}>
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>

        {stepError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {stepError}
          </Alert>
        )}

        <Box>{renderStep()}</Box>
      </DialogContent>
      <DialogActions>
        {published ? (
          <Button variant="contained" onClick={handleClose}>
            Done
          </Button>
        ) : (
          <>
            <Button onClick={handleClose}>Cancel</Button>
            <Button onClick={handleBack} disabled={activeStep === 0 || saving}>
              Back
            </Button>
            {isLastStep ? (
              <Button variant="contained" onClick={handlePublish} disabled={saving}>
                {saving ? "Publishing..." : "Publish"}
              </Button>
            ) : (
              <Button variant="contained" onClick={handleNext} disabled={saving}>
                {saving ? "Saving..." : "Next"}
              </Button>
            )}
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
