import { useCallback, useEffect, useState, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import { fetchCandidateStatus, type CandidateStatusView, type StatusStepKey, type StatusStepState } from "../../api/automationApi";
import { useBootstrap } from "../../bootstrap/BootstrapContext";
import { BrandMark, LanguagePicker } from "../../components/careers/PublicAuthLayout";
import { useT } from "../../i18n";
import { Emoji, FriendlyError, Illustration } from "../../ui-kit";

// Part 17.13: the candidate's own "Where is my application?" page, opened from the link in
// their emails (/status/:token). Public -- no login, no auth header. Plain progress only:
// the server never sends scores, notes or reasons, and this page never guesses them.

const STEP_EMOJI: Record<StatusStepKey, string> = {
  applied: "envelope", reviewed: "eyes", shortlisted: "star", interview: "speech", offer: "page", joined: "party",
};

export default function CandidateStatusPage() {
  const f = useTheme().palette.fresh;
  const t = useT();
  const { branding, productName } = useBootstrap();
  const { token = "" } = useParams<{ token: string }>();
  const [view, setView] = useState<CandidateStatusView | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);

  const load = useCallback(() => {
    if (!token) return;
    setLoadError(null);
    fetchCandidateStatus(token).then(setView).catch(setLoadError);
  }, [token]);

  useEffect(load, [load]);

  const shell = (children: ReactNode) => (
    <Box sx={{ minHeight: "100vh", bgcolor: f.ground, display: "flex", flexDirection: "column" }}>
      <Box component="header" sx={{ bgcolor: f.surface, boxShadow: f.shadow }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2} sx={{ maxWidth: 560, mx: "auto", px: 2, py: 1.5 }}>
          <BrandMark size={34} />
          <LanguagePicker />
        </Stack>
      </Box>
      <Box component="main" sx={{ width: "100%", maxWidth: 560, mx: "auto", px: 2, py: { xs: 2.5, md: 4 }, flex: 1 }}>{children}</Box>
      <Box component="footer" sx={{ py: 2.5, px: 2, textAlign: "center", color: f.muted, fontSize: 13 }}>
        {branding?.support_contact ? t("autom.status.footer_help", { contact: branding.support_contact }) : t("autom.status.footer_plain", { company: productName })}
      </Box>
    </Box>
  );

  if (!token || (loadError instanceof ApiError && (loadError.status === 404 || loadError.status === 410))) {
    return shell(
      <Card sx={{ p: { xs: 2.5, md: 4 }, textAlign: "center" }}>
        <Illustration name="access-denied" height={140} />
        <Typography component="h1" sx={{ fontWeight: 800, fontSize: 22, mt: 2 }}>{t("autom.status.invalid")}</Typography>
        <Typography sx={{ color: f.muted, mt: 1, maxWidth: "46ch", mx: "auto" }}>{t("autom.status.invalid_hint")}</Typography>
        {branding?.support_contact && (
          <Button variant="contained" sx={{ mt: 2 }} href={`mailto:${branding.support_contact}`}>{t("autom.status.email_hr")}</Button>
        )}
      </Card>,
    );
  }

  if (loadError) return shell(<FriendlyError error={loadError} what={t("autom.status.load_failed")} onRetry={load} />);

  if (!view) {
    return shell(
      <Box sx={{ display: "grid", placeItems: "center", py: 8 }} role="status" aria-label={t("autom.status.loading")}>
        <CircularProgress />
      </Box>,
    );
  }

  const current = view.steps.find((s) => s.state === "current");
  const colours: Record<StatusStepState, { dot: string; ink: string; line: string }> = {
    done: { dot: f.ok, ink: f.ink, line: f.ok },
    current: { dot: f.brand, ink: f.ink, line: f.line },
    closed: { dot: f.muted, ink: f.ink, line: f.line },
    todo: { dot: f.surface2, ink: f.muted, line: f.line },
  };

  return shell(
    <Stack spacing={2}>
      <Card sx={{ p: { xs: 2.5, md: 3 } }}>
        <Typography component="h1" sx={{ fontWeight: 800, fontSize: { xs: 22, md: 26 } }}>
          {view.first_name ? t("autom.status.hello", { name: view.first_name }) : t("autom.status.hello_plain")}
        </Typography>
        <Typography sx={{ color: f.muted, mt: 0.5 }}>
          {view.job_title ? t("autom.status.for_job", { job: view.job_title, company: productName }) : t("autom.status.for_company", { company: productName })}
        </Typography>
        {view.applied_on && (
          <Typography variant="body2" sx={{ color: f.muted, mt: 0.5 }}>
            {t("autom.status.applied_on", { date: new Date(view.applied_on).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" }) })}
          </Typography>
        )}
      </Card>

      {view.closed ? (
        <Card role="status" sx={{ p: { xs: 2.5, md: 3 }, bgcolor: f.surface2, boxShadow: "none" }}>
          <Stack direction="row" spacing={1.5} alignItems="flex-start">
            <Emoji name="seedling" size={28} />
            <Box>
              <Typography sx={{ fontWeight: 800, fontSize: 18 }}>{t("autom.status.closed_title")}</Typography>
              <Typography sx={{ color: f.muted, mt: 0.5 }}>{t("autom.status.closed_body", { company: productName })}</Typography>
            </Box>
          </Stack>
        </Card>
      ) : current ? (
        <Card role="status" sx={{ p: { xs: 2, md: 2.5 }, bgcolor: f.brandSoft, boxShadow: "none" }}>
          <Typography sx={{ fontWeight: 800 }}>{t(`autom.status.now.${current.key}`)}</Typography>
          <Typography variant="body2" sx={{ color: f.ink, mt: 0.5 }}>{t(`autom.status.next.${current.key}`)}</Typography>
        </Card>
      ) : null}

      <Card sx={{ p: { xs: 2, md: 3 } }}>
        <Typography component="h2" sx={{ fontWeight: 800, mb: 1.5 }}>{t("autom.status.steps_title")}</Typography>
        <Box component="ol" sx={{ listStyle: "none", m: 0, p: 0 }} aria-label={t("autom.status.steps_title")}>
          {view.steps.map((step, i) => {
            const c = colours[step.state];
            const last = i === view.steps.length - 1;
            return (
              <Box component="li" key={step.key} aria-current={step.state === "current" ? "step" : undefined}
                sx={{ display: "grid", gridTemplateColumns: "40px 1fr", columnGap: 1.5, opacity: step.state === "todo" ? 0.75 : 1 }}>
                <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                  <Box sx={{
                    width: 36, height: 36, borderRadius: "50%", display: "grid", placeItems: "center", bgcolor: c.dot,
                    border: step.state === "todo" ? `2px dashed ${f.line}` : "none",
                    boxShadow: step.state === "current" ? `0 0 0 4px ${f.brandSoft}` : "none",
                  }}>
                    {step.state === "done" ? <Emoji name="check" size={18} /> : <Emoji name={STEP_EMOJI[step.key]} size={18} />}
                  </Box>
                  {!last && <Box sx={{ width: 2, flex: 1, minHeight: 24, bgcolor: c.line, my: 0.5 }} />}
                </Box>
                <Box sx={{ pb: last ? 0 : 2, pt: 0.5 }}>
                  <Typography sx={{ fontWeight: step.state === "current" || step.state === "closed" ? 800 : 600, color: c.ink }}>
                    {t(`autom.status.step.${step.key}`)}
                  </Typography>
                  <Typography variant="body2" sx={{ color: f.muted }}>{t(`autom.status.state.${step.state}`)}</Typography>
                </Box>
              </Box>
            );
          })}
        </Box>
      </Card>

      <Typography variant="body2" sx={{ color: f.muted, textAlign: "center" }}>{t("autom.status.bookmark")}</Typography>
    </Stack>,
  );
}
