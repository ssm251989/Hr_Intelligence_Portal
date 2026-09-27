import { useEffect, useMemo, useState } from "react";
import CompareArrowsOutlinedIcon from "@mui/icons-material/CompareArrowsOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import RefreshIcon from "@mui/icons-material/Refresh";
import SearchIcon from "@mui/icons-material/Search";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import Link from "@mui/material/Link";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Skeleton from "@mui/material/Skeleton";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { Link as RouterLink, useNavigate, useSearchParams } from "react-router-dom";

import { jobsApi, shortlistingApi } from "../api/client";
import {
  shortlistStatusOf,
  type ApplicationRead,
  type CandidateApplicationRow,
  type JobRoleRead,
  type ShortlistBulkDecisionResult,
  type ShortlistStatus,
} from "../api/types";
import RetryNegotiationMenuItem, { isRetryNegotiationEligible } from "../components/RetryNegotiationMenuItem";
import ShortlistStatusPanel from "../components/ShortlistStatusPanel";
import SourceIcon from "../components/SourceIcon";
import BulkShortlistDialog from "../components/shortlisting/BulkShortlistDialog";
import {
  clearThresholdCache,
  KnockoutChip,
  MatchScoreChip,
  matchScoreOf,
  QUEUE_TABS,
  useJobThresholds,
  waitingBucket,
  type QueueRow,
  type QueueTab,
} from "../components/shortlisting/queueParts";
import AutoShortlistNotice from "../components/screening/AutoShortlistNotice";
import CompareDialog, { MAX_COMPARE } from "../components/screening/CompareDialog";
import { useScreeningDetails } from "../components/screening/hooks";
import { CandidateCell, PaginationFooter } from "../components/screening/listParts";
import RejectReasonDialog from "../components/screening/RejectReasonDialog";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { useT } from "../i18n";
import { EmptyState, FriendlyError, PageHeader, StatusChip, type Tone } from "../ui-kit";
import { downloadCsv } from "../utils/csv";
import { downloadResume } from "../utils/resume";

const SEARCH_DEBOUNCE_MS = 300;
const POOL_PAGE_SIZE = 200;
const POOL_MAX_PAGES = 5; // up to 1000 waiting candidates are sorted into the two waiting tabs
const DEFAULT_PAGE_SIZE = 25; // the details endpoint takes up to 50 ids, so pages stay <= 50
const DECIDED_STATUS: Record<"shortlisted" | "rejected", ShortlistStatus> = { shortlisted: "shortlisted", rejected: "not_shortlisted" };
// Old links (?shortlist_status=...) still land on the matching tab.
const LEGACY_STATUS_TAB: Record<string, QueueTab> = { under_review: "suggested", shortlisted: "shortlisted", not_shortlisted: "rejected" };

const STATUS_CHIP: Record<ShortlistStatus, { tone: Tone; emoji: string; key: string }> = {
  under_review: { tone: "sky", emoji: "hourglass", key: "shortlistQueue.status.waiting" },
  shortlisted: { tone: "ok", emoji: "star", key: "shortlistQueue.status.shortlisted" },
  on_hold: { tone: "muted", emoji: "pause", key: "shortlistQueue.status.on_hold" },
  not_shortlisted: { tone: "coral", emoji: "cross", key: "shortlistQueue.status.rejected" },
};

type BulkResult = { result: ShortlistBulkDecisionResult; target: "shortlisted" | "not_shortlisted"; namesById: Map<string, string> };

function RowMenu({
  row, canDecide, onChangeStatus, onResume, onRetryDone, onRetryError,
}: {
  row: QueueRow;
  canDecide: boolean;
  onChangeStatus: (row: QueueRow) => void;
  onResume: (row: QueueRow) => void;
  onRetryDone: () => void;
  onRetryError: (message: string) => void;
}) {
  const t = useT();
  const navigate = useNavigate();
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const name = row.candidate_name || t("screening.unnamed");
  const close = () => setAnchorEl(null);
  return (
    <>
      <IconButton size="small" onClick={(e) => setAnchorEl(e.currentTarget)} aria-label={t("shortlistQueue.row.more", { name })} aria-haspopup="menu">
        <MoreVertIcon fontSize="small" />
      </IconButton>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={close}>
        <MenuItem onClick={() => { close(); navigate(`/candidates/${row.application_id}`); }}>{t("shortlistQueue.row.open")}</MenuItem>
        {canDecide && <MenuItem onClick={() => { close(); onChangeStatus(row); }}>{t("shortlistQueue.row.change_status")}</MenuItem>}
        {row.resume_path && (
          <MenuItem onClick={() => { close(); onResume(row); }} aria-label={t("shortlistQueue.row.resume_for", { name })}>
            {t("shortlistQueue.row.resume")}
          </MenuItem>
        )}
        {canDecide && isRetryNegotiationEligible(row) && (
          <RetryNegotiationMenuItem row={row} onClose={close} onDone={onRetryDone} onError={onRetryError} />
        )}
      </Menu>
    </>
  );
}

// Part 17.6: the Shortlisting page is a queue. Waiting (screened) candidates are sorted into
// "Suggested by AI" (Match score >= the job's Shortlist threshold, no hard rule failed) and
// "Needs a look" (a hard rule flagged them -- never auto-rejected); decided ones sit in
// "Shortlisted" / "Rejected". Every decision here is a person's (bulk or one by one).
export default function ShortlistingListPage() {
  const t = useT();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { can } = useAuth();
  const canDecide = can(ROLE_MATRIX.screeningDecisions);

  const tabParam = searchParams.get("tab");
  const legacy = searchParams.get("shortlist_status");
  const tab: QueueTab = (QUEUE_TABS as readonly string[]).includes(tabParam ?? "")
    ? (tabParam as QueueTab)
    : (legacy && LEGACY_STATUS_TAB[legacy]) || "suggested";
  const jobId = searchParams.get("job") ?? "";

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("shortlist_status");
    setSearchParams(next, { replace: true });
  };

  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [refreshKey, setRefreshKey] = useState(0);

  // Waiting (screened) candidates, all loaded so they can be sorted by each job's threshold.
  const [pool, setPool] = useState<QueueRow[]>([]);
  const [poolTruncated, setPoolTruncated] = useState(false);
  const [poolLoading, setPoolLoading] = useState(true);
  const [poolError, setPoolError] = useState<unknown>(null);
  // Decided tabs are paged by the server.
  const [decidedRows, setDecidedRows] = useState<QueueRow[]>([]);
  const [decidedTotal, setDecidedTotal] = useState(0);
  const [decidedLoading, setDecidedLoading] = useState(false);
  const [decidedError, setDecidedError] = useState<unknown>(null);
  const [decidedCounts, setDecidedCounts] = useState<{ shortlisted: number | null; rejected: number | null }>({ shortlisted: null, rejected: null });

  const [selected, setSelected] = useState<Map<string, QueueRow>>(new Map());
  const [actionError, setActionError] = useState<unknown>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [quickBusy, setQuickBusy] = useState<string | null>(null);
  const [rejectRows, setRejectRows] = useState<QueueRow[] | null>(null);
  const [shortlistRows, setShortlistRows] = useState<QueueRow[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkResult | null>(null);
  const [statusPanelRow, setStatusPanelRow] = useState<QueueRow | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);

  useEffect(() => {
    jobsApi.list().then(setJobs).catch(() => setJobs([]));
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
    setSelected(new Map());
  }, [tab, jobId, search]);

  const reload = () => setRefreshKey((k) => k + 1);

  useEffect(() => {
    let alive = true;
    setPoolLoading(true);
    setPoolError(null);
    (async () => {
      const all: QueueRow[] = [];
      let total = 0;
      for (let p = 1; p <= POOL_MAX_PAGES; p += 1) {
        const res = await shortlistingApi.listShortlisting({
          page: p, pageSize: POOL_PAGE_SIZE, shortlistStatus: "under_review", jobRoleId: jobId || undefined, search: search || undefined,
        });
        all.push(...(res.items as QueueRow[]));
        total = res.total;
        if (all.length >= total || res.items.length === 0) break;
      }
      return { all, truncated: all.length < total };
    })()
      .then(({ all, truncated }) => {
        if (!alive) return;
        setPool(all);
        setPoolTruncated(truncated);
      })
      .catch((err) => alive && setPoolError(err))
      .finally(() => alive && setPoolLoading(false));
    return () => {
      alive = false;
    };
  }, [jobId, search, refreshKey]);

  useEffect(() => {
    let alive = true;
    const count = (status: ShortlistStatus) =>
      shortlistingApi
        .listShortlisting({ page: 1, pageSize: 1, shortlistStatus: status, jobRoleId: jobId || undefined, search: search || undefined })
        .then((r) => r.total)
        .catch(() => null);
    Promise.all([count("shortlisted"), count("not_shortlisted")]).then(([shortlisted, rejected]) => {
      if (alive) setDecidedCounts({ shortlisted, rejected });
    });
    return () => {
      alive = false;
    };
  }, [jobId, search, refreshKey]);

  const decidedTab = tab === "shortlisted" || tab === "rejected";
  useEffect(() => {
    if (!decidedTab) return;
    let alive = true;
    setDecidedLoading(true);
    setDecidedError(null);
    shortlistingApi
      .listShortlisting({ page, pageSize, shortlistStatus: DECIDED_STATUS[tab], jobRoleId: jobId || undefined, search: search || undefined })
      .then((res) => {
        if (!alive) return;
        setDecidedRows(res.items as QueueRow[]);
        setDecidedTotal(res.total);
      })
      .catch((err) => alive && setDecidedError(err))
      .finally(() => alive && setDecidedLoading(false));
    return () => {
      alive = false;
    };
  }, [decidedTab, tab, page, pageSize, jobId, search, refreshKey]);

  const { thresholds, ready: thresholdsReady } = useJobThresholds(
    [...pool.map((r) => r.job_role_id), ...decidedRows.map((r) => r.job_role_id)],
    refreshKey,
  );

  const buckets = useMemo(() => {
    const out = { suggested: [] as QueueRow[], needs_look: [] as QueueRow[], below: 0 };
    for (const row of pool) {
      const b = waitingBucket(row, thresholds.get(row.job_role_id));
      if (b === "below") out.below += 1;
      else out[b].push(row);
    }
    const byScore = (a: QueueRow, b: QueueRow) => (matchScoreOf(b) ?? -1) - (matchScoreOf(a) ?? -1);
    out.suggested.sort(byScore);
    out.needs_look.sort(byScore);
    return out;
  }, [pool, thresholds]);

  const waitingRows = tab === "suggested" ? buckets.suggested : tab === "needs_look" ? buckets.needs_look : [];
  const total = decidedTab ? decidedTotal : waitingRows.length;
  const rows: QueueRow[] = decidedTab ? decidedRows : waitingRows.slice((page - 1) * pageSize, page * pageSize);
  const loading = decidedTab ? decidedLoading : poolLoading || (tab === "suggested" && !thresholdsReady);
  const loadError = decidedTab ? decidedError : poolError;
  const details = useScreeningDetails(rows.map((r) => r.application_id), refreshKey);

  const counts: Record<QueueTab, number | null> = {
    suggested: poolLoading || !thresholdsReady ? null : buckets.suggested.length,
    needs_look: poolLoading ? null : buckets.needs_look.length,
    shortlisted: decidedCounts.shortlisted,
    rejected: decidedCounts.rejected,
  };

  const nameOf = (row: CandidateApplicationRow) => row.candidate_name || t("screening.unnamed");
  const selectedList = Array.from(selected.values());
  const allOnPageSelected = rows.length > 0 && rows.every((r) => selected.has(r.application_id));
  const someOnPageSelected = rows.some((r) => selected.has(r.application_id));
  const canCompare = selected.size >= 2 && selected.size <= MAX_COMPARE;

  const toggleOne = (row: QueueRow) =>
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(row.application_id)) next.delete(row.application_id);
      else next.set(row.application_id, row);
      return next;
    });
  const togglePage = () =>
    setSelected((prev) => {
      const next = new Map(prev);
      if (allOnPageSelected) rows.forEach((r) => next.delete(r.application_id));
      else rows.forEach((r) => next.set(r.application_id, r));
      return next;
    });

  const handleRefresh = () => {
    clearThresholdCache();
    reload();
  };

  const quickShortlist = async (row: QueueRow) => {
    setQuickBusy(row.application_id);
    setActionError(null);
    try {
      await shortlistingApi.updateStatus(row.application_id, { target_status: "shortlisted", reason: null, feedback: null });
      setToast(t("shortlistQueue.done.shortlisted", { name: nameOf(row) }));
      reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setQuickBusy(null);
    }
  };

  // One person or a batch; the rejection email (existing behaviour) only follows this decision.
  const decide = async (list: QueueRow[], target: "shortlisted" | "not_shortlisted", reason: string, feedback: string) => {
    setSubmitting(true);
    setActionError(null);
    try {
      if (list.length === 1) {
        await shortlistingApi.updateStatus(list[0].application_id, { target_status: target, reason: reason || null, feedback: feedback || null });
        setToast(t(target === "shortlisted" ? "shortlistQueue.done.shortlisted" : "shortlistQueue.done.rejected", { name: nameOf(list[0]) }));
      } else {
        const namesById = new Map(list.map((r) => [r.application_id, nameOf(r)]));
        const result = await shortlistingApi.bulkDecision({
          application_ids: list.map((r) => r.application_id),
          target_status: target,
          reason: reason || null,
          feedback: feedback || null,
        });
        setBulkResult({ result, target, namesById });
      }
      setSelected(new Map());
      setRejectRows(null);
      setShortlistRows(null);
      reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleResume = async (row: QueueRow) => {
    setActionError(null);
    try {
      await downloadResume(row.candidate_id, row.resume_path, row.candidate_name);
    } catch (err) {
      setActionError(err);
    }
  };

  const handleExport = async () => {
    try {
      const list: QueueRow[] =
        selected.size > 0
          ? selectedList
          : decidedTab
            ? ((await shortlistingApi.exportShortlisting({
              shortlistStatus: DECIDED_STATUS[tab], jobRoleId: jobId || undefined, search: search || undefined,
            })) as QueueRow[])
            : waitingRows;
      downloadCsv(
        `shortlisting-${tab}.csv`,
        ["Candidate", "Email", "Source", "Job Title", "Applied On", "Match score", "Shortlist threshold", "Hard rules", "Status"],
        list.map((row) => {
          const st = shortlistStatusOf(row.status);
          return [
            row.candidate_name,
            row.candidate_email,
            row.source,
            row.job_title,
            row.applied_on,
            matchScoreOf(row),
            thresholds.get(row.job_role_id) ?? "",
            row.knocked_out ? (row.knockout_reasons ?? []).join("; ") || "Flagged" : "",
            st ? t(STATUS_CHIP[st].key) : row.status,
          ];
        }),
      );
    } catch (err) {
      setActionError(err);
    }
  };

  const clearSearch = () => {
    setSearchInput("");
    setSearch("");
  };

  const tabLabel = (key: QueueTab) => {
    const label = t(`shortlistQueue.tab.${key}`);
    const count = counts[key];
    return count == null ? label : t("shortlistQueue.tab_count", { label, count });
  };

  const emptyKey = search ? null : tab;
  const columnCount = 9;

  const headRow = (
    <TableRow>
      <TableCell padding="checkbox">
        <Checkbox
          indeterminate={someOnPageSelected && !allOnPageSelected}
          checked={allOnPageSelected}
          onChange={togglePage}
          disabled={rows.length === 0}
          slotProps={{ input: { "aria-label": t("shortlistQueue.select_page") } }}
        />
      </TableCell>
      <TableCell>{t("shortlistQueue.col.candidate")}</TableCell>
      <TableCell>{t("shortlistQueue.col.job")}</TableCell>
      <TableCell>{t("shortlistQueue.col.score")}</TableCell>
      <TableCell>{t("shortlistQueue.col.knockout")}</TableCell>
      <TableCell>{t("shortlistQueue.col.source")}</TableCell>
      <TableCell>{t("shortlistQueue.col.applied")}</TableCell>
      <TableCell>{t("shortlistQueue.col.status")}</TableCell>
      <TableCell align="right">{t("shortlistQueue.col.actions")}</TableCell>
    </TableRow>
  );

  return (
    <Box>
      <PageHeader
        emoji="star"
        title={t("shortlistQueue.title")}
        purpose={t("shortlistQueue.purpose")}
        tourKey="shortlisting"
        primary={
          <Button variant="contained" startIcon={<DownloadOutlinedIcon />} onClick={handleExport} disabled={selected.size === 0 && total === 0}>
            {selected.size > 0 ? t("shortlistQueue.export_selected", { count: selected.size }) : t("shortlistQueue.export")}
          </Button>
        }
      />

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ xs: "stretch", md: "center" }} mb={2}>
        <TextField
          select
          size="small"
          label={t("shortlistQueue.job.label")}
          value={jobId}
          onChange={(e) => setParam("job", e.target.value)}
          sx={{ minWidth: 240 }}
        >
          <MenuItem value="">{t("shortlistQueue.job.all")}</MenuItem>
          {jobs.map((job) => (
            <MenuItem key={job.id} value={job.id}>{job.title}</MenuItem>
          ))}
        </TextField>
        <TextField
          size="small"
          placeholder={t("shortlistQueue.search")}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          slotProps={{
            input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> },
            htmlInput: { "aria-label": t("shortlistQueue.search") },
          }}
          sx={{ minWidth: 260 }}
        />
        <Box flex={1} />
        <Button startIcon={<RefreshIcon />} onClick={handleRefresh} disabled={loading}>{t("shortlistQueue.refresh")}</Button>
      </Stack>

      <Tabs
        value={tab}
        onChange={(_e, v: QueueTab) => setParam("tab", v === "suggested" ? "" : v)}
        variant="scrollable"
        allowScrollButtonsMobile
        sx={{ mb: 1, borderBottom: 1, borderColor: "divider" }}
      >
        {QUEUE_TABS.map((key) => (
          <Tab key={key} value={key} label={tabLabel(key)} />
        ))}
      </Tabs>
      <Typography variant="body2" color="text.secondary" mb={2}>{t(`shortlistQueue.tab_hint.${tab}`)}</Typography>

      {tab === "suggested" && !poolLoading && thresholdsReady && buckets.below > 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>
          {t("shortlistQueue.below_note", { count: buckets.below })}{" "}
          <Link component={RouterLink} to={jobId ? `/screening/list?job=${jobId}` : "/screening/list"}>{t("shortlistQueue.below_link")}</Link>
        </Alert>
      )}
      {!decidedTab && poolTruncated && (
        <Alert severity="warning" sx={{ mb: 2 }}>{t("shortlistQueue.truncated", { count: pool.length })}</Alert>
      )}

      {actionError != null && <Box mb={2}><FriendlyError error={actionError} compact /></Box>}
      {actionMessage && <Box mb={2}><FriendlyError what={actionMessage} fix={t("screening.retry_fix")} compact /></Box>}

      {bulkResult && (
        <Alert severity={bulkResult.result.skipped.length > 0 ? "warning" : "success"} sx={{ mb: 2 }} onClose={() => setBulkResult(null)}>
          <Typography variant="body2" fontWeight={600}>
            {t(bulkResult.target === "shortlisted" ? "shortlisting.bulk.result_shortlisted" : "shortlisting.bulk.result_rejected", {
              done: bulkResult.result.succeeded.length,
              count: bulkResult.result.succeeded.length + bulkResult.result.skipped.length,
            })}
            {bulkResult.result.skipped.length > 0 ? ` ${t("shortlisting.bulk.skipped", { count: bulkResult.result.skipped.length })}` : ""}
          </Typography>
          {bulkResult.result.skipped.length > 0 && (
            <Stack spacing={0.25} mt={0.5}>
              {bulkResult.result.skipped.map((skip) => (
                <Typography key={skip.application_id} variant="body2">
                  • {bulkResult.namesById.get(skip.application_id) || t("shortlisting.unknown_candidate")} — {skip.reason}
                </Typography>
              ))}
            </Stack>
          )}
        </Alert>
      )}

      {selected.size > 0 && (
        <Paper variant="outlined" sx={{ p: 1.25, mb: 2 }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ xs: "stretch", sm: "center" }} flexWrap="wrap" useFlexGap>
            <Typography variant="body2" fontWeight={700} sx={{ mr: 1 }}>{t("shortlistQueue.bulk.selected", { count: selected.size })}</Typography>
            {canDecide && tab !== "shortlisted" && (
              <Button size="small" variant="contained" color="success" onClick={() => setShortlistRows(selectedList)}>
                {t("shortlistQueue.bulk.shortlist")}
              </Button>
            )}
            {canDecide && tab !== "rejected" && (
              <Button size="small" variant="outlined" color="error" onClick={() => setRejectRows(selectedList)}>
                {t("shortlistQueue.bulk.reject")}
              </Button>
            )}
            <Tooltip title={canCompare ? "" : t("shortlistQueue.bulk.compare_hint")}>
              <span>
                <Button size="small" startIcon={<CompareArrowsOutlinedIcon />} disabled={!canCompare} onClick={() => setCompareOpen(true)}>
                  {t("shortlistQueue.bulk.compare", { count: Math.min(selected.size, MAX_COMPARE) })}
                </Button>
              </span>
            </Tooltip>
            <Button size="small" onClick={() => setSelected(new Map())}>{t("shortlistQueue.bulk.clear")}</Button>
          </Stack>
        </Paper>
      )}

      {loadError != null ? (
        <FriendlyError error={loadError} onRetry={handleRefresh} />
      ) : loading ? (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>{headRow}</TableHead>
            <TableBody>
              {Array.from({ length: 6 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: columnCount }).map((__, j) => (
                    <TableCell key={j}><Skeleton variant="text" /></TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : rows.length === 0 ? (
        <Card>
          {emptyKey ? (
            <EmptyState
              illustration="people-search"
              title={t(`shortlistQueue.empty.${emptyKey}`)}
              hint={t(`shortlistQueue.empty.${emptyKey}_hint`)}
              action={
                emptyKey === "suggested" || emptyKey === "needs_look" ? (
                  <Button variant="outlined" onClick={() => navigate("/screening/list")}>{t("shortlistQueue.go_screening")}</Button>
                ) : undefined
              }
            />
          ) : (
            <EmptyState
              illustration="search"
              title={t("shortlistQueue.empty.filtered")}
              action={<Button variant="outlined" onClick={clearSearch}>{t("shortlistQueue.empty.clear")}</Button>}
            />
          )}
        </Card>
      ) : (
        <>
          <TableContainer component={Paper} data-tour="shortlisting-table">
            <Table size="small">
              <TableHead>{headRow}</TableHead>
              <TableBody>
                {rows.map((row) => {
                  const name = nameOf(row);
                  const st = shortlistStatusOf(row.status);
                  const detail = details.get(row.application_id);
                  const waiting = st === "under_review" || st === "on_hold";
                  return (
                    <TableRow key={row.application_id} hover selected={selected.has(row.application_id)}>
                      <TableCell padding="checkbox">
                        <Checkbox
                          checked={selected.has(row.application_id)}
                          onChange={() => toggleOne(row)}
                          slotProps={{ input: { "aria-label": t("shortlistQueue.row.select", { name }) } }}
                        />
                      </TableCell>
                      <TableCell>
                        <CandidateCell row={row} />
                        <Link
                          component={RouterLink}
                          to={`/candidates/${row.application_id}`}
                          variant="caption"
                          aria-label={t("shortlistQueue.why_aria", { name })}
                          sx={{ display: "inline-block", mt: 0.5, ml: 5.25 }}
                        >
                          {t("shortlistQueue.why")}
                        </Link>
                      </TableCell>
                      <TableCell>{row.job_title}</TableCell>
                      <TableCell><MatchScoreChip score={matchScoreOf(row)} threshold={thresholds.get(row.job_role_id)} /></TableCell>
                      <TableCell><KnockoutChip row={row} /></TableCell>
                      <TableCell><SourceIcon source={row.source} /></TableCell>
                      <TableCell sx={{ whiteSpace: "nowrap" }}>{new Date(row.applied_on).toLocaleDateString()}</TableCell>
                      <TableCell>
                        <Stack spacing={0.75} alignItems="flex-start">
                          {st ? <StatusChip tone={STATUS_CHIP[st].tone} emoji={STATUS_CHIP[st].emoji} label={t(STATUS_CHIP[st].key)} /> : "—"}
                          {detail?.auto_shortlist && (
                            <AutoShortlistNotice
                              info={detail.auto_shortlist}
                              applicationId={row.application_id}
                              canDecide={canDecide}
                              onUndone={() => {
                                setToast(t("shortlistQueue.done.undone", { name }));
                                reload();
                              }}
                              onError={setActionError}
                            />
                          )}
                        </Stack>
                      </TableCell>
                      <TableCell align="right">
                        <Stack direction="row" spacing={0.5} justifyContent="flex-end" alignItems="center">
                          {canDecide && waiting && (
                            <>
                              <Button
                                size="small"
                                variant="contained"
                                color="success"
                                onClick={() => quickShortlist(row)}
                                disabled={quickBusy != null}
                                aria-label={t("shortlistQueue.row.shortlist_aria", { name })}
                                sx={{ whiteSpace: "nowrap" }}
                              >
                                {quickBusy === row.application_id ? <CircularProgress size={14} color="inherit" /> : t("shortlistQueue.row.shortlist")}
                              </Button>
                              <Button
                                size="small"
                                color="error"
                                onClick={() => setRejectRows([row])}
                                disabled={quickBusy != null}
                                aria-label={t("shortlistQueue.row.reject_aria", { name })}
                              >
                                {t("shortlistQueue.row.reject")}
                              </Button>
                            </>
                          )}
                          <RowMenu
                            row={row}
                            canDecide={canDecide}
                            onChangeStatus={setStatusPanelRow}
                            onResume={handleResume}
                            onRetryDone={reload}
                            onRetryError={setActionMessage}
                          />
                        </Stack>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>

          <PaginationFooter
            id="shortlisting"
            page={page}
            pageSize={pageSize}
            total={total}
            selected={selected.size}
            onPage={setPage}
            onPageSize={(n) => {
              setPageSize(Math.min(n, 50));
              setPage(1);
            }}
          />
        </>
      )}

      <Dialog open={statusPanelRow != null} onClose={() => setStatusPanelRow(null)} fullWidth maxWidth="sm">
        <DialogTitle>
          {t("shortlisting.update_status_for", { name: statusPanelRow?.candidate_name || t("shortlisting.panel.this_candidate") })}
        </DialogTitle>
        <DialogContent>
          {statusPanelRow && (
            <Box mt={1}>
              <ShortlistStatusPanel
                applicationId={statusPanelRow.application_id}
                candidateName={statusPanelRow.candidate_name}
                currentApplicationStatus={statusPanelRow.status}
                onSaved={(_updated: ApplicationRead) => {
                  setStatusPanelRow(null);
                  reload();
                }}
              />
            </Box>
          )}
        </DialogContent>
      </Dialog>

      <RejectReasonDialog
        open={rejectRows != null}
        people={(rejectRows ?? []).map((r) => ({ id: r.application_id, name: nameOf(r), job: r.job_title }))}
        submitting={submitting}
        onCancel={() => setRejectRows(null)}
        onConfirm={(reason, feedback) => rejectRows && decide(rejectRows, "not_shortlisted", reason, feedback)}
      />

      <BulkShortlistDialog
        open={shortlistRows != null}
        people={(shortlistRows ?? []).map((r) => ({ id: r.application_id, name: nameOf(r), job: r.job_title }))}
        submitting={submitting}
        onCancel={() => setShortlistRows(null)}
        onConfirm={(reason, feedback) => shortlistRows && decide(shortlistRows, "shortlisted", reason, feedback)}
      />

      <CompareDialog
        open={compareOpen}
        rows={selectedList}
        onClose={() => setCompareOpen(false)}
        onOpenCandidate={(id) => navigate(`/candidates/${id}`)}
      />

      <Snackbar open={toast != null} autoHideDuration={5000} onClose={() => setToast(null)} message={toast ?? ""} />
    </Box>
  );
}
