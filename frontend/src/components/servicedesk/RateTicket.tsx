// T4: one-click rating once a ticket is fixed -- five faces, each with its word.
import { useState } from "react";
import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { serviceDeskExtra } from "../../api/serviceDeskExtra";
import { useT } from "../../i18n";
import { FriendlyError } from "../../ui-kit";

const FACES = ["😞", "🙁", "😐", "🙂", "😍"];

export default function RateTicket({ ticketId, score, onRated, compact }: { ticketId: string; score: number | null; onRated?: (score: number) => void; compact?: boolean }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [saved, setSaved] = useState<number | null>(score);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (saved) {
    return <Typography sx={{ fontSize: 13, color: f.ok, fontWeight: 700 }}>{t("helpdesk.rate.thanks", { score: saved })}</Typography>;
  }

  const rate = async (n: number) => {
    setBusy(true);
    setError(null);
    try {
      await serviceDeskExtra.rate(ticketId, n);
      setSaved(n);
      onRated?.(n);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box>
      <Typography sx={{ fontSize: 13, fontWeight: 700, mb: 0.5 }}>{t("helpdesk.rate.ask")}</Typography>
      <Stack direction="row" spacing={0.5} role="group" aria-label={t("helpdesk.rate.ask")}>
        {FACES.map((face, i) => {
          const n = i + 1;
          const word = t(`helpdesk.rate.${n}`);
          return (
            <ButtonBase key={n} disabled={busy} onClick={() => rate(n)} aria-label={t("helpdesk.rate.label", { score: n, word })} title={word}
              sx={{ flexDirection: "column", borderRadius: "11px", px: compact ? 0.75 : 1.25, py: 0.5, border: `1px solid ${f.line}`, bgcolor: f.surface,
                "&:hover, &:focus-visible": { bgcolor: f.brandSoft, borderColor: f.brand } }}>
              <Box component="span" aria-hidden sx={{ fontSize: compact ? 18 : 22, lineHeight: 1.2 }}>{face}</Box>
              {!compact && <Box component="span" sx={{ fontSize: 11, color: f.muted }}>{word}</Box>}
            </ButtonBase>
          );
        })}
      </Stack>
      {error ? <Box sx={{ mt: 1 }}><FriendlyError error={error} compact /></Box> : null}
    </Box>
  );
}
