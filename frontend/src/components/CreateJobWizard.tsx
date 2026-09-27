import { useEffect, useRef, useState, type ReactNode } from "react";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
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
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { experienceApi, integrationsApi, jobsApi } from "../api/client";
import { EDUCATION_DEGREE_LEVELS } from "../api/types";
import type { JobFieldSuggestionsResponse, JobRoleRead } from "../api/types";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import { useT } from "../i18n";
import { Emoji, FriendlyAnimation, FriendlyError, InfoTip } from "../ui-kit";
import { formatExperienceRange } from "../utils/experience";
import JdSideBySide from "./jobs/JdSideBySide";
import ScoringRulesEditor from "./scoring/ScoringRulesEditor";
import ShortlistingRulesForm from "./scoring/ShortlistingRulesForm";
import WizardProgress from "./jobs/WizardProgress";

const EMPTY_SUGGESTIONS: JobFieldSuggestionsResponse = {
  departments: [], locations: [], skills: [], certifications: [],
};

// JD generation sits at step 5 (after Requirements/Salary/Additional Info, not right after
// Job Details) specifically so the AI has skills, salary band, benefits and additional
// notes to draw on -- see app/ai_services/jd_generator.py.
const STEPS = [
  { key: "details", emoji: "briefcase" },
  { key: "requirements", emoji: "tools" },
  { key: "salary", emoji: "money" },
  { key: "extra", emoji: "memo" },
  { key: "jd", emoji: "page" },
  // Part 17.5/17.6: the job is already saved by now (step 1 creates it), so its own scoring and
  // shortlisting rules can be set here; each has its own Save (nothing is required).
  { key: "scoring", emoji: "target" },
  { key: "shortlisting", emoji: "check" },
  { key: "publish", emoji: "rocket" },
];

const JOB_TYPES = [
  { value: "Full-time", key: "jobs.type.full_time" },
  { value: "Part-time", key: "jobs.type.part_time" },
  { value: "Contract", key: "jobs.type.contract" },
];

// Autosaved, server-side wizard draft (Part 14 drafts API) -- so a half-typed job follows
// the user across devices and survives closing the dialog.
const DRAFT_FORM_KEY = "jobs.wizard";
const DRAFT_REF = "new";

// Same cross-category rule as the backend's JobRoleBase/JobRoleUpdate validators (see
// backend/app/schemas/job.py _find_skill_in_multiple_categories) -- checked client-side
// too so the wizard can flag it before a save round-trip.
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
  educationDegreeLevel: "",
  educationField: "",
  jobType: "Full-time",
  positionsCount: "1",
  jdText: "",
  technicalSkillsMustHave: [] as string[],
  technicalSkillsGoodToHave: [] as string[],
  softSkillsMustHave: [] as string[],
  softSkillsGoodToHave: [] as string[],
  preferredCertifications: [] as string[],
  salaryMin: "",
  salaryMax: "",
  benefits: "",
  additionalNotes: "",
  keyResponsibilities: "",
  naukri: false,
  linkedin: false,
  careerPortal: true,
  postingUrlNaukri: "",
  postingUrlLinkedin: "",
  emailNotifications: false,
  applicationDeadline: "",
};
type WizardForm = typeof EMPTY_STATE;

interface WizardDraft {
  form: WizardForm;
  jobId: string | null;
  step: number;
}

// Converts an existing job back into the wizard's flat form shape, for the jobs table's
// "Edit" action -- reopens this same wizard pre-filled so every step's existing
// save-as-you-go logic (jobId set -> update, not create) just works.
function formFromJob(job: JobRoleRead): WizardForm {
  const platforms = job.published_platforms as Record<string, boolean>;
  const settings = job.publish_settings as Record<string, unknown>;
  return {
    ...EMPTY_STATE,
    title: job.title,
    department: job.department || "",
    location: job.location || "",
    experienceMinYears: job.experience_min_years != null ? String(job.experience_min_years) : "",
    experienceMaxYears: job.experience_max_years != null ? String(job.experience_max_years) : "",
    educationDegreeLevel: job.education_degree_level || "",
    educationField: job.education_field || "",
    jobType: job.job_type || "Full-time",
    positionsCount: String(job.positions_count ?? 1),
    jdText: job.jd_text || "",
    technicalSkillsMustHave: job.technical_skills_must_have || [],
    technicalSkillsGoodToHave: job.technical_skills_good_to_have || [],
    softSkillsMustHave: job.soft_skills_must_have || [],
    softSkillsGoodToHave: job.soft_skills_good_to_have || [],
    preferredCertifications: job.preferred_certifications || [],
    salaryMin: job.salary_band_min != null ? String(job.salary_band_min) : "",
    salaryMax: job.salary_band_max != null ? String(job.salary_band_max) : "",
    benefits: job.benefits || "",
    additionalNotes: job.additional_notes || "",
    keyResponsibilities: job.key_responsibilities || "",
    naukri: Boolean(platforms?.naukri),
    linkedin: Boolean(platforms?.linkedin),
    careerPortal: Boolean(platforms?.career_portal),
    postingUrlNaukri: job.posting_url_naukri || "",
    postingUrlLinkedin: job.posting_url_linkedin || "",
    emailNotifications: Boolean(settings?.email_notifications),
    applicationDeadline: (settings?.application_deadline as string) || "",
  };
}

// J2: a template is a job posted before -- copy what describes the ROLE, not where/when it
// was posted (platforms, links, closing date start fresh).
export function formFromTemplate(job: JobRoleRead): WizardForm {
  return {
    ...formFromJob(job),
    naukri: false,
    linkedin: false,
    careerPortal: true,
    postingUrlNaukri: "",
    postingUrlLinkedin: "",
    emailNotifications: false,
    applicationDeadline: "",
  };
}

interface Props {
  open: boolean;
  onClose: () => void;
  onPublished: (job: JobRoleRead) => void;
  // When set, the wizard opens pre-filled for this existing job (the jobs table's "Edit"
  // action) instead of starting a new one.
  initialJob?: JobRoleRead | null;
  // J2: start a NEW job pre-filled from this one (template library).
  template?: JobRoleRead | null;
  // Jobs offered in step 1's "copy details from" picker.
  templates?: JobRoleRead[];
}

// A field with an (i) next to it -- the tip stays outside the input so it is its own
// keyboard stop and never fights the field for clicks.
function WithTip({ tip, children }: { tip: string; children: ReactNode }) {
  return (
    <Stack direction="row" spacing={0.5} alignItems="flex-start">
      <Box sx={{ flex: 1, minWidth: 0 }}>{children}</Box>
      <Box sx={{ pt: 1.5 }}>
        <InfoTip text={tip} />
      </Box>
    </Stack>
  );
}

export default function CreateJobWizard({ open, onClose, onPublished, initialJob, template, templates = [] }: Props) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { aiFeature } = useMeBootstrap();
  const aiEnabled = aiFeature("recruitment.jd_generation");
  const [activeStep, setActiveStep] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobRoleRead | null>(null);
  const [form, setForm] = useState<WizardForm>(EMPTY_STATE);
  const [saving, setSaving] = useState(false);
  const [generatingJd, setGeneratingJd] = useState(false);
  const [stepError, setStepError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<{ what: string; error: unknown } | null>(null);
  const [published, setPublished] = useState<JobRoleRead | null>(null);
  const [googleConnected, setGoogleConnected] = useState<boolean | null>(null);
  const [linkedinConnected, setLinkedinConnected] = useState<boolean | null>(null);
  const [linkedinExpired, setLinkedinExpired] = useState(false);
  const [suggestions, setSuggestions] = useState<JobFieldSuggestionsResponse>(EMPTY_SUGGESTIONS);
  const [copiedFrom, setCopiedFrom] = useState<string | null>(null);
  // unsaved changes on the Scoring / Shortlisting steps (they save themselves)
  const [rulesDirty, setRulesDirty] = useState(false);
  // autosave
  const [draftOffer, setDraftOffer] = useState<{ draft: WizardDraft; at: string | null } | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const touched = useRef(false);
  const saveTimer = useRef<number | undefined>(undefined);

  const draftsOn = open && !initialJob && !published;

  useEffect(() => {
    if (!open) return;
    if (initialJob) {
      setJobId(initialJob.id);
      setJob(initialJob);
      setForm(formFromJob(initialJob));
    } else if (template) {
      setForm(formFromTemplate(template));
      setCopiedFrom(template.title);
      touched.current = true;
    } else {
      experienceApi
        .getDraft(DRAFT_FORM_KEY, DRAFT_REF)
        .then((r) => {
          const d = r.data as unknown as WizardDraft | null;
          if (d && d.form && typeof d.form === "object") setDraftOffer({ draft: d, at: r.updated_at });
        })
        .catch(() => undefined);
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
  }, [open, initialJob, template]);

  // Debounced autosave of the whole wizard (form + which job it created + which step).
  useEffect(() => {
    if (!draftsOn || draftOffer || !touched.current) return;
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      const payload: WizardDraft = { form, jobId, step: activeStep };
      experienceApi
        .saveDraft(DRAFT_FORM_KEY, payload as unknown as Record<string, unknown>, DRAFT_REF)
        .then((r) => setSavedAt(r.updated_at))
        .catch(() => undefined);
    }, 1500);
    return () => window.clearTimeout(saveTimer.current);
  }, [draftsOn, draftOffer, form, jobId, activeStep]);

  const discardDraft = () => experienceApi.discardDraft(DRAFT_FORM_KEY, DRAFT_REF).catch(() => undefined);

  const restoreDraft = async () => {
    if (!draftOffer) return;
    const { draft } = draftOffer;
    setForm({ ...EMPTY_STATE, ...draft.form });
    touched.current = true;
    if (draft.jobId) {
      try {
        const existing = await jobsApi.get(draft.jobId);
        setJobId(existing.id);
        setJob(existing);
        setActiveStep(Math.min(Math.max(draft.step ?? 0, 0), STEPS.length - 1));
      } catch {
        setJobId(null);
        setJob(null);
        setActiveStep(0);
      }
    }
    setSavedAt(draftOffer.at);
    setDraftOffer(null);
  };

  const startFresh = () => {
    discardDraft();
    setDraftOffer(null);
  };

  const set = <K extends keyof WizardForm>(key: K, value: WizardForm[K]) => {
    touched.current = true;
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const applyTemplate = (source: JobRoleRead | null) => {
    if (!source) return;
    touched.current = true;
    setForm(formFromTemplate(source));
    setCopiedFrom(source.title);
  };

  const reset = () => {
    setRulesDirty(false);
    window.clearTimeout(saveTimer.current);
    touched.current = false;
    setActiveStep(0);
    setJobId(null);
    setJob(null);
    setForm(EMPTY_STATE);
    setStepError(null);
    setApiError(null);
    setPublished(null);
    setDraftOffer(null);
    setSavedAt(null);
    setCopiedFrom(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const validateStep = (step: number): string | null => {
    if (step === 0) {
      if (!form.title.trim()) return t("jobs.v.title");
      const positions = Number(form.positionsCount);
      if (!Number.isFinite(positions) || positions < 1) return t("jobs.v.positions");
      if (form.experienceMinYears.trim()) {
        const min = Number(form.experienceMinYears);
        if (!Number.isFinite(min) || min < 0) return t("jobs.v.exp_min");
      }
      if (form.experienceMaxYears.trim()) {
        const max = Number(form.experienceMaxYears);
        if (!Number.isFinite(max) || max < 0) return t("jobs.v.exp_max");
      }
      if (form.experienceMinYears.trim() && form.experienceMaxYears.trim()) {
        if (Number(form.experienceMaxYears) < Number(form.experienceMinYears)) return t("jobs.v.exp_order");
      }
      return null;
    }
    if (step === 1) {
      const categories = [form.technicalSkillsMustHave, form.technicalSkillsGoodToHave, form.softSkillsMustHave, form.softSkillsGoodToHave];
      if (categories.every((category) => category.length === 0)) return t("jobs.v.skills");
      const duplicate = findSkillInMultipleCategories(categories);
      if (duplicate) return t("jobs.v.skill_dup", { skill: duplicate });
      return null;
    }
    if (step === 2) {
      if (form.salaryMin && form.salaryMax && Number(form.salaryMax) < Number(form.salaryMin)) return t("jobs.v.salary");
      return null;
    }
    if (step === 4) {
      if (!form.jdText.trim()) return t(aiEnabled ? "jobs.v.jd_ai" : "jobs.v.jd");
      return null;
    }
    if (step === 5 || step === 6) {
      if (rulesDirty) return t("scoring.wiz.unsaved");
      return null;
    }
    return null;
  };

  // freeSolo + multiple normally adds whatever was typed/pasted as a single chip verbatim
  // -- "createOption" fires with the raw text as the newest entry in `newValue`, and
  // "blur" (via autoSelect) fires the same way when focus leaves without Enter. Splitting
  // only on those two reasons leaves picking a suggestion or removing a chip untouched.
  const handleSkillsChange = (
    key: "technicalSkillsMustHave" | "technicalSkillsGoodToHave" | "softSkillsMustHave" | "softSkillsGoodToHave" | "preferredCertifications",
    newValue: string[],
    reason: string,
  ) => {
    const committedNewText = reason === "createOption" || reason === "blur";
    const raw = newValue[newValue.length - 1];
    if (committedNewText && typeof raw === "string" && raw.includes(",")) {
      const segments = raw.split(",").map((segment) => segment.trim()).filter(Boolean);
      set(key, Array.from(new Set([...newValue.slice(0, -1), ...segments])));
      return;
    }
    set(key, newValue);
  };

  const renderSkillsField = (
    key: "technicalSkillsMustHave" | "technicalSkillsGoodToHave" | "softSkillsMustHave" | "softSkillsGoodToHave" | "preferredCertifications",
    label: string,
    options: string[] = suggestions.skills,
    helperText = t("jobs.f.skills_help"),
  ) => (
    <Autocomplete
      multiple
      freeSolo
      autoSelect
      options={options}
      value={form[key]}
      onChange={(_e, value, reason) => handleSkillsChange(key, value, reason)}
      renderTags={(selected, getTagProps) =>
        selected.map((skill, index) => {
          const { key: tagKey, ...tagProps } = getTagProps({ index });
          return <Chip key={tagKey} label={skill} size="small" {...tagProps} />;
        })
      }
      renderInput={(params) => <TextField {...params} label={label} helperText={helperText} />}
    />
  );

  const handleGenerateJd = async (): Promise<string | null> => {
    if (!jobId) return null;
    setGeneratingJd(true);
    setStepError(null);
    setApiError(null);
    try {
      const updated = await jobsApi.generateJd(jobId);
      setJob(updated);
      set("jdText", updated.jd_text || "");
      return updated.jd_text || "";
    } catch (err) {
      setApiError({ what: t("jobs.err.ai"), error: err });
      return null;
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
    setApiError(null);
    setSaving(true);
    try {
      if (activeStep === 0) {
        const payload = {
          title: form.title.trim(),
          department: form.department.trim() || null,
          location: form.location.trim() || null,
          experience_min_years: form.experienceMinYears.trim() ? Number(form.experienceMinYears) : null,
          experience_max_years: form.experienceMaxYears.trim() ? Number(form.experienceMaxYears) : null,
          education_degree_level: form.educationDegreeLevel || null,
          education_field: form.educationField.trim() || null,
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
          preferred_certifications: form.preferredCertifications,
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
          key_responsibilities: form.keyResponsibilities.trim() || null,
          additional_notes: form.additionalNotes.trim() || null,
        });
        setJob(updated);
      } else if (activeStep === 4) {
        if (jobId && job && job.jd_text !== form.jdText) {
          const updated = await jobsApi.update(jobId, { jd_text: form.jdText });
          setJob(updated);
        }
      }
      setRulesDirty(false);
      setActiveStep((s) => s + 1);
    } catch (err) {
      setApiError({ what: t("jobs.err.save_step"), error: err });
    } finally {
      setSaving(false);
    }
  };

  const handleBack = () => {
    setRulesDirty(false);
    setStepError(null);
    setApiError(null);
    setActiveStep((s) => Math.max(0, s - 1));
  };

  const handlePublish = async () => {
    if (!form.naukri && !form.linkedin && !form.careerPortal) {
      setStepError(t("jobs.v.platform"));
      return;
    }
    setStepError(null);
    setApiError(null);
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
      window.clearTimeout(saveTimer.current);
      if (!initialJob) discardDraft();
      setJob(updated);
      setPublished(updated);
      onPublished(updated);
    } catch (err) {
      setApiError({ what: t("jobs.err.publish"), error: err });
    } finally {
      setSaving(false);
    }
  };

  const sectionTitle = (emoji: string, text: string) => (
    <Typography variant="subtitle1" component="h3" sx={{ fontWeight: 700, display: "flex", alignItems: "center", gap: 1 }}>
      <Emoji name={emoji} size={18} />
      {text}
    </Typography>
  );

  const aiInputs = [
    form.title,
    form.department,
    form.location,
    formatExperienceRange(form.experienceMinYears ? Number(form.experienceMinYears) : null, form.experienceMaxYears ? Number(form.experienceMaxYears) : null),
    ...[...form.technicalSkillsMustHave, ...form.softSkillsMustHave].slice(0, 6),
    form.salaryMin && form.salaryMax ? t("jobs.rev.salary", { min: form.salaryMin, max: form.salaryMax }) : "",
    form.benefits ? t("jobs.rev.benefits") : "",
    form.keyResponsibilities ? t("jobs.rev.responsibilities") : "",
    form.additionalNotes ? t("jobs.rev.notes") : "",
  ].filter((v): v is string => Boolean(v));

  const renderStep = () => {
    switch (activeStep) {
      case 0:
        return (
          <Stack spacing={2}>
            {!jobId && !initialJob && templates.length > 0 && (
              <Card sx={{ p: 2, bgcolor: f.surface2, boxShadow: "none", border: `1px dashed ${f.line}` }}>
                <WithTip tip={t("jobs.tpl.pick_tip")}>
                  <Autocomplete
                    options={templates}
                    getOptionLabel={(o) => [o.title, o.department, o.location].filter(Boolean).join(" · ")}
                    isOptionEqualToValue={(a, b) => a.id === b.id}
                    onChange={(_e, value) => applyTemplate(value)}
                    renderInput={(params) => <TextField {...params} size="small" label={t("jobs.tpl.pick_label")} />}
                  />
                </WithTip>
              </Card>
            )}
            {copiedFrom && (
              <Typography role="status" variant="body2" sx={{ p: 1.25, borderRadius: "12px", bgcolor: f.skySoft }}>
                {t("jobs.tpl.applied", { title: copiedFrom })}
              </Typography>
            )}
            <TextField label={t("jobs.f.title")} required value={form.title} onChange={(e) => set("title", e.target.value)} fullWidth autoFocus />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <Autocomplete
                freeSolo
                fullWidth
                options={suggestions.departments}
                value={form.department}
                onInputChange={(_e, value) => set("department", value)}
                renderInput={(params) => <TextField {...params} label={t("jobs.f.department")} fullWidth />}
              />
              <Autocomplete
                freeSolo
                fullWidth
                options={suggestions.locations}
                value={form.location}
                onInputChange={(_e, value) => set("location", value)}
                renderInput={(params) => <TextField {...params} label={t("jobs.f.location")} fullWidth />}
              />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField label={t("jobs.f.exp_min")} type="number" slotProps={{ htmlInput: { min: 0, step: 0.5 } }}
                value={form.experienceMinYears} onChange={(e) => set("experienceMinYears", e.target.value)} fullWidth />
              <TextField label={t("jobs.f.exp_max")} type="number" slotProps={{ htmlInput: { min: 0, step: 0.5 } }} placeholder={t("jobs.f.exp_max_ph")}
                value={form.experienceMaxYears} onChange={(e) => set("experienceMaxYears", e.target.value)} fullWidth />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField select label={t("jobs.f.edu_level")} value={form.educationDegreeLevel} onChange={(e) => set("educationDegreeLevel", e.target.value)} fullWidth>
                <MenuItem value="">
                  <em>{t("jobs.f.edu_none")}</em>
                </MenuItem>
                {EDUCATION_DEGREE_LEVELS.map((level) => (
                  <MenuItem key={level} value={level}>
                    {level}
                  </MenuItem>
                ))}
              </TextField>
              <TextField label={t("jobs.f.edu_field")} placeholder={t("jobs.f.edu_field_ph")} value={form.educationField}
                onChange={(e) => set("educationField", e.target.value)} fullWidth />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField select label={t("jobs.f.job_type")} value={form.jobType} onChange={(e) => set("jobType", e.target.value)} fullWidth>
                {JOB_TYPES.map((type) => (
                  <MenuItem key={type.value} value={type.value}>
                    {t(type.key)}
                  </MenuItem>
                ))}
              </TextField>
              <Box sx={{ width: "100%" }}>
                <WithTip tip={t("jobs.f.positions_tip")}>
                  <TextField label={t("jobs.f.positions")} type="number" slotProps={{ htmlInput: { min: 1 } }} value={form.positionsCount}
                    onChange={(e) => set("positionsCount", e.target.value)} fullWidth />
                </WithTip>
              </Box>
            </Stack>
          </Stack>
        );
      case 1:
        return (
          <Stack spacing={3}>
            <Stack spacing={2}>
              <Stack direction="row" alignItems="center">
                {sectionTitle("laptop", t("jobs.f.tech"))}
                <InfoTip text={t("jobs.f.must_tip")} />
              </Stack>
              {renderSkillsField("technicalSkillsMustHave", t("jobs.f.must"))}
              {renderSkillsField("technicalSkillsGoodToHave", t("jobs.f.good"))}
            </Stack>
            <Stack spacing={2}>
              {sectionTitle("handshake", t("jobs.f.soft"))}
              {renderSkillsField("softSkillsMustHave", t("jobs.f.must"))}
              {renderSkillsField("softSkillsGoodToHave", t("jobs.f.good"))}
            </Stack>
            <Stack spacing={2}>
              {sectionTitle("graduation", t("jobs.f.certs_title"))}
              {renderSkillsField("preferredCertifications", t("jobs.f.certs"), suggestions.certifications, t("jobs.f.certs_help"))}
            </Stack>
          </Stack>
        );
      case 2:
        return (
          <Stack spacing={2}>
            <WithTip tip={t("jobs.f.salary_tip")}>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                <TextField label={t("jobs.f.salary_min")} type="number" value={form.salaryMin} onChange={(e) => set("salaryMin", e.target.value)} fullWidth />
                <TextField label={t("jobs.f.salary_max")} type="number" value={form.salaryMax} onChange={(e) => set("salaryMax", e.target.value)} fullWidth />
              </Stack>
            </WithTip>
            <TextField label={t("jobs.f.benefits")} value={form.benefits} onChange={(e) => set("benefits", e.target.value)} multiline minRows={3} fullWidth />
          </Stack>
        );
      case 3:
        return (
          <Stack spacing={2}>
            <TextField label={t("jobs.f.responsibilities")} placeholder={t("jobs.f.responsibilities_ph")} value={form.keyResponsibilities}
              onChange={(e) => set("keyResponsibilities", e.target.value)} multiline minRows={4} fullWidth />
            <TextField label={t("jobs.f.notes")} value={form.additionalNotes} onChange={(e) => set("additionalNotes", e.target.value)} multiline minRows={4} fullWidth />
          </Stack>
        );
      case 4:
        return (
          <JdSideBySide
            value={form.jdText}
            onChange={(next) => set("jdText", next)}
            aiEnabled={aiEnabled}
            generating={generatingJd}
            onGenerate={handleGenerateJd}
            inputs={aiInputs}
          />
        );
      case 5:
        return jobId ? <ScoringRulesEditor jobId={jobId} onDirtyChange={setRulesDirty} /> : <Typography sx={{ color: f.muted }}>{t("scoring.wiz.save_first")}</Typography>;
      case 6:
        return jobId ? <ShortlistingRulesForm jobId={jobId} onDirtyChange={setRulesDirty} /> : <Typography sx={{ color: f.muted }}>{t("scoring.wiz.save_first")}</Typography>;
      case 7:
        return published ? renderSuccess() : renderReviewAndPublish();
      default:
        return null;
    }
  };

  const reviewSkills = {
    mustHave: [...form.technicalSkillsMustHave, ...form.softSkillsMustHave],
    goodToHave: [...form.technicalSkillsGoodToHave, ...form.softSkillsGoodToHave],
  };

  const platformNote = (text: string) => (
    <Typography variant="caption" sx={{ color: f.muted, mt: -1, ml: 6, display: "block" }}>
      {text}
    </Typography>
  );

  const renderReviewAndPublish = () => (
    <Stack spacing={2}>
      <Card sx={{ p: 2, bgcolor: f.surface2, boxShadow: "none", border: `1px solid ${f.line}` }}>
        <Stack spacing={0.75}>
          <Typography sx={{ fontWeight: 800, fontSize: 17 }}>{form.title}</Typography>
          <Typography variant="body2" sx={{ color: f.muted }}>
            {[
              form.department,
              form.location,
              formatExperienceRange(form.experienceMinYears ? Number(form.experienceMinYears) : null, form.experienceMaxYears ? Number(form.experienceMaxYears) : null),
            ]
              .filter(Boolean)
              .join(" · ") || t("jobs.rev.no_details")}
          </Typography>
          <Typography variant="body2" sx={{ color: f.muted }}>
            {[t(JOB_TYPES.find((j) => j.value === form.jobType)?.key ?? form.jobType), t("jobs.rev.positions", { count: Number(form.positionsCount) || 1 }),
              form.salaryMin && form.salaryMax ? t("jobs.rev.salary", { min: form.salaryMin, max: form.salaryMax }) : ""].filter(Boolean).join(" · ")}
          </Typography>
          {(form.educationDegreeLevel || form.educationField) && (
            <Typography variant="body2" sx={{ color: f.muted }}>
              {t("jobs.rev.education", { value: [form.educationDegreeLevel, form.educationField].filter(Boolean).join(" · ") })}
            </Typography>
          )}
          {(reviewSkills.mustHave.length > 0 || reviewSkills.goodToHave.length > 0) && (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap mt={0.5}>
              {reviewSkills.mustHave.map((skill) => (
                <Chip key={`must-${skill}`} label={skill} size="small" color="primary" />
              ))}
              {reviewSkills.goodToHave.map((skill) => (
                <Chip key={`good-${skill}`} label={skill} size="small" variant="outlined" />
              ))}
            </Stack>
          )}
          {form.preferredCertifications.length > 0 && (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap mt={0.5} alignItems="center">
              <Typography variant="caption" sx={{ color: f.muted }}>{t("jobs.rev.certs")}:</Typography>
              {form.preferredCertifications.map((cert) => (
                <Chip key={cert} label={cert} size="small" variant="outlined" />
              ))}
            </Stack>
          )}
          {form.keyResponsibilities && <Typography variant="body2" sx={{ color: f.muted }}>{t("jobs.rev.responsibilities")}: {form.keyResponsibilities}</Typography>}
          {form.benefits && <Typography variant="body2" sx={{ color: f.muted }}>{t("jobs.rev.benefits")}: {form.benefits}</Typography>}
          {form.additionalNotes && <Typography variant="body2" sx={{ color: f.muted }}>{t("jobs.rev.notes")}: {form.additionalNotes}</Typography>}
        </Stack>
      </Card>

      {sectionTitle("globe", t("jobs.pub.where"))}
      <FormControlLabel control={<Switch checked={form.careerPortal} onChange={(e) => set("careerPortal", e.target.checked)} />} label={t("jobs.pub.careers")} />
      {platformNote(t("jobs.pub.careers_note"))}
      {form.careerPortal && (
        <Box sx={{ ml: 6 }}>
          {job?.status === "published" ? (
            <Typography variant="body2">
              {t("jobs.pub.live")}{" "}
              <MuiLink href={`${window.location.origin}/careers/${job.id}`} target="_blank" rel="noopener noreferrer">
                {`${window.location.origin}/careers/${job.id}`}
              </MuiLink>
            </Typography>
          ) : (
            <Typography variant="caption" sx={{ color: f.muted }}>{t("jobs.pub.will_live")}</Typography>
          )}
        </Box>
      )}
      <FormControlLabel control={<Switch checked={form.linkedin} onChange={(e) => set("linkedin", e.target.checked)} />} label="LinkedIn" />
      {platformNote(
        linkedinConnected && !linkedinExpired ? t("jobs.pub.linkedin_real") : linkedinExpired ? t("jobs.pub.linkedin_expired") : t("jobs.pub.linkedin_none"),
      )}
      {form.linkedin && !(linkedinConnected && !linkedinExpired) && (
        <TextField label={t("jobs.pub.url")} value={form.postingUrlLinkedin} onChange={(e) => set("postingUrlLinkedin", e.target.value)} size="small" fullWidth sx={{ ml: 6, maxWidth: 420 }} />
      )}
      <FormControlLabel control={<Switch checked={form.naukri} onChange={(e) => set("naukri", e.target.checked)} />} label="Naukri.com" />
      {platformNote(t("jobs.pub.naukri_note"))}
      {form.naukri && (
        <TextField label={t("jobs.pub.url")} value={form.postingUrlNaukri} onChange={(e) => set("postingUrlNaukri", e.target.value)} size="small" fullWidth sx={{ ml: 6, maxWidth: 420 }} />
      )}

      <Divider />

      {sectionTitle("gear", t("jobs.pub.more"))}
      <FormControlLabel control={<Switch checked={form.emailNotifications} onChange={(e) => set("emailNotifications", e.target.checked)} />} label={t("jobs.pub.email")} />
      {platformNote(googleConnected ? t("jobs.pub.email_on") : t("jobs.pub.email_off"))}
      <WithTip tip={t("jobs.autoclose.tip")}>
        <TextField label={t("jobs.pub.deadline")} type="date" value={form.applicationDeadline} onChange={(e) => set("applicationDeadline", e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }} helperText={t("jobs.pub.deadline_help")} sx={{ maxWidth: 320 }} fullWidth />
      </WithTip>
    </Stack>
  );

  const renderSuccess = () => {
    if (!published) return null;
    const platforms = published.published_platforms as Record<string, boolean>;
    const careersUrl = `${window.location.origin}/careers/${published.id}`;
    return (
      <Stack spacing={2} alignItems="center" textAlign="center">
        <FriendlyAnimation name="success" size={110} label={t("jobs.done.title")} />
        <Typography variant="h5" component="p" role="status">{t("jobs.done.title")}</Typography>
        <Stack spacing={1} sx={{ width: "100%", textAlign: "left" }}>
          {platforms.career_portal && (
            <Typography variant="body2">
              <strong>{t("jobs.done.careers")}</strong> —{" "}
              <MuiLink href={careersUrl} target="_blank" rel="noopener noreferrer">{careersUrl}</MuiLink>
            </Typography>
          )}
          {platforms.naukri && (
            <Typography variant="body2">
              {t("jobs.done.naukri")}
              {published.posting_url_naukri && (
                <>
                  {" — "}
                  <MuiLink href={published.posting_url_naukri} target="_blank" rel="noopener noreferrer">{t("jobs.done.view")}</MuiLink>
                </>
              )}
            </Typography>
          )}
          {platforms.linkedin && (
            <Typography variant="body2">
              {published.linkedin_post_urn ? (
                <>
                  {t("jobs.done.linkedin_post")}{" — "}
                  <MuiLink href={`https://www.linkedin.com/feed/update/${published.linkedin_post_urn}/`} target="_blank" rel="noopener noreferrer">{t("jobs.done.view")}</MuiLink>
                </>
              ) : (
                <>
                  {t("jobs.done.linkedin_manual")}
                  {published.posting_url_linkedin && (
                    <>
                      {" — "}
                      <MuiLink href={published.posting_url_linkedin} target="_blank" rel="noopener noreferrer">{t("jobs.done.view")}</MuiLink>
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
  const steps = STEPS.map((s) => ({ ...s, title: t(`jobs.wiz.step.${s.key}`) }));
  const saveText = !draftsOn
    ? ""
    : savedAt
      ? t("jobs.wiz.saved", { time: new Date(savedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) })
      : t("jobs.wiz.saves");

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth={(activeStep === 4 || activeStep === 5) && !published ? "lg" : "md"} aria-labelledby="job-wizard-title">
      <DialogTitle id="job-wizard-title" sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <Emoji name="briefcase" size={24} />
        {initialJob ? t("jobs.wiz.edit") : t("jobs.wiz.create")}
      </DialogTitle>
      <DialogContent>
        {draftOffer && (
          <Card role="status" sx={{ p: 2, mb: 2, bgcolor: f.sunSoft, boxShadow: "none" }}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
              <Emoji name="memo" size={22} />
              <Typography sx={{ flex: 1, fontWeight: 600 }}>
                {t("jobs.wiz.draft_found", { time: draftOffer.at ? new Date(draftOffer.at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "" })}
              </Typography>
              <Button variant="contained" size="small" onClick={restoreDraft}>{t("jobs.wiz.draft_continue")}</Button>
              <Button size="small" onClick={startFresh}>{t("jobs.wiz.draft_fresh")}</Button>
            </Stack>
          </Card>
        )}

        {!published && <WizardProgress steps={steps} active={activeStep} saveText={saveText} />}

        {!published && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="h5" component="h2">{steps[activeStep].title}</Typography>
            <Typography sx={{ color: f.muted, mt: 0.5 }}>{t(`jobs.wiz.hint.${STEPS[activeStep].key}`)}</Typography>
          </Box>
        )}

        {apiError && (
          <Box sx={{ mb: 2 }}>
            <FriendlyError compact error={apiError.error} what={apiError.what} />
          </Box>
        )}

        <Box>{renderStep()}</Box>

        {stepError && (
          <Typography role="alert" sx={{ mt: 2, color: f.coral, fontWeight: 600 }}>
            {stepError}
          </Typography>
        )}
      </DialogContent>
      <DialogActions>
        {published ? (
          <Button variant="contained" onClick={handleClose}>
            {t("action.done")}
          </Button>
        ) : (
          <>
            <Button onClick={handleClose}>{t("action.cancel")}</Button>
            <Box sx={{ flex: 1 }} />
            <Button variant="outlined" onClick={handleBack} disabled={activeStep === 0 || saving}>
              {t("action.back")}
            </Button>
            {isLastStep ? (
              <Button variant="contained" onClick={handlePublish} disabled={saving}>
                {saving ? t("jobs.wiz.publishing") : t("jobs.wiz.publish")}
              </Button>
            ) : (
              <Button variant="contained" onClick={handleNext} disabled={saving}>
                {saving ? t("jobs.wiz.saving") : t("action.next")}
              </Button>
            )}
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
