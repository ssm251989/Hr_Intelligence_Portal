import { useEffect, useMemo, useState } from "react";
import CompareArrowsOutlinedIcon from "@mui/icons-material/CompareArrowsOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import SearchIcon from "@mui/icons-material/Search";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useNavigate } from "react-router-dom";

import { candidatesApi, jobsApi, screeningApi } from "../api/client";
import { isTerminalApplicationStatus, type CandidateApplicationRow, type JobRoleRead } from "../api/types";
import CandidateFiltersPanel, { EMPTY_CANDIDATE_FILTERS, type CandidateFilters } from "../components/CandidateFiltersPanel";
import ListToolbar, { type ListColumn, type ListViewState } from "../components/ListToolbar";
import RetryNegotiationMenuItem, { isRetryNegotiationEligible } from "../components/RetryNegotiationMenuItem";
import SourceIcon from "../components/SourceIcon";
import CompareDialog, { MAX_COMPARE } from "../components/screening/CompareDialog";
import { useScoreCounts, useScreeningDetails } from "../components/screening/hooks";
import { CandidateCell, DEFAULT_PAGE_SIZE, loadSortedPage, PaginationFooter, SortSelect, type SortMode } from "../components/screening/listParts";
import { ScoreBadge } from "../components/screening/ScoreParts";
import ThresholdSlider from "../components/screening/ThresholdSlider";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import { useT } from "../i18n";
import { EmptyState, FriendlyError, PageHeader, StatusChip } from "../ui-kit";
import { downloadCsv } from "../utils/csv";
import { screeningScoreDisplay } from "../utils/screeningScore";

const SEARCH_DEBOUNCE_MS = 300;
const COLUMN_KEYS = ["source", "job", "applied", "skill", "score", "pass", "ranking", "status", "remarks"] as const;

// Same "Active"/"Inactive"/"On Hold" reading as the Candidates List -- one status language
// across every table, now as colour + emoji + word.
function ApplicationStatusChip({ status }: { status: string }) {
  if (status === "on_hold") return <StatusChip status="on_hold" />;
  return <StatusChip status={isTerminalApplicationStatus(status) ? "inactive" : "active"} />;
}

// One 3-dot Actions column instead of a row of named buttons.
function ScreeningActionsMenu({
  row, canDecide, actionId, onView, onScreen, onRank, onRetryDone, onRetryError,
}: {
  row: CandidateApplicationRow;
  canDecide: boolean;
  actionId: string | null;
  onView: (applicationId: string) => void;
  onScreen: (applicationId: string) => void;
  onRank: (applicationId: string) => void;
  onRetryDone: () => void;
  onRetryError: (message: string) => void;
}) {
  const t = useT();
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const pending = actionId === row.application_id;
  const canScreen = canDecide && row.status === "received";
  const canRank = canDecide && row.match_score != null;
  // A row already Shortlisted -- possibly stuck after a failed auto-negotiation -- can show
  // up here too; same shared eligibility/handler as the Shortlisting List's row action.
  const showRetry = canDecide && isRetryNegotiationEligible(row);

  return (
    <>
      <IconButton
        size="small"
        onClick={(e) => setAnchorEl(e.currentTarget)}
        disabled={pending}
        aria-label={t("screening.actions_for", { name: row.candidate_name || t("screening.unnamed") })}
        aria-haspopup="menu"
      >
        <MoreVertIcon fontSize="small" />
      </IconButton>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        <MenuItem
          onClick={() => {
            setAnchorEl(null);
            onView(row.application_id);
          }}
        >
          <VisibilityOutlinedIcon fontSize="small" sx={{ mr: 1 }} />
          {t("screening.view")}
        </MenuItem>
        {canScreen && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              onScreen(row.application_id);
            }}
            disabled={pending}
          >
            {pending ? t("screening.screening_now") : t("screening.screen")}
          </MenuItem>
        )}
        {canRank && (
          <MenuItem
            onClick={() => {
              setAnchorEl(null);
              onRank(row.application_id);
            }}
            disabled={pending}
          >
            {pending ? t("screening.ranking_now") : row.ranking_score != null ? t("screening.rerank") : t("screening.rank")}
          </MenuItem>
        )}
        {showRetry && (
          <RetryNegotiationMenuItem row={row} onClose={() => setAnchorEl(null)} onDone={onRetryDone} onError={onRetryError} />
        )}
      </Menu>
    </>
  );
}

// Part E: the Screening module's own filterable, paginated table -- same filters panel and
// list/export endpoints as the Candidates List, focused on the screening decisions.
// Part 15.4: one score with breakdown on hover (S1), highest first (S3), a pass-mark slider
// with a live count (S4) and compare up to 3 (S5).
export default function ScreeningListPage() {
  const t = useT();
  const navigate = useNavigate();
  const { can } = useAuth();
  const canDecide = can(ROLE_MATRIX.screeningDecisions);
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [rows, setRows] = useState<CandidateApplicationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);

  const [filters, setFilters] = useState<CandidateFilters>(EMPTY_CANDIDATE_FILTERS);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("score");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  // Forces loadPage to re-run on Refresh even when every filter/search/page value already
  // happens to be at its default.
  const [refreshKey, setRefreshKey] = useState(0);
  const anyFilterActive = Boolean(search) || Object.values(filters).some(Boolean);
  const [selected, setSelected] = useState<Map<string, CandidateApplicationRow>>(new Map());
  const [compareOpen, setCompareOpen] = useState(false);
  const [passRange, setPassRange] = useState<[number, number]>([75, 100]);
  const [visibleColumns, setVisibleColumns] = useState<string[]>([...COLUMN_KEYS]);

  const columns: ListColumn[] = COLUMN_KEYS.map((key) => ({ key, label: t(`screening.col.${key}`) }));
  const show = (key: string) => visibleColumns.includes(key);

  useEffect(() => {
    jobsApi.list().then(setJobs).catch(() => setJobs([]));
    // The pass line starts at the company's own "interview ready" mark.
    screeningApi
      .getSettings()
      .then((s) => setPassRange([Number(s.interview_min_score), Number(s.interview_max_score)]))
      .catch(() => undefined);
  }, []);

  // Debounced: this is a server round-trip per keystroke otherwise.
  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
  }, [filters, search, sort]);

  const listParams = () => ({
    search: search || undefined,
    jobRoleId: filters.jobRoleId || undefined,
    status: filters.status || undefined,
    source: filters.source || undefined,
    location: filters.location || undefined,
    experienceMin: filters.experienceMin ? Number(filters.experienceMin) : undefined,
    experienceMax: filters.experienceMax ? Number(filters.experienceMax) : undefined,
    appliedAfter: filters.appliedAfter || undefined,
    appliedBefore: filters.appliedBefore || undefined,
    matchScoreMin: filters.matchScoreMin ? Number(filters.matchScoreMin) : undefined,
    matchScoreMax: filters.matchScoreMax ? Number(filters.matchScoreMax) : undefined,
    // This page's score range filter targets composite_score (the Screening Score column).
    scoreField: "composite_score" as const,
  });

  const loadPage = () => {
    setLoading(true);
    setLoadError(null);
    const { scoreField: _scoreField, ...rest } = listParams();
    loadSortedPage(sort, { scope: "screening", page, pageSize, ...rest }, () =>
      candidatesApi.listApplications({ page, pageSize, ...listParams() }),
    )
      .then((result) => {
        setRows(result.items);
        setTotal(result.total);
      })
      .catch(setLoadError)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search, filters, sort, refreshKey]);

  const details = useScreeningDetails(rows.map((r) => r.application_id), refreshKey);
  const countParams = useMemo(() => {
    const { scoreField: _s, matchScoreMin: _a, matchScoreMax: _b, ...rest } = listParams();
    return { scope: "screening" as const, ...rest };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, filters]);
  const counts = useScoreCounts(countParams, refreshKey);

  const handleRefresh = () => {
    setFilters(EMPTY_CANDIDATE_FILTERS);
    setSearchInput("");
    setSearch("");
    setPage(1);
    setPageSize(DEFAULT_PAGE_SIZE);
    setRefreshKey((k) => k + 1);
  };

  const handleExportCsv = async () => {
    try {
      const result =
        selected.size > 0
          ? await candidatesApi.exportApplications({ applicationIds: Array.from(selected.keys()) })
          : await candidatesApi.exportApplications(listParams());
      downloadCsv(
        "screening.csv",
        [
          "Candidate", "Email", "Job Applied", "Status", "Applied On", "Skill Match %",
          "Screening Score", "Resume Match", "Ranking Score", "Remarks",
        ],
        result.map((row) => [
          row.candidate_name,
          row.candidate_email,
          row.job_title,
          row.status,
          row.applied_on,
          row.skill_match_pct,
          row.composite_score ?? row.match_score,
          row.match_score,
          row.ranking_score,
          row.interview_remarks,
        ]),
      );
    } catch (err) {
      setActionError(err);
    }
  };

  const allOnPageSelected = rows.length > 0 && rows.every((row) => selected.has(row.application_id));
  const someOnPageSelected = rows.some((row) => selected.has(row.application_id));

  const toggleSelectAllOnPage = () => {
    setSelected((prev) => {
      const next = new Map(prev);
      if (allOnPageSelected) rows.forEach((row) => next.delete(row.application_id));
      else rows.forEach((row) => next.set(row.application_id, row));
      return next;
    });
  };

  const toggleSelectOne = (row: CandidateApplicationRow) => {
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(row.application_id)) next.delete(row.application_id);
      else next.set(row.application_id, row);
      return next;
    });
  };

  const runAction = async (applicationId: string, fn: (id: string) => Promise<unknown>) => {
    setActionId(applicationId);
    setActionError(null);
    try {
      await fn(applicationId);
      loadPage();
    } catch (err) {
      setActionError(err);
    } finally {
      setActionId(null);
    }
  };

  const viewState: ListViewState = { columns: visibleColumns, filters: { ...filters, search: searchInput, sort } };
  const applyViewState = (next: ListViewState) => {
    if (Array.isArray(next.columns) && next.columns.length > 0) setVisibleColumns(next.columns);
    const raw = (next.filters ?? {}) as Record<string, string>;
    const { search: s = "", sort: so, ...rest } = raw;
    const nextFilters = { ...EMPTY_CANDIDATE_FILTERS, ...rest } as CandidateFilters;
    if (JSON.stringify(nextFilters) !== JSON.stringify(filters)) setFilters(nextFilters);
    if (s !== searchInput) setSearchInput(s);
    if ((so === "score" || so === "newest") && so !== sort) setSort(so);
  };

  const csvRows = rows.map((row) => ({
    source: row.source, job: row.job_title, applied: row.applied_on, skill: row.skill_match_pct,
    score: screeningScoreDisplay(row).value, pass: passLabel(row), ranking: row.ranking_score, status: row.status,
    remarks: row.interview_remarks,
  }));

  function passes(row: CandidateApplicationRow): boolean | null {
    const v = screeningScoreDisplay(row).value;
    if (v == null) return null;
    const r = Math.round(v);
    return r >= passRange[0] && r <= passRange[1];
  }
  function passLabel(row: CandidateApplicationRow): string {
    const p = passes(row);
    return p == null ? "" : p ? t("screening.pass.yes") : t("screening.pass.no");
  }

  const selectedRows = Array.from(selected.values());
  const canCompare = selected.size >= 2 && selected.size <= MAX_COMPARE;
  const compareButton = (
    <Tooltip title={selected.size > MAX_COMPARE ? t("screening.compare.too_many", { max: MAX_COMPARE }) : ""}>
      <span>
        <Button size="small" variant="contained" startIcon={<CompareArrowsOutlinedIcon />} disabled={!canCompare} onClick={() => setCompareOpen(true)}>
          {t("screening.compare.button", { count: Math.min(selected.size, MAX_COMPARE) })}
        </Button>
      </span>
    </Tooltip>
  );

  const headCells = (
    <>
      <TableCell>{t("screening.col.candidate")}</TableCell>
      {show("source") && <TableCell>{t("screening.col.source")}</TableCell>}
      {show("job") && <TableCell>{t("screening.col.job")}</TableCell>}
      {show("applied") && <TableCell>{t("screening.col.applied")}</TableCell>}
      {show("skill") && <TableCell>{t("screening.col.skill")}</TableCell>}
      {show("score") && <TableCell>{t("screening.col.score")}</TableCell>}
      {show("pass") && <TableCell>{t("screening.col.pass")}</TableCell>}
      {show("ranking") && <TableCell>{t("screening.col.ranking")}</TableCell>}
      {show("status") && <TableCell>{t("screening.col.status")}</TableCell>}
      {show("remarks") && <TableCell>{t("screening.col.remarks")}</TableCell>}
      <TableCell align="right">{t("screening.col.actions")}</TableCell>
    </>
  );
  const columnCount = 3 + COLUMN_KEYS.filter(show).length;

  return (
    <Box>
      <PageHeader
        emoji="magnifier"
        title={t("screening.list.title")}
        purpose={t("screening.list.purpose")}
        tourKey="screening"
        primary={
          <Button variant="contained" startIcon={<DownloadOutlinedIcon />} onClick={handleExportCsv} disabled={total === 0}>
            {selected.size > 0 ? t("screening.export_selected", { count: selected.size }) : t("screening.export_all", { count: total })}
          </Button>
        }
      />

      <Card sx={{ mb: 2 }} data-tour="screening-slider">
        <CardContent>
          <ThresholdSlider
            id="screening-pass"
            value={passRange}
            onChange={setPassRange}
            counts={counts?.counts}
            scores={rows.map((r) => screeningScoreDisplay(r).value)}
            label={t("screening.pass.slider")}
            info={t("screening.pass.info")}
          />
        </CardContent>
      </Card>

      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ xs: "stretch", md: "center" }} mb={2}>
        <TextField
          size="small"
          placeholder={t("screening.search")}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          slotProps={{
            input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> },
            htmlInput: { "aria-label": t("screening.search") },
          }}
          sx={{ minWidth: 260 }}
        />
        <SortSelect id="screening" value={sort} onChange={setSort} />
      </Stack>

      <Box mb={2}>
        <CandidateFiltersPanel jobs={jobs} filters={filters} onChange={setFilters} scoreLabel="Screening" />
      </Box>

      {actionError != null && (
        <Box mb={2}><FriendlyError error={actionError} compact /></Box>
      )}
      {actionMessage && (
        <Box mb={2}><FriendlyError what={actionMessage} fix={t("screening.retry_fix")} compact /></Box>
      )}

      <ListToolbar
        listKey="screening_list"
        columns={columns}
        state={viewState}
        onStateChange={applyViewState}
        rows={csvRows}
        loading={loading}
        onRefresh={handleRefresh}
        selectedCount={selected.size}
        bulkActions={
          <>
            {compareButton}
            <Button size="small" onClick={() => setSelected(new Map())}>{t("screening.clear_selection")}</Button>
          </>
        }
      />

      {loadError != null ? (
        <FriendlyError error={loadError} onRetry={loadPage} />
      ) : loading ? (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox" />
                {headCells}
              </TableRow>
            </TableHead>
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
          {total === 0 && !anyFilterActive ? (
            <EmptyState
              illustration="people-search"
              title={t("screening.empty.none")}
              hint={t("screening.empty.none_hint")}
              action={<Button variant="contained" onClick={() => navigate("/candidates")}>{t("screening.empty.go_candidates")}</Button>}
            />
          ) : (
            <EmptyState
              illustration="search"
              title={t("screening.empty.filtered")}
              action={<Button variant="outlined" onClick={handleRefresh}>{t("screening.empty.clear")}</Button>}
            />
          )}
        </Card>
      ) : (
        <>
          <TableContainer component={Paper} data-tour="screening-table">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox">
                    <Checkbox
                      indeterminate={someOnPageSelected && !allOnPageSelected}
                      checked={allOnPageSelected}
                      onChange={toggleSelectAllOnPage}
                      slotProps={{ input: { "aria-label": t("screening.select_page") } }}
                    />
                  </TableCell>
                  {headCells}
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => {
                  const { value, tooltip } = screeningScoreDisplay(row);
                  const pass = passes(row);
                  const name = row.candidate_name || t("screening.unnamed");
                  return (
                    <TableRow key={row.application_id} hover selected={selected.has(row.application_id)}>
                      <TableCell padding="checkbox">
                        <Checkbox
                          checked={selected.has(row.application_id)}
                          onChange={() => toggleSelectOne(row)}
                          slotProps={{ input: { "aria-label": t("screening.select_one", { name }) } }}
                        />
                      </TableCell>
                      <TableCell><CandidateCell row={row} /></TableCell>
                      {show("source") && <TableCell><SourceIcon source={row.source} /></TableCell>}
                      {show("job") && <TableCell>{row.job_title}</TableCell>}
                      {show("applied") && <TableCell>{new Date(row.applied_on).toLocaleDateString()}</TableCell>}
                      {show("skill") && (
                        <TableCell>{row.skill_match_pct != null ? t("screening.pct", { n: Math.round(row.skill_match_pct) }) : "—"}</TableCell>
                      )}
                      {show("score") && (
                        <TableCell><ScoreBadge value={value} detail={details.get(row.application_id)} fallbackHint={tooltip} /></TableCell>
                      )}
                      {show("pass") && (
                        <TableCell>
                          {pass == null ? "—" : pass ? (
                            <StatusChip tone="ok" emoji="check" label={t("screening.pass.yes")} />
                          ) : (
                            <StatusChip tone="muted" emoji="pause" label={t("screening.pass.no")} />
                          )}
                        </TableCell>
                      )}
                      {show("ranking") && <TableCell>{row.ranking_score != null ? row.ranking_score : "—"}</TableCell>}
                      {show("status") && <TableCell><ApplicationStatusChip status={row.status} /></TableCell>}
                      {show("remarks") && (
                        <TableCell sx={{ maxWidth: 220 }}>
                          {row.interview_remarks ? (
                            <Tooltip title={row.interview_remarks}>
                              <Typography variant="body2" noWrap>{row.interview_remarks}</Typography>
                            </Tooltip>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                      )}
                      <TableCell align="right">
                        <ScreeningActionsMenu
                          row={row}
                          canDecide={canDecide}
                          actionId={actionId}
                          onView={(applicationId) => navigate(`/candidates/${applicationId}`)}
                          onScreen={(id) => runAction(id, screeningApi.screen)}
                          onRank={(id) => runAction(id, screeningApi.rank)}
                          onRetryDone={loadPage}
                          onRetryError={setActionMessage}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>

          <PaginationFooter
            id="screening"
            page={page}
            pageSize={pageSize}
            total={total}
            selected={selected.size}
            onPage={setPage}
            onPageSize={(n) => {
              setPageSize(n);
              setPage(1);
            }}
          />
        </>
      )}

      <CompareDialog
        open={compareOpen}
        rows={selectedRows}
        onClose={() => setCompareOpen(false)}
        onOpenCandidate={(id) => navigate(`/candidates/${id}`)}
      />
    </Box>
  );
}
