import CloseIcon from "@mui/icons-material/Close";
import Dialog from "@mui/material/Dialog";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

import { useT } from "../i18n";
import Emoji from "../ui-kit/Emoji";
import ScorecardForm from "./interviews/ScorecardForm";

// The interview scorecard in a dialog -- the Interview List's "Fill in scorecard" row
// action. Same PATCH /interviews/{id}/feedback logic as before (now in ScorecardForm, which
// the "My interviews" page shows inline too), pre-filled from GET /interviews/{id}.
export default function InterviewFeedbackDialog({
  interviewId,
  applicationId = null,
  candidateLabel,
  onClose,
  onSaved,
}: {
  interviewId: string | null;
  applicationId?: string | null;
  candidateLabel: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down("sm"));

  return (
    <Dialog open={interviewId != null} onClose={onClose} fullWidth maxWidth="sm" fullScreen={fullScreen} aria-labelledby="scorecard-dialog-title">
      <DialogTitle id="scorecard-dialog-title" sx={{ pr: 6 }}>
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Emoji name="memo" size={24} />
          <span>
            {t("interviews.score.title")}
            <Typography component="span" sx={{ display: "block", color: theme.palette.fresh.muted, fontSize: 14, fontWeight: 500 }}>
              {candidateLabel}
            </Typography>
          </span>
        </Stack>
        <IconButton aria-label={t("action.close")} onClick={onClose} sx={{ position: "absolute", right: 12, top: 12 }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        {interviewId && (
          <ScorecardForm interviewId={interviewId} applicationId={applicationId} candidateLabel={candidateLabel} onSaved={onSaved} onCancel={onClose} />
        )}
      </DialogContent>
    </Dialog>
  );
}
