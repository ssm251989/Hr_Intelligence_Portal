import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Legend, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer, Tooltip as ChartTooltip } from "recharts";

import type { ApplicationEvidence } from "../../api/candidatesExtra";
import { useT } from "../../i18n";
import { InfoTip, ProgressRing, useReducedMotion } from "../../ui-kit";
import { useFresh } from "./stages";

// Part 15.4 profile "Why this score" card: score ring (S1: hover/focus shows the
// breakdown), evidence lines quoted from the resume (S2, when the evidence endpoint is
// available) and a radar of the candidate's score parts against what the job needs to reach
// the interview stage (V7). Every number here comes from the latest ai_screening_scored
// entry or the application row -- nothing is estimated.

export interface ScoreParts {
  skills?: number | null;
  experience?: number | null;
  location?: number | null;
  certificates?: number | null;
  resumeMatch?: number | null;
  composite?: number | null;
  /** The interview-ready score the company set (screening settings at scoring time). */
  jobNeeds?: number | null;
}

export default function ScoreCard({
  score, parts, evidence, missingSkills, candidateName, rationale,
}: {
  score: number | null;
  parts: ScoreParts;
  evidence: ApplicationEvidence | null;
  missingSkills: string[];
  candidateName: string;
  rationale?: string | null;
}) {
  const t = useT();
  const f = useFresh();
  const chart = (useTheme().palette as { chart?: string[] }).chart ?? [f.brand, f.sky, f.sun];
  const reduced = useReducedMotion();

  const rows = [
    { key: "skills", label: t("candidates.score.skills"), value: parts.skills },
    { key: "experience", label: t("candidates.score.experience"), value: parts.experience },
    { key: "location", label: t("candidates.score.location"), value: parts.location },
    { key: "certificates", label: t("candidates.score.certificates"), value: parts.certificates },
    { key: "resume", label: t("candidates.score.resume_match"), value: parts.resumeMatch },
  ];
  const known = rows.filter((r) => r.value != null);
  const radarData = known.map((r) => ({ axis: r.label, candidate: Math.round(r.value as number), job: parts.jobNeeds != null ? Math.round(parts.jobNeeds) : undefined }));

  const breakdown = (
    <Box sx={{ p: 0.5 }}>
      <Typography sx={{ fontWeight: 700, mb: 0.5, fontSize: 13 }}>{t("candidates.score.breakdown")}</Typography>
      {rows.map((r) => (
        <Stack key={r.key} direction="row" justifyContent="space-between" spacing={2} sx={{ fontSize: 12 }}>
          <span>{r.label}</span>
          <b>{r.value != null ? `${Math.round(r.value)}%` : "—"}</b>
        </Stack>
      ))}
      {parts.composite != null && (
        <Stack direction="row" justifyContent="space-between" spacing={2} sx={{ fontSize: 12, mt: 0.5, fontWeight: 700 }}>
          <span>{t("candidates.score.overall")}</span>
          <span>{Math.round(parts.composite)}%</span>
        </Stack>
      )}
    </Box>
  );

  const quotes = evidence?.evidence ?? [];
  const missing = (evidence?.missing_skills?.length ? evidence.missing_skills : missingSkills).slice(0, 4);

  return (
    <Card sx={{ p: 2.25 }} data-testid="candidate-score-card">
      <Stack direction="row" justifyContent="space-between" alignItems="baseline" sx={{ mb: 1.5 }}>
        <Typography variant="h6" component="h2" sx={{ fontWeight: 700 }}>
          {t("candidates.score.title")}
          <InfoTip text={t("candidates.score.info")} />
        </Typography>
        <Typography sx={{ fontSize: 12, color: f.muted }}>{t("candidates.score.from_resume")}</Typography>
      </Stack>
      {score == null ? (
        <Typography sx={{ color: f.muted }}>{t("candidates.score.not_scored")}</Typography>
      ) : (
        <Stack direction={{ xs: "column", md: "row" }} spacing={2.5} alignItems={{ xs: "flex-start", md: "center" }}>
          <Tooltip title={breakdown} arrow describeChild>
            <Box tabIndex={0} sx={{ borderRadius: "50%", "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 3 } }}>
              <ProgressRing value={score} caption={t("candidates.score.ring_caption", { score: Math.round(score) })} />
            </Box>
          </Tooltip>
          <Box component="ul" sx={{ listStyle: "none", m: 0, p: 0, display: "flex", flexDirection: "column", gap: 1, flex: 1, minWidth: 220 }}>
            {quotes.map((q) => (
              <Box component="li" key={q.skill + q.quote} sx={{ fontSize: 13, px: 1.25, py: 1, borderLeft: `3px solid ${f.brand}`, bgcolor: f.surface2, borderRadius: "0 8px 8px 0" }}>
                “{q.quote}”
                <Typography component="span" sx={{ display: "block", fontSize: 11, color: f.muted, mt: 0.25 }}>
                  {t("candidates.score.shows_skill", { skill: q.skill })}
                </Typography>
              </Box>
            ))}
            {missing.length > 0 && (
              <Box component="li" sx={{ fontSize: 13, px: 1.25, py: 1, borderLeft: `3px solid ${f.coral}`, bgcolor: f.surface2, borderRadius: "0 8px 8px 0" }}>
                {t("candidates.score.missing", { skills: missing.join(", ") })}
              </Box>
            )}
            {quotes.length === 0 && missing.length === 0 && rationale && (
              <Box component="li" sx={{ fontSize: 13, px: 1.25, py: 1, borderLeft: `3px solid ${f.brand}`, bgcolor: f.surface2, borderRadius: "0 8px 8px 0", whiteSpace: "pre-wrap" }}>
                {rationale}
              </Box>
            )}
            {quotes.length === 0 && missing.length === 0 && !rationale && (
              <Box component="li" sx={{ fontSize: 13, color: f.muted }}>{t("candidates.score.no_evidence")}</Box>
            )}
          </Box>
          {radarData.length >= 3 && (
            <Box sx={{ width: 260, height: 220, flexShrink: 0 }} role="img" aria-label={t("candidates.score.radar_label", { name: candidateName })}>
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={radarData} outerRadius={70}>
                  <PolarGrid stroke={f.line} />
                  <PolarAngleAxis dataKey="axis" tick={{ fill: f.ink, fontSize: 10, fontWeight: 600 }} />
                  <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                  {parts.jobNeeds != null && (
                    <Radar name={t("candidates.score.job_needs")} dataKey="job" stroke={chart[2]} fill={chart[2]} fillOpacity={0.2} strokeWidth={2} isAnimationActive={!reduced} />
                  )}
                  <Radar name={candidateName} dataKey="candidate" stroke={chart[0]} fill={chart[0]} fillOpacity={0.3} strokeWidth={2} isAnimationActive={!reduced} />
                  <ChartTooltip contentStyle={{ background: f.surface, border: `1px solid ${f.line}`, borderRadius: 10, color: f.ink }} formatter={(v) => `${v}%`} />
                  <Legend iconType="square" wrapperStyle={{ fontSize: 12, color: f.muted }} />
                </RadarChart>
              </ResponsiveContainer>
            </Box>
          )}
        </Stack>
      )}
    </Card>
  );
}
