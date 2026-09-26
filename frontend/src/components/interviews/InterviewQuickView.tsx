import CloseIcon from "@mui/icons-material/Close";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import type { InterviewListRow } from "../../api/types";
import { useI18n } from "../../i18n";
import Emoji from "../../ui-kit/Emoji";
import UserAvatar from "../../ui-kit/UserAvatar";
import { InterviewStatusChip, SchedulingMethodChip } from "../InterviewChips";
import { localeTag } from "./weekDates";

// What opens when you click an interview block on the week calendar: the key facts and the
// same actions the table's row menu has.
export default function InterviewQuickView({
  row,
  canWrite,
  aiAllowed,
  onClose,
  onViewCandidate,
  onScorecard,
  onQuestions,
}: {
  row: InterviewListRow | null;
  canWrite: boolean;
  aiAllowed: boolean;
  onClose: () => void;
  onViewCandidate: (row: InterviewListRow) => void;
  onScorecard: (row: InterviewListRow) => void;
  onQuestions: (row: InterviewListRow) => void;
}) {
  const f = useTheme().palette.fresh;
  const { t, locale } = useI18n();
  if (!row) return null;
  const name = row.candidate_name || t("interviews.unnamed");
  const fmt = new Intl.DateTimeFormat(localeTag(locale), { dateStyle: "full", timeStyle: "short" });
  const join = row.meeting_link || row.calendar_link;
  const facts: [string, React.ReactNode][] = [
    [t("interviews.col.job"), row.job_title],
    [t("interviews.col.when"), row.scheduled_at ? fmt.format(new Date(row.scheduled_at)) : t("interviews.no_time")],
    [t("interviews.col.interviewer"), row.interviewer_name || t("interviews.unassigned")],
    [t("interviews.col.method"), <SchedulingMethodChip key="m" method={row.scheduling_method} />],
  ];
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs" aria-labelledby="interview-quick-title">
      <DialogTitle id="interview-quick-title" sx={{ pr: 6 }}>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <UserAvatar name={name} size={44} />
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 800, fontSize: 18 }} noWrap>{name}</Typography>
            <InterviewStatusChip status={row.status} />
          </Box>
        </Stack>
        <IconButton aria-label={t("action.close")} onClick={onClose} sx={{ position: "absolute", right: 12, top: 12 }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        <Box component="dl" sx={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 16px", m: 0 }}>
          {facts.map(([k, v]) => (
            <Box key={k} sx={{ display: "contents" }}>
              <Typography component="dt" sx={{ color: f.muted, fontSize: 13 }}>{k}</Typography>
              <Typography component="dd" sx={{ m: 0, fontWeight: 600, fontSize: 14 }}>{v}</Typography>
            </Box>
          ))}
        </Box>
      </DialogContent>
      <DialogActions sx={{ flexWrap: "wrap", gap: 1, px: 3, pb: 2 }}>
        {join && (
          <Button component="a" href={join} target="_blank" rel="noopener noreferrer" startIcon={<Emoji name="link" size={16} />}>
            {t("interviews.join")}
          </Button>
        )}
        <Button onClick={() => onViewCandidate(row)}>{t("interviews.action.view")}</Button>
        {canWrite && aiAllowed && <Button onClick={() => onQuestions(row)}>{t("interviews.action.questions")}</Button>}
        {canWrite && (
          <Button variant="contained" onClick={() => onScorecard(row)}>
            {t("interviews.action.scorecard")}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
