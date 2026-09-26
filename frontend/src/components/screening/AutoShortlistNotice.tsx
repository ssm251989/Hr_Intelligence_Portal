import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import { screeningExtraApi, type AutoShortlistInfo } from "../../api/screeningExtra";
import { useI18n, useT } from "../../i18n";
import { StatusChip } from "../../ui-kit";
import { ScoreBreakdown } from "./ScoreParts";

function formatUntil(iso: string, locale: string): string {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  const loc = locale === "en" ? "en-IN" : `${locale}-IN`;
  const time = d.toLocaleTimeString(loc, { hour: "numeric", minute: "2-digit" });
  return sameDay ? time : `${d.toLocaleDateString(loc, { weekday: "short", day: "numeric", month: "short" })} ${time}`;
}

// K F1: an automatic shortlist always shows its undo window ("Undo until 3:40 pm"), that the
// recruiter was told, and the audited score breakdown it was based on.
export default function AutoShortlistNotice({
  info, applicationId, canDecide, onUndone, onError, compact,
}: {
  info: AutoShortlistInfo;
  applicationId: string;
  canDecide: boolean;
  onUndone: () => void;
  onError: (err: unknown) => void;
  compact?: boolean;
}) {
  const t = useT();
  const { locale } = useI18n();
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const open = info.can_undo && new Date(info.undo_until).getTime() > now;
  const until = formatUntil(info.undo_until, locale);

  const undo = async () => {
    setBusy(true);
    try {
      await screeningExtraApi.undoAutoShortlist(applicationId);
      onUndone();
    } catch (err) {
      onError(err);
    } finally {
      setBusy(false);
    }
  };

  const breakdownTip = (
    <Box sx={{ p: 0.5 }}>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>{t("shortlisting.auto.audited")}</Typography>
      <ScoreBreakdown breakdown={info.breakdown} dense />
    </Box>
  );

  return (
    <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
      <Tooltip title={breakdownTip} arrow>
        <Box component="span" tabIndex={0} aria-label={t("shortlisting.auto.chip_aria")} sx={{ display: "inline-flex" }}>
          <StatusChip tone="brand" emoji="robot" label={t("shortlisting.auto.chip")} />
        </Box>
      </Tooltip>
      {info.undone ? (
        <StatusChip tone="muted" emoji="pause" label={t("shortlisting.auto.undone")} />
      ) : open ? (
        <StatusChip tone="sun" emoji="alarm_clock" label={t("shortlisting.auto.undo_until", { time: until })} />
      ) : (
        <StatusChip tone="muted" emoji="lock" label={t("shortlisting.auto.window_closed")} />
      )}
      {!compact && info.recruiter_notified && (
        <StatusChip tone="sky" emoji="bell" label={info.notified_to ? t("shortlisting.auto.notified_to", { name: info.notified_to }) : t("shortlisting.auto.notified")} />
      )}
      {open && canDecide && !info.undone && (
        <Button size="small" variant="outlined" color="warning" onClick={undo} disabled={busy} aria-label={t("shortlisting.auto.undo_aria", { time: until })}>
          {busy ? t("screening.saving") : t("shortlisting.auto.undo")}
        </Button>
      )}
    </Stack>
  );
}
