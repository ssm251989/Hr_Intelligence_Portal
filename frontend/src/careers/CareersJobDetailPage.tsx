import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink, useParams } from "react-router-dom";

import { careersExtraApi, type CareersJobExtras } from "../api/careersExtra";
import { ApiError, publicApi } from "../api/client";
import type { PublicJobRead } from "../api/types";
import { BenefitsSection, FaqSection, useCareersSite } from "../components/careers/CareersSections";
import JobFacts from "../components/careers/JobFacts";
import { useT } from "../i18n";
import { EmptyState, Emoji, FriendlyError } from "../ui-kit";
import { categorizeSkills } from "../utils/skills";

function SkillChips({ skills, strong }: { skills: string[]; strong?: boolean }) {
  const f = useTheme().palette.fresh;
  return (
    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
      {skills.map((s) => (
        <Box key={s} component="span" sx={{ borderRadius: 999, px: 1.1, py: 0.35, fontSize: 12, fontWeight: 700, bgcolor: strong ? f.brandSoft : f.surface2, color: strong ? f.brand : f.ink, border: strong ? "1px solid transparent" : `1px solid ${f.line}` }}>
          {s}
        </Box>
      ))}
    </Stack>
  );
}

export default function CareersJobDetailPage() {
  const f = useTheme().palette.fresh;
  const t = useT();
  const { id } = useParams<{ id: string }>();
  const site = useCareersSite();
  const [job, setJob] = useState<PublicJobRead | null>(null);
  const [extras, setExtras] = useState<CareersJobExtras | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const load = () => {
    if (!id) return;
    setError(null);
    publicApi
      .getJob(id)
      .then(setJob)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError(err);
        }
      });
    careersExtraApi.jobExtras(id).then(setExtras);
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [id]);

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

  if (error !== null) {
    return <FriendlyError error={error} what={t("careers.job_load_failed")} fix={t("careers.load_failed_fix")} onRetry={load} actionLabel={t("careers.view_open")} actionTo="/careers" />;
  }

  if (!job) {
    return (
      <Stack spacing={2} aria-busy="true">
        <Skeleton variant="rounded" height={140} />
        <Skeleton variant="rounded" height={320} />
      </Stack>
    );
  }

  const { mustHave, goodToHave } = categorizeSkills(job);
  const extraFacts = [
    ...(extras?.job_type ? [{ emoji: "briefcase", text: extras.job_type }] : []),
    ...(extras?.application_deadline ? [{ emoji: "alarm_clock", text: t("careers.deadline", { date: new Date(extras.application_deadline).toLocaleDateString() }) }] : []),
  ];
  const applyButton = (
    <Button component={RouterLink} to={`/careers/${job.id}/apply`} variant="contained" size="large">
      {t("careers.apply_now")}
    </Button>
  );

  return (
    <Stack spacing={4}>
      <Button component={RouterLink} to="/careers" sx={{ alignSelf: "flex-start" }}>← {t("careers.all_jobs")}</Button>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "minmax(0, 1fr) 300px" }, gap: 3, alignItems: "start" }}>
        <Stack spacing={3}>
          <Card sx={{ p: { xs: 2.5, md: 3.5 } }}>
            <Typography variant="h1" component="h1" sx={{ fontSize: { xs: 26, md: 32 }, mb: 1.5 }}>{job.title}</Typography>
            <JobFacts job={job} extra={extraFacts} />
          </Card>

          {job.jd_text && (
            <Card sx={{ p: { xs: 2.5, md: 3.5 } }}>
              <Typography component="h2" sx={{ fontWeight: 700, fontSize: 18, mb: 1.5 }}>{t("careers.about_role")}</Typography>
              <Typography sx={{ whiteSpace: "pre-wrap" }}>{job.jd_text}</Typography>
            </Card>
          )}

          {extras?.benefits && (
            <Card sx={{ p: { xs: 2.5, md: 3.5 } }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
                <Emoji name="sparkles" size={20} />
                <Typography component="h2" sx={{ fontWeight: 700, fontSize: 18 }}>{t("careers.job_benefits")}</Typography>
              </Stack>
              <Typography sx={{ whiteSpace: "pre-wrap", color: f.ink }}>{extras.benefits}</Typography>
            </Card>
          )}
        </Stack>

        <Stack spacing={2} sx={{ position: { md: "sticky" }, top: { md: 16 } }}>
          <Card sx={{ p: 2.5 }}>
            <Typography sx={{ fontWeight: 700, mb: 0.5 }}>{t("careers.apply_box_title")}</Typography>
            <Typography sx={{ color: f.muted, fontSize: 13, mb: 2 }}>{t("careers.apply_box_hint")}</Typography>
            <Box sx={{ "& > a": { width: "100%" } }}>{applyButton}</Box>
          </Card>
          {(mustHave.length > 0 || goodToHave.length > 0) && (
            <Card sx={{ p: 2.5 }}>
              <Typography component="h2" sx={{ fontWeight: 700, mb: 1.5 }}>{t("careers.skills")}</Typography>
              {mustHave.length > 0 && (
                <Box sx={{ mb: goodToHave.length ? 1.5 : 0 }}>
                  <Typography variant="caption" sx={{ color: f.muted, display: "block", mb: 0.75 }}>{t("careers.required")}</Typography>
                  <SkillChips skills={mustHave} strong />
                </Box>
              )}
              {goodToHave.length > 0 && (
                <Box>
                  <Typography variant="caption" sx={{ color: f.muted, display: "block", mb: 0.75 }}>{t("careers.nice_to_have")}</Typography>
                  <SkillChips skills={goodToHave} />
                </Box>
              )}
            </Card>
          )}
          {job.preferred_certifications && job.preferred_certifications.length > 0 && (
            <Card sx={{ p: 2.5 }}>
              <Typography component="h2" sx={{ fontWeight: 700, mb: 1.5 }}>{t("careers.certifications")}</Typography>
              <SkillChips skills={job.preferred_certifications} />
            </Card>
          )}
        </Stack>
      </Box>

      <BenefitsSection site={site} />
      <FaqSection site={site} />
      <Box sx={{ textAlign: "center" }}>{applyButton}</Box>
    </Stack>
  );
}
