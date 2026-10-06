// Part 21.1: Recycle bin > Jobs -- closed jobs moved to the bin (by the daily clean-up), with Restore (the job and the
// data that moved with it) and Delete permanently. Deleted permanently by the daily job after the bin's time limit.
import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import { extractErrorMessage } from "../../api/client";
import { jobsExtraApi, type BinnedJob } from "../../api/jobsExtra";
import { useT } from "../../i18n";
import ConfirmDialog from "../ConfirmDialog";
import { EmptyState } from "../../ui-kit";

export default function JobsBinTab({ onNotice }: { onNotice: (m: string) => void }) {
  const t = useT();
  const [items, setItems] = useState<BinnedJob[] | null>(null);
  const [cfg, setCfg] = useState<{ enabled: boolean; days: number; keep_in_pool: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<BinnedJob | null>(null);
  const load = useCallback(() => {
    jobsExtraApi.jobsBin().then((r) => { setItems(r.items); setCfg(r.settings); }).catch((e) => setError(extractErrorMessage(e, "")));
  }, []);
  useEffect(load, [load]);
  const run = async (job: BinnedJob, fn: () => Promise<unknown>, msg: string) => {
    setBusy(job.id);
    setError(null);
    try {
      await fn();
      onNotice(msg);
      load();
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(null);
    }
  };
  return (
    <Stack spacing={2} data-testid="jobs-bin">
      {cfg && (
        <Typography color="text.secondary" sx={{ fontSize: 14 }}>
          {cfg.enabled ? t("jobs.bin.rule", { days: cfg.days }) : t("jobs.bin.rule_off")} {t(cfg.keep_in_pool ? "jobs.bin.pool_on" : "jobs.bin.pool_off")}
        </Typography>
      )}
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      {items === null ? <Card sx={{ p: 2 }}><Skeleton height={40} /><Skeleton height={40} /></Card> : items.length === 0 ? (
        <Card><EmptyState illustration="empty" title={t("jobs.bin.empty")} /></Card>
      ) : (
        <Card>
          <TableContainer>
            <Table size="small" aria-label={t("jobs.bin.tab")}>
              <TableHead>
                <TableRow>
                  <TableCell>{t("jobs.bin.col.job")}</TableCell>
                  <TableCell>{t("jobs.bin.col.closed")}</TableCell>
                  <TableCell>{t("jobs.bin.col.moved")}</TableCell>
                  <TableCell>{t("jobs.bin.col.applications")}</TableCell>
                  <TableCell>{t("bin.col.deleted_on")}</TableCell>
                  <TableCell align="right" />
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((j) => (
                  <TableRow key={j.id} hover>
                    <TableCell>
                      <Typography variant="body2" fontWeight={700}>{j.title}</Typography>
                      {j.department && <Typography variant="caption" color="text.secondary">{j.department}</Typography>}
                    </TableCell>
                    <TableCell>{new Date(j.closed_on).toLocaleDateString()}</TableCell>
                    <TableCell>
                      {new Date(j.moved_on).toLocaleDateString()}
                      {j.by && <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>{j.by}</Typography>}
                    </TableCell>
                    <TableCell>{j.applications}</TableCell>
                    <TableCell>{new Date(j.deleted_permanently_on).toLocaleDateString()}</TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={1} justifyContent="flex-end">
                        <Button size="small" variant="outlined" disabled={busy === j.id}
                          onClick={() => run(j, () => jobsExtraApi.restoreJob(j.id), t("jobs.bin.restored", { title: j.title }))}>{t("bin.restore")}</Button>
                        <Button size="small" color="error" disabled={busy === j.id} onClick={() => setDeleting(j)}>{t("bin.delete")}</Button>
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}
      <ConfirmDialog open={deleting !== null} title={t("jobs.bin.delete_title", { title: deleting?.title ?? "" })} message={t("jobs.bin.delete_text")}
        confirmLabel={t("bin.delete")} cancelLabel={t("action.cancel")} onCancel={() => setDeleting(null)}
        onConfirm={() => { const j = deleting!; setDeleting(null); void run(j, () => jobsExtraApi.deleteJob(j.id), t("jobs.bin.deleted", { title: j.title })); }} />
    </Stack>
  );
}
