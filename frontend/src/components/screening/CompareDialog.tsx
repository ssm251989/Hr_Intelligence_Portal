import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import type { CandidateApplicationRow } from "../../api/types";
import { useT } from "../../i18n";
import { ProgressRing, StatusChip } from "../../ui-kit";
import { matchScoreDisplay } from "../../utils/screeningScore";
import { useScreeningDetails } from "./hooks";
import { EvidenceList, ScoreBreakdown, scoreTone } from "./ScoreParts";

export const MAX_COMPARE = 3;

// S5: up to three candidates side by side -- score, what it is made of, skills, experience
// and the resume lines behind it. Read-only; decisions stay on the list.
export default function CompareDialog({
  open, rows, onClose, onOpenCandidate,
}: {
  open: boolean;
  rows: CandidateApplicationRow[];
  onClose: () => void;
  onOpenCandidate: (applicationId: string) => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const shown = rows.slice(0, MAX_COMPARE);
  // Selected rows can come from several pages, so the dialog fetches its own details.
  const details = useScreeningDetails(open ? shown.map((r) => r.application_id) : []);
  const best = Math.max(...shown.map((r) => matchScoreDisplay(r).value ?? -1));

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="lg" aria-labelledby="compare-title">
      <DialogTitle id="compare-title">{t("screening.compare_dialog.title", { count: shown.length })}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: `repeat(${Math.max(1, shown.length)}, minmax(0, 1fr))` } }}>
          {shown.map((row) => {
            const d = details.get(row.application_id);
            const score = matchScoreDisplay(row).value;
            const tone = scoreTone(score);
            const ringTone = tone === "muted" ? "brand" : tone;
            const years = d?.experience_years ?? row.experience_years;
            return (
              <Box key={row.application_id} sx={{ border: `1px solid ${f.line}`, borderRadius: "18px", p: 2, display: "flex", flexDirection: "column", gap: 2, bgcolor: f.surface }}>
                <Stack direction="row" spacing={2} alignItems="center">
                  <ProgressRing
                    value={score ?? 0}
                    size={84}
                    thickness={10}
                    tone={ringTone}
                    label={score != null ? String(Math.round(score)) : "—"}
                    caption={score != null ? t("screening.score.aria", { n: Math.round(score) }) : t("screening.score.none")}
                  />
                  <Box sx={{ minWidth: 0 }}>
                    <Typography sx={{ fontWeight: 800 }} noWrap>{row.candidate_name || t("screening.unnamed")}</Typography>
                    <Typography variant="body2" sx={{ color: f.muted }} noWrap>{row.job_title}</Typography>
                    {score != null && score === best && shown.length > 1 && (
                      <Box mt={0.5}><StatusChip tone="ok" emoji="trophy" label={t("screening.compare_dialog.best")} /></Box>
                    )}
                  </Box>
                </Stack>

                <Section title={t("screening.compare_dialog.breakdown")}>
                  {d ? <ScoreBreakdown breakdown={d.breakdown} /> : <Muted>{t("screening.breakdown.none")}</Muted>}
                </Section>

                <Section title={t("screening.compare_dialog.experience")}>
                  <Typography variant="body2">
                    {years != null ? t("screening.years", { count: years }) : t("screening.compare_dialog.unknown")}
                    {d?.current_title ? ` · ${d.current_title}` : ""}
                  </Typography>
                  {row.location && <Typography variant="body2" sx={{ color: f.muted }}>{row.location}</Typography>}
                </Section>

                <Section title={t("screening.compare_dialog.skills")}>
                  {d && d.matched_skills.length > 0 ? (
                    <Stack direction="row" flexWrap="wrap" gap={0.75}>
                      {d.matched_skills.slice(0, 10).map((s) => <StatusChip key={s} tone="ok" emoji="check" label={s} />)}
                    </Stack>
                  ) : (
                    <Muted>{t("screening.compare_dialog.none")}</Muted>
                  )}
                </Section>

                <Section title={t("screening.compare_dialog.missing")}>
                  {d && d.missing_skills.length > 0 ? (
                    <Stack direction="row" flexWrap="wrap" gap={0.75}>
                      {d.missing_skills.slice(0, 10).map((s) => <StatusChip key={s} tone="coral" emoji="cross" label={s} />)}
                    </Stack>
                  ) : (
                    <Muted>{t("screening.compare_dialog.none_missing")}</Muted>
                  )}
                </Section>

                <Section title={t("screening.compare_dialog.evidence")}>
                  <EvidenceList lines={d?.evidence ?? []} max={4} />
                </Section>

                <Box sx={{ mt: "auto" }}>
                  <Button fullWidth variant="outlined" onClick={() => onOpenCandidate(row.application_id)}>
                    {t("screening.view_profile")}
                  </Button>
                </Box>
              </Box>
            );
          })}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.close")}</Button>
      </DialogActions>
    </Dialog>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const f = useTheme().palette.fresh;
  return (
    <Box>
      <Typography variant="caption" sx={{ color: f.muted, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, display: "block", mb: 0.75 }}>
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function Muted({ children }: { children: React.ReactNode }) {
  return <Typography variant="body2" sx={{ color: "text.secondary" }}>{children}</Typography>;
}
