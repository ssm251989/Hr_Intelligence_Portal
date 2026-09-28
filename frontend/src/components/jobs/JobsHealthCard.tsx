import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Collapse from "@mui/material/Collapse";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { automationApi, type JobHealthRow } from "../../api/automationApi";
import { useT, type TFunction } from "../../i18n";
import { Emoji, InfoTip } from "../../ui-kit";

// Part 17.13: "Jobs needing attention" -- live jobs with no new applicants for a week or
// candidates waiting past a stage's time limit, each with a few plain suggestions.
// Hidden when every job is fine (or the check can't be loaded -- it's a nudge, not a page).

// The server writes its tips in English; the known ones get the user's language.
const TIP_KEYS: Record<string, string> = {
  "Share the job again (careers site, job boards, referrals)": "autom.health.tip.share",
  "Widen the location or allow relocation": "autom.health.tip.location",
  "Relax the must-have skills or the experience range": "autom.health.tip.relax",
  "Open the shortlist and decide on the waiting candidates": "autom.health.tip.decide",
  "Most candidates stay below the shortlist threshold - check the job's scoring rules": "autom.health.tip.threshold",
};

function issueText(t: TFunction, issue: { kind: string; text: string }): string {
  if (issue.kind === "no_applicants") return t("autom.health.issue.no_applicants");
  if (issue.kind === "slow_stage") {
    const n = Number(/\d+/.exec(issue.text)?.[0]);
    if (Number.isFinite(n)) return t("autom.health.issue.slow_stage", { count: n });
  }
  return issue.text;
}

const SHOW_FIRST = 3;

export default function JobsHealthCard({ refreshSignal = 0, onOpenJob }: { refreshSignal?: number; onOpenJob?: (jobId: string) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [rows, setRows] = useState<JobHealthRow[]>([]);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let live = true;
    automationApi
      .jobsHealth()
      .then((r) => live && setRows(r.filter((row) => !row.healthy)))
      .catch(() => live && setRows([]));
    return () => {
      live = false;
    };
  }, [refreshSignal]);

  if (rows.length === 0) return null;
  const first = rows.slice(0, SHOW_FIRST);
  const rest = rows.slice(SHOW_FIRST);

  const renderRow = (row: JobHealthRow) => (
    <Box key={row.job_id} component="li" sx={{ p: 1.5, borderRadius: "10px", bgcolor: f.surface, border: `1px solid ${f.line}` }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ sm: "center" }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontWeight: 700 }}>{row.title}</Typography>
          <Typography variant="caption" sx={{ color: f.muted }}>
            {t("autom.health.counts", { week: row.applicants_7d, total: row.applicants_total, days: row.age_days })}
          </Typography>
        </Box>
        {onOpenJob && <Button size="small" onClick={() => onOpenJob(row.job_id)}>{t("autom.health.open")}</Button>}
      </Stack>
      <Stack spacing={0.25} sx={{ mt: 0.75 }}>
        {row.issues.map((issue) => (
          <Typography key={issue.kind} variant="body2" sx={{ fontWeight: 600, display: "flex", gap: 0.75, alignItems: "center" }}>
            <Emoji name="warning" size={16} />
            {issueText(t, issue)}
          </Typography>
        ))}
      </Stack>
      {row.suggestions.length > 0 && (
        <>
          <Typography variant="caption" sx={{ color: f.muted, display: "block", mt: 0.75 }}>{t("autom.health.try")}</Typography>
          <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
            {row.suggestions.map((tip) => (
              <Typography key={tip} component="li" variant="body2">{TIP_KEYS[tip] ? t(TIP_KEYS[tip]) : tip}</Typography>
            ))}
          </Box>
        </>
      )}
    </Box>
  );

  return (
    <Card role="region" aria-label={t("autom.health.title")} sx={{ p: 2, mb: 2, bgcolor: f.sunSoft, boxShadow: "none" }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <Emoji name="bell" size={22} />
        <Typography sx={{ fontWeight: 800, flex: 1 }}>
          {t("autom.health.title_count", { count: rows.length })}
          <InfoTip text={t("autom.health.info")} />
        </Typography>
      </Stack>
      <Stack component="ul" spacing={1} sx={{ listStyle: "none", m: 0, p: 0 }}>
        {first.map(renderRow)}
      </Stack>
      {rest.length > 0 && (
        <>
          <Collapse in={showAll}>
            <Stack component="ul" spacing={1} sx={{ listStyle: "none", m: 0, p: 0, mt: 1 }}>
              {rest.map(renderRow)}
            </Stack>
          </Collapse>
          <Button size="small" sx={{ mt: 1 }} onClick={() => setShowAll((v) => !v)}>
            {showAll ? t("autom.health.show_less") : t("autom.health.show_more", { count: rest.length })}
          </Button>
        </>
      )}
    </Card>
  );
}
