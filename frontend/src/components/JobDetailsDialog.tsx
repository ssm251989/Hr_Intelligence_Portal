import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { PIPELINE_STAGES, type JobPipelineRow } from "../api/jobsExtra";
import type { JobRoleRead } from "../api/types";
import { useT } from "../i18n";
import { Emoji, StatusChip } from "../ui-kit";
import { formatExperienceRange } from "../utils/experience";
import { categorizeSkills } from "../utils/skills";
import AutoCloseNote from "./jobs/AutoCloseNote";
import JdPreview from "./jobs/JdPreview";
import JobSchedulingProblems from "./jobs/JobSchedulingProblems";
import TalentPoolPanel from "./jobs/TalentPoolPanel";
import { STAGE_STYLE } from "./jobs/jobStages";
import JobTypeChip from "./JobTypeChip";
import PostingLinksEditor from "./PostingLinksEditor";

function Fact({ label, children }: { label: string; children: ReactNode }) {
  const f = useTheme().palette.fresh;
  return (
    <>
      <Typography component="dt" sx={{ color: f.muted, fontSize: 13 }}>{label}</Typography>
      <Typography component="dd" sx={{ m: 0, fontWeight: 600, fontSize: 13 }}>{children}</Typography>
    </>
  );
}

export default function JobDetailsDialog({
  job,
  canWrite,
  onClose,
  onUpdated,
  pipeline,
  onCloseJob,
}: {
  job: JobRoleRead | null;
  canWrite: boolean;
  onClose: () => void;
  onUpdated: (job: JobRoleRead) => void;
  pipeline?: JobPipelineRow;
  /** Part 18.8: opens the Close job dialog */
  onCloseJob?: (job: JobRoleRead) => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  return (
    <Dialog open={job !== null} onClose={onClose} fullWidth maxWidth="md" aria-labelledby="job-details-title">
      <DialogTitle id="job-details-title" sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <Emoji name="briefcase" size={22} />
        {t("jobs.det.title")}
      </DialogTitle>
      <DialogContent>
        {job && (
          <Stack spacing={2} mt={0.5}>
            <JobSchedulingProblems jobId={job.id} />
            <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1} flexWrap="wrap" useFlexGap>
              <Box>
                <Typography variant="h5" component="h3">{job.title}</Typography>
                <Typography variant="body2" sx={{ color: f.muted, mt: 0.5 }}>
                  {[job.department, job.location, formatExperienceRange(job.experience_min_years, job.experience_max_years)].filter(Boolean).join(" · ") || t("jobs.rev.no_details")}
                </Typography>
              </Box>
              <Stack direction="row" spacing={0.75} alignItems="center">
                <JobTypeChip jobType={job.job_type} />
                <StatusChip status={job.status} />
              </Stack>
            </Stack>
            <AutoCloseNote row={pipeline} withTip />

            {pipeline && (
              <Box>
                <Typography sx={{ fontWeight: 700, mb: 1 }}>{t("jobs.det.pipeline")}</Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  {PIPELINE_STAGES.map((stage) => (
                    <StatusChip key={stage} tone={pipeline.stages[stage] > 0 ? STAGE_STYLE[stage].tone : "muted"} emoji={STAGE_STYLE[stage].emoji}
                      label={`${t(`jobs.stage.${stage}`)}: ${pipeline.stages[stage].toLocaleString()}`} />
                  ))}
                </Stack>
              </Box>
            )}

            <Box component="dl" sx={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 16px", m: 0, p: 2, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
              <Fact label={t("jobs.det.openings")}>{job.positions_count}</Fact>
              {job.salary_band_min != null && job.salary_band_max != null && (
                <Fact label={t("jobs.det.salary")}>{`${job.salary_band_min} – ${job.salary_band_max}`}</Fact>
              )}
              <Fact label={t("jobs.det.applications")}>{job.application_count}</Fact>
              {job.avg_time_to_hire_days != null && <Fact label={t("jobs.det.avg")}>{t("jobs.days", { count: job.avg_time_to_hire_days })}</Fact>}
              {(job.education_degree_level || job.education_field) && (
                <Fact label={t("jobs.det.education")}>{[job.education_degree_level, job.education_field].filter(Boolean).join(" · ")}</Fact>
              )}
            </Box>

            {(() => {
              const { mustHave, goodToHave } = categorizeSkills(job);
              if (mustHave.length === 0 && goodToHave.length === 0) return null;
              return (
                <Stack spacing={0.75}>
                  {mustHave.length > 0 && (
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
                      <Typography variant="caption" sx={{ color: f.muted }}>{t("jobs.det.must")}:</Typography>
                      {mustHave.map((skill) => <Chip key={`must-${skill}`} label={skill} size="small" color="primary" />)}
                    </Stack>
                  )}
                  {goodToHave.length > 0 && (
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
                      <Typography variant="caption" sx={{ color: f.muted }}>{t("jobs.det.good")}:</Typography>
                      {goodToHave.map((skill) => <Chip key={`good-${skill}`} label={skill} size="small" variant="outlined" />)}
                    </Stack>
                  )}
                </Stack>
              );
            })()}

            {job.preferred_certifications && job.preferred_certifications.length > 0 && (
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
                <Typography variant="caption" sx={{ color: f.muted }}>{t("jobs.det.certs")}:</Typography>
                {job.preferred_certifications.map((cert) => <Chip key={cert} label={cert} size="small" variant="outlined" />)}
              </Stack>
            )}

            {job.key_responsibilities && <Typography variant="body2" sx={{ color: f.muted }}>{t("jobs.rev.responsibilities")}: {job.key_responsibilities}</Typography>}
            {job.benefits && <Typography variant="body2" sx={{ color: f.muted }}>{t("jobs.rev.benefits")}: {job.benefits}</Typography>}
            {job.additional_notes && <Typography variant="body2" sx={{ color: f.muted }}>{t("jobs.rev.notes")}: {job.additional_notes}</Typography>}

            <PostingLinksEditor job={job} canWrite={canWrite} onUpdated={onUpdated} />

            {/* Part 17.13: people from earlier jobs who fit this one */}
            {job.status !== "closed" && <TalentPoolPanel key={job.id} jobId={job.id} />}

            {job.jd_text && (
              <Box sx={{ p: 2.5, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                <Typography sx={{ fontWeight: 700, color: f.muted, fontSize: 13, textTransform: "uppercase", letterSpacing: ".06em", mb: 1 }}>
                  {t("jobs.det.jd")}
                </Typography>
                <JdPreview text={job.jd_text} />
              </Box>
            )}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        {onCloseJob && canWrite && job && (job.status === "published" || job.status === "on_hold") && (
          <Button color="warning" variant="outlined" onClick={() => onCloseJob(job)} sx={{ mr: "auto" }}>{t("closejob.action")}</Button>
        )}
        <Button onClick={onClose}>{t("action.close")}</Button>
      </DialogActions>
    </Dialog>
  );
}
