import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Rating from "@mui/material/Rating";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { interviewsExtraApi, type PanelFeedback } from "../../api/interviewsExtra";
import { useT } from "../../i18n";
import Emoji from "../../ui-kit/Emoji";
import StatusChip from "../../ui-kit/StatusChip";
import UserAvatar from "../../ui-kit/UserAvatar";

// Spec I6: the other interviewers' scorecards for the same candidate. The server withholds
// them until the caller has submitted their own (backend ui_interviews_router.panel_feedback),
// so nobody is nudged by someone else's scores. If that endpoint isn't available this
// section simply doesn't show -- nothing is faked in the browser.
export default function PanelFeedbackSection({ interviewId, refreshKey = 0 }: { interviewId: string; refreshKey?: number }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [panel, setPanel] = useState<PanelFeedback | null>(null);

  useEffect(() => {
    let alive = true;
    interviewsExtraApi
      .panel(interviewId)
      .then((p) => alive && setPanel(p))
      .catch(() => alive && setPanel(null));
    return () => {
      alive = false;
    };
  }, [interviewId, refreshKey]);

  if (!panel) return null;
  if (panel.hidden) {
    return (
      <Stack direction="row" spacing={1.25} alignItems="center" sx={{ p: 1.5, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
        <Emoji name="lock" size={20} />
        <Typography sx={{ fontSize: 14, color: f.muted }}>{t("interviews.panel.hidden")}</Typography>
      </Stack>
    );
  }
  if (panel.others.length === 0) return null;

  return (
    <Box component="section" aria-label={t("interviews.panel.title")}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <Emoji name="people" size={20} />
        <Typography sx={{ fontWeight: 700 }}>{t("interviews.panel.title_count", { count: panel.others.length })}</Typography>
      </Stack>
      <Stack spacing={1}>
        {panel.others.map((o) => {
          const name = o.interviewer_name || t("interviews.unassigned");
          return (
            <Box key={o.interview_id} sx={{ p: 1.5, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
              <Stack direction="row" spacing={1.25} alignItems="center" justifyContent="space-between" flexWrap="wrap" useFlexGap>
                <Stack direction="row" spacing={1.25} alignItems="center">
                  <UserAvatar name={name} size={32} />
                  <Typography sx={{ fontWeight: 600 }}>{name}</Typography>
                </Stack>
                {o.decision === "selected" ? (
                  <StatusChip tone="ok" emoji="thumbs_up" label={t("interviews.decision.selected")} />
                ) : o.decision === "rejected" ? (
                  <StatusChip tone="coral" emoji="cross" label={t("interviews.decision.rejected")} />
                ) : !o.submitted ? (
                  <StatusChip tone="sun" emoji="hourglass" label={t("interviews.panel.not_yet")} />
                ) : null}
              </Stack>
              {o.submitted && (
                <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                  {(
                    [
                      ["technical", o.technical_rating],
                      ["communication", o.communication_rating],
                      ["overall", o.overall_rating],
                    ] as const
                  ).map(([k, v]) =>
                    v == null ? null : (
                      <Stack key={k} direction="row" spacing={0.5} alignItems="center">
                        <Typography sx={{ fontSize: 12, color: f.muted }}>{t(`interviews.score.${k}`)}</Typography>
                        <Rating value={v} readOnly size="small" aria-label={t("interviews.score.rated", { label: t(`interviews.score.${k}`), value: v })} />
                      </Stack>
                    ),
                  )}
                </Stack>
              )}
              {o.comments && <Typography sx={{ mt: 1, fontSize: 14, whiteSpace: "pre-wrap" }}>{o.comments}</Typography>}
            </Box>
          );
        })}
      </Stack>
    </Box>
  );
}
