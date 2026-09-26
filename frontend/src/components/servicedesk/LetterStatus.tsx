// X5: relieving letter status in words + sandboxed preview (no scripts, no same-origin).
import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";

import { serviceDeskExtra, type LetterHtml, type SeparationRow } from "../../api/serviceDeskExtra";
import { useT } from "../../i18n";
import { FriendlyError, InfoTip, StatusChip } from "../../ui-kit";
import { useDateFmt } from "./shared";

export function letterState(s: SeparationRow): "issued" | "ready" | "blocked" | "no_lwd" {
  if (s.letters.relieving) return "issued";
  if (!s.approved_lwd) return "no_lwd";
  return s.blocking_pending > 0 ? "blocked" : "ready";
}

export function LetterChip({ s, forEmployee, withTip }: { s: SeparationRow; forEmployee?: boolean; withTip?: boolean }) {
  const t = useT();
  const fmt = useDateFmt();
  const state = letterState(s);
  const chip =
    state === "issued" ? <StatusChip tone="ok" emoji="page" label={t("exits.letter.issued", { date: fmt.date(s.letters.relieving?.generated_at) })} />
    : state === "ready" ? <StatusChip tone="brand" emoji="pause" label={t(forEmployee ? "exits.letter.ready_me" : "exits.letter.ready")} />
    : state === "blocked" ? <StatusChip tone="sun" emoji="hourglass" label={t("exits.letter.blocked", { count: s.blocking_pending })} />
    : <StatusChip tone="muted" emoji="calendar" label={t("exits.letter.no_lwd")} />;
  return <Box component="span" sx={{ display: "inline-flex", alignItems: "center" }}>{chip}{withTip && <InfoTip text={t("exits.letter.hold_tip")} />}</Box>;
}

export function LetterPreviewButton({ separationId }: { separationId: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<{ relieving: LetterHtml | null; experience: LetterHtml | null } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [which, setWhich] = useState<"relieving" | "experience">("relieving");
  const [frame, setFrame] = useState<HTMLIFrameElement | null>(null);

  const openIt = () => {
    setOpen(true);
    setError(null);
    setData(null);
    serviceDeskExtra.letters(separationId).then(setData).catch(setError);
  };
  const letter = data?.[which] ?? null;
  const doc = letter ? `<!doctype html><html><head><meta charset="utf-8"><style>body{font-family:system-ui,sans-serif;line-height:1.6;max-width:72ch;margin:24px auto;padding:0 16px;color:#15211D;background:#fff}</style></head><body>${letter.html}</body></html>` : "";

  return (
    <>
      <Button size="small" variant="outlined" onClick={openIt}>{t("exits.letter.view")}</Button>
      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>{t("exits.letter.title")}</DialogTitle>
        <DialogContent dividers>
          {error ? <FriendlyError error={error} compact /> : !data ? (
            <Box sx={{ display: "grid", placeItems: "center", py: 6 }}><CircularProgress aria-label={t("helpdesk.common.loading")} /></Box>
          ) : (
            <Stack spacing={1}>
              {data.experience && (
                <Tabs value={which} onChange={(_, v) => setWhich(v)}>
                  <Tab value="relieving" label={t("exits.letter.title")} />
                  <Tab value="experience" label={t("exits.letter.experience")} />
                </Tabs>
              )}
              {/* no allow-scripts: nothing inside the letter can run. allow-same-origin + allow-modals only let our Print button call print(). */}
              <Box component="iframe" ref={setFrame} title={t("exits.letter.frame")} sandbox="allow-modals allow-same-origin" srcDoc={doc}
                sx={{ width: "100%", height: "60vh", border: 0, borderRadius: "12px", bgcolor: "#fff" }} />
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          {letter && <Button onClick={() => frame?.contentWindow?.print()}>{t("exits.letter.print")}</Button>}
          <Button variant="contained" onClick={() => setOpen(false)}>{t("action.close")}</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
