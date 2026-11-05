import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage } from "../../api/client";
import { REMOVAL_REASONS, removalApi, type DeleteSummary, type RemovalReason, type RemovalRun } from "../../api/removalApi";
import { useT } from "../../i18n";

// Part 17.15: one dialog for every "Remove" -- profile, list row, board card, bulk selection,
// and "Delete permanently" from the Recycle bin.
//   mode "remove": reason (+ note) -> Recycle bin. Reason "privacy request" -> deletes at once.
//   mode "delete": permanent. Both permanent paths show the counts and need DELETE typed.
// One candidate is done directly; more than one runs in the background with progress.
export default function RemoveCandidateDialog({
  open, candidateIds, name, mode = "remove", recycleDays = 30, onClose, onDone,
}: {
  open: boolean;
  candidateIds: string[];
  name?: string | null;
  mode?: "remove" | "delete";
  recycleDays?: number;
  onClose: () => void;
  onDone: (result: { deleted: boolean; count: number }) => void;
}) {
  const t = useT();
  const single = candidateIds.length === 1;
  const [reason, setReason] = useState<RemovalReason | "">("");
  const [note, setNote] = useState("");
  const [typed, setTyped] = useState("");
  const [summary, setSummary] = useState<DeleteSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<RemovalRun | null>(null);
  const timer = useRef<number | null>(null);

  const permanent = mode === "delete" || reason === "privacy_request";
  const displayName = name || t("bin.unnamed");

  useEffect(() => {
    if (!open) return;
    setReason(mode === "delete" ? "other" : "");
    setNote("");
    setTyped("");
    setError(null);
    setRun(null);
    setSummary(null);
    setSummaryError(null);
    if (single) {
      removalApi.summary(candidateIds[0]).then(setSummary).catch((err) => setSummaryError(extractErrorMessage(err, t("removal.err"))));
    }
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, candidateIds.join(","), mode]);

  const blocked = summary?.blocked ?? null;
  const tooMany = candidateIds.length > 500;
  const canConfirm = !busy && !run && !blocked && !tooMany && reason !== "" && (!permanent || typed === "DELETE");

  const poll = (runId: string) => {
    timer.current = window.setInterval(async () => {
      try {
        const r = await removalApi.run(runId);
        setRun(r);
        if (r.status !== "running" && timer.current) {
          window.clearInterval(timer.current);
          timer.current = null;
        }
      } catch {
        /* keep polling; the next tick retries */
      }
    }, 1000);
  };

  const confirm = async () => {
    if (!reason) return;
    setBusy(true);
    setError(null);
    try {
      if (single) {
        const id = candidateIds[0];
        if (mode === "delete") await removalApi.deletePermanently(id, { reason, confirm: typed });
        else await removalApi.remove(id, { reason, note: note || undefined, confirm: permanent ? typed : undefined });
        onDone({ deleted: permanent, count: 1 });
      } else {
        const res = await removalApi.bulk({ candidate_ids: candidateIds, mode: permanent ? "delete" : "remove", reason, note: note || undefined, confirm: permanent ? typed : undefined });
        setRun({ id: res.run_id, mode: res.mode, status: "running", total: res.total, done: 0, skipped: [], finished_at: null });
        poll(res.run_id);
      }
    } catch (err) {
      setError(extractErrorMessage(err, t("removal.err")));
    } finally {
      setBusy(false);
    }
  };

  const finished = run && run.status !== "running";
  const title = mode === "delete"
    ? (single ? t("removal.title_delete", { name: displayName }) : t("removal.title_delete_bulk", { count: candidateIds.length }))
    : (single ? t("removal.title", { name: displayName }) : t("removal.title_bulk", { count: candidateIds.length }));

  return (
    <Dialog open={open} onClose={busy || (run && !finished) ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 0.5 }}>
          {summaryError && <Alert severity="error">{summaryError}</Alert>}
          {blocked && (
            <Alert severity="warning">
              <AlertTitle>{t("removal.blocked_title")}</AlertTitle>
              {blocked}
            </Alert>
          )}
          {tooMany && <Alert severity="warning">{t("removal.too_many")}</Alert>}

          {!blocked && !run && (
            <>
              {mode === "remove" && (
                <TextField select label={t("removal.reason")} value={reason} onChange={(e) => setReason(e.target.value as RemovalReason)} fullWidth required>
                  {REMOVAL_REASONS.map((r) => <MenuItem key={r} value={r}>{t(`removal.reason.${r}`)}</MenuItem>)}
                </TextField>
              )}
              {mode === "remove" && reason !== "" && reason !== "privacy_request" && (
                <TextField label={t("removal.note")} value={note} onChange={(e) => setNote(e.target.value)} fullWidth multiline minRows={2} inputProps={{ maxLength: 1000 }} />
              )}
              {mode === "remove" && reason !== "" && !permanent && (
                <Alert severity="info">{t("removal.soft_explain", { days: recycleDays })}</Alert>
              )}
              {permanent && (
                <>
                  {reason === "privacy_request" && <Alert severity="info">{t("removal.privacy_explain")}</Alert>}
                  <Alert severity="error" icon={false}>
                    <Typography fontWeight={700}>
                      {single
                        ? summary
                          ? t("removal.summary", { candidates: summary.candidates, applications: summary.applications, interviews: summary.interviews, files: summary.files })
                          : t("removal.checking")
                        : t("removal.summary_bulk", { count: candidateIds.length })}
                    </Typography>
                  </Alert>
                  <TextField
                    label={t("removal.type_delete")}
                    helperText={t("removal.type_delete_hint")}
                    value={typed}
                    onChange={(e) => setTyped(e.target.value)}
                    autoComplete="off"
                    fullWidth
                  />
                </>
              )}
            </>
          )}

          {run && (
            <Stack spacing={1}>
              <LinearProgress variant="determinate" value={run.total ? (run.done / run.total) * 100 : 0} />
              <Typography>{finished ? t("removal.bulk_done", { done: run.done - run.skipped.length, total: run.total }) : t("removal.progress", { done: run.done, total: run.total })}</Typography>
              {run.skipped.length > 0 && (
                <Alert severity="warning">
                  {t("removal.progress_skipped", { count: run.skipped.length })}
                  {run.skipped.slice(0, 10).map((s, i) => <Typography key={i} variant="body2">• {s.why}</Typography>)}
                </Alert>
              )}
            </Stack>
          )}
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        {finished ? (
          <Button variant="contained" onClick={() => onDone({ deleted: run!.mode === "delete", count: run!.done - run!.skipped.length })}>{t("removal.close")}</Button>
        ) : (
          <>
            <Button onClick={onClose} disabled={busy || !!run}>{t("removal.cancel")}</Button>
            {!blocked && (
              <Button variant="contained" color={permanent ? "error" : "primary"} onClick={confirm} disabled={!canConfirm}>
                {permanent ? t("removal.confirm_delete") : t("removal.confirm_remove")}
              </Button>
            )}
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
