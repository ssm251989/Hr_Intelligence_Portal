import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Skeleton from "@mui/material/Skeleton";
import Snackbar from "@mui/material/Snackbar";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import { extractErrorMessage } from "../../api/client";
import { removalApi, type RecycleBinItem } from "../../api/removalApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import RemoveCandidateDialog from "../../components/candidates/RemoveCandidateDialog";
import JobsBinTab from "../../components/candidates/JobsBinTab";
import { useT } from "../../i18n";
import { EmptyState, FriendlyError, PageHeader } from "../../ui-kit";

// Part 17.15: Candidates > Recycle bin -- removed candidates, restorable for N days
// (recruitment.candidates.recycle_days), then deleted permanently by the daily job.
export default function RecycleBinPage() {
  const t = useT();
  const { can } = useMeBootstrap();
  const allowed = can("recruitment.candidate.delete");
  const [items, setItems] = useState<RecycleBinItem[] | null>(null);
  const [days, setDays] = useState(30);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<RecycleBinItem | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"candidates" | "jobs">("candidates");  // Part 21.1

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const res = await removalApi.recycleBin();
      setItems(res.items);
      setDays(res.recycle_days);
    } catch (err) {
      setLoadError(err);
    }
  }, []);

  useEffect(() => {
    if (allowed) void load();
  }, [allowed, load]);

  const restore = async (item: RecycleBinItem) => {
    setBusyId(item.candidate_id);
    setError(null);
    try {
      await removalApi.restore(item.candidate_id);
      setNotice(t("bin.restored", { name: item.name || t("bin.unnamed") }));
      await load();
    } catch (err) {
      setError(extractErrorMessage(err, t("removal.err")));
    } finally {
      setBusyId(null);
    }
  };

  const header = <PageHeader emoji="file_folder" title={t("bin.title")} purpose={t("bin.subtitle", { days })} />;
  if (!allowed) {
    return (<>{header}<Alert severity="info">{t("bin.no_permission")}</Alert></>);
  }

  return (
    <>
      {header}
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }} aria-label={t("bin.title")}>
        <Tab value="candidates" label={t("jobs.bin.tab_candidates")} />
        <Tab value="jobs" label={t("jobs.bin.tab")} />
      </Tabs>
      {tab === "jobs" ? <JobsBinTab onNotice={setNotice} /> : loadError ? (
        <FriendlyError error={loadError} what={t("bin.err")} onRetry={load} />
      ) : items === null ? (
        <Card sx={{ p: 2 }}><Stack spacing={1}>{[0, 1, 2].map((i) => <Skeleton key={i} height={40} />)}</Stack></Card>
      ) : items.length === 0 ? (
        <Card><EmptyState illustration="empty" title={t("bin.empty")} hint={t("bin.empty_hint")} /></Card>
      ) : (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t("bin.col.name")}</TableCell>
                  <TableCell>{t("bin.col.jobs")}</TableCell>
                  <TableCell>{t("bin.col.reason")}</TableCell>
                  <TableCell>{t("bin.col.removed")}</TableCell>
                  <TableCell>{t("bin.col.deleted_on")}</TableCell>
                  <TableCell align="right" />
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.candidate_id} hover>
                    <TableCell>
                      <Typography variant="body2" fontWeight={700}>{item.name || t("bin.unnamed")}</Typography>
                      {item.email && <Typography variant="caption" color="text.secondary">{item.email}</Typography>}
                    </TableCell>
                    <TableCell>{Array.from(new Set(item.jobs)).join(", ") || "—"}</TableCell>
                    <TableCell>
                      {item.reason ? t(`removal.reason.${item.reason}`) : "—"}
                      {item.note && <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>{item.note}</Typography>}
                    </TableCell>
                    <TableCell>
                      {new Date(item.removed_at).toLocaleDateString()}
                      {item.removed_by && <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>{t("bin.removed_by", { who: item.removed_by })}</Typography>}
                    </TableCell>
                    <TableCell>{new Date(item.deleted_permanently_on).toLocaleDateString()}</TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={1} justifyContent="flex-end">
                        <Button size="small" variant="outlined" onClick={() => restore(item)} disabled={busyId === item.candidate_id}>{t("bin.restore")}</Button>
                        <Button size="small" color="error" onClick={() => setDeleting(item)} disabled={busyId === item.candidate_id}>{t("bin.delete")}</Button>
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}
      <RemoveCandidateDialog
        open={deleting !== null}
        candidateIds={deleting ? [deleting.candidate_id] : []}
        name={deleting?.name}
        mode="delete"
        recycleDays={days}
        onClose={() => setDeleting(null)}
        onDone={() => { setDeleting(null); setNotice(t("removal.done_deleted")); void load(); }}
      />
      <Snackbar open={notice !== null} autoHideDuration={5000} onClose={() => setNotice(null)} message={notice ?? ""} />
    </>
  );
}
