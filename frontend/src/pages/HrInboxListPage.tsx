import { useEffect, useMemo, useState } from "react";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import SearchIcon from "@mui/icons-material/Search";
import TableRowsOutlinedIcon from "@mui/icons-material/TableRowsOutlined";
import ViewQuiltOutlinedIcon from "@mui/icons-material/ViewQuiltOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import Card from "@mui/material/Card";
import FormControl from "@mui/material/FormControl";
import Grid from "@mui/material/Grid";
import InputAdornment from "@mui/material/InputAdornment";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Pagination from "@mui/material/Pagination";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useNavigate } from "react-router-dom";

import { hrInboxApi } from "../api/client";
import type { HrInboundEmailRead } from "../api/types";
import InboxCandidatePane from "../components/inbox/InboxCandidatePane";
import InboxThreadPane from "../components/inbox/InboxThreadPane";
import { localeTag } from "../components/interviews/weekDates";
import ListToolbar, { type ListColumn, type ListViewState } from "../components/ListToolbar";
import { useI18n } from "../i18n";
import Emoji from "../ui-kit/Emoji";
import EmptyState from "../ui-kit/EmptyState";
import FriendlyError from "../ui-kit/FriendlyError";
import StatusChip from "../ui-kit/StatusChip";
import PageHeader from "../ui-kit/PageHeader";
import UserAvatar from "../ui-kit/UserAvatar";
import { downloadCsv } from "../utils/csv";

const ROWS_PER_PAGE_OPTIONS = [10, 25, 50, 100];
const DEFAULT_PAGE_SIZE = 25;
const SEARCH_DEBOUNCE_MS = 300;
const VIEW_STORAGE_KEY = "hrms.hr-inbox.view";

type MatchedFilter = "" | "matched" | "unmatched";
type ViewMode = "panes" | "table";

function readStoredView(): ViewMode {
  try {
    return localStorage.getItem(VIEW_STORAGE_KEY) === "table" ? "table" : "panes";
  } catch {
    return "panes";
  }
}

// The "HR Inbox" -- every message the shared HR mailbox has received (linked to a
// candidate or not). Spec H1: three panes (list / thread / candidate); the plain table stays
// one click away. Unmatched mail can be assigned to a candidate from the right pane (H3).
export default function HrInboxListPage() {
  const navigate = useNavigate();
  const f = useTheme().palette.fresh;
  const { t, locale } = useI18n();
  const fmt = new Intl.DateTimeFormat(localeTag(locale), { dateStyle: "medium", timeStyle: "short" });
  const shortFmt = new Intl.DateTimeFormat(localeTag(locale), { day: "numeric", month: "short" });

  const columns: ListColumn[] = useMemo(
    () => [
      { key: "from_address", label: t("inbox.col.from") },
      { key: "subject", label: t("inbox.col.subject") },
      { key: "received_at", label: t("inbox.col.received") },
      { key: "matched_candidate_name", label: t("inbox.col.candidate") },
      { key: "matched_job_title", label: t("inbox.col.job") },
    ],
    [t],
  );

  const [rows, setRows] = useState<HrInboundEmailRead[]>([]);
  const [total, setTotal] = useState(0);
  const [unmatchedTotal, setUnmatchedTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [matchedFilter, setMatchedFilter] = useState<MatchedFilter>("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [refreshKey, setRefreshKey] = useState(0);
  const [visibleColumns, setVisibleColumns] = useState<string[]>(columns.map((c) => c.key));
  const [view, setView] = useState<ViewMode>(readStoredView);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const anyFilterActive = Boolean(search) || Boolean(matchedFilter);

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
  }, [search, matchedFilter]);

  const listParams = () => ({
    search: search || undefined,
    matched: matchedFilter === "" ? undefined : matchedFilter === "matched",
  });

  const loadPage = () => {
    setLoading(true);
    setError(null);
    hrInboxApi
      .list({ page, pageSize, ...listParams() })
      .then((result) => {
        setRows(result.items);
        setTotal(result.total);
        setSelectedId((cur) => (cur && result.items.some((r) => r.id === cur) ? cur : result.items[0]?.id ?? null));
      })
      .catch(setError)
      .finally(() => setLoading(false));
    hrInboxApi
      .list({ page: 1, pageSize: 1, matched: false })
      .then((r) => setUnmatchedTotal(r.total))
      .catch(() => setUnmatchedTotal(null));
  };

  useEffect(() => {
    loadPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, search, matchedFilter, refreshKey]);

  const handleRefresh = () => {
    setSearchInput("");
    setSearch("");
    setMatchedFilter("");
    setPage(1);
    setPageSize(DEFAULT_PAGE_SIZE);
    setRefreshKey((k) => k + 1);
  };

  const changeView = (next: ViewMode | null) => {
    if (!next) return;
    setView(next);
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, next);
    } catch {
      /* per-visit only */
    }
  };

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pageStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = Math.min(page * pageSize, total);

  const handlePageSizeChange = (event: SelectChangeEvent<number>) => {
    setPageSize(Number(event.target.value));
    setPage(1);
  };

  const handleExportCsv = async () => {
    try {
      const result = await hrInboxApi.export(listParams());
      downloadCsv(
        "hr-inbox.csv",
        [t("inbox.col.from"), t("inbox.col.to"), t("inbox.col.subject"), t("inbox.col.received"), t("inbox.col.candidate"), t("inbox.col.job")],
        result.map((row) => [row.from_address, row.to_address, row.subject, row.received_at, row.matched_candidate_name, row.matched_job_title]),
      );
    } catch (err) {
      setError(err);
    }
  };

  const viewState: ListViewState = { columns: visibleColumns, filters: { search, matched: matchedFilter } };
  const onViewStateChange = (next: ListViewState) => {
    if (Array.isArray(next.columns)) setVisibleColumns(next.columns);
    const nf = (next.filters ?? {}) as { search?: string; matched?: MatchedFilter };
    if (typeof nf.search === "string") {
      setSearchInput(nf.search);
      setSearch(nf.search);
    }
    if (nf.matched === "" || nf.matched === "matched" || nf.matched === "unmatched") setMatchedFilter(nf.matched);
  };

  const selected = rows.find((r) => r.id === selectedId) ?? null;
  const shown = columns.filter((c) => visibleColumns.includes(c.key));

  const matchChip = (row: HrInboundEmailRead) =>
    row.matched_candidate_id ? (
      <StatusChip tone="ok" emoji="link" label={row.matched_candidate_name || t("inbox.linked")} />
    ) : (
      <StatusChip tone="sun" emoji="question" label={t("inbox.needs_candidate")} />
    );

  const tableCell = (row: HrInboundEmailRead, key: string) => {
    switch (key) {
      case "from_address":
        return (
          <Typography variant="body2" fontWeight={600} noWrap>
            {row.from_address}
          </Typography>
        );
      case "subject":
        return row.subject ? (
          <Tooltip title={row.subject}>
            <Typography variant="body2" noWrap sx={{ maxWidth: 260 }}>
              {row.subject}
            </Typography>
          </Tooltip>
        ) : (
          "—"
        );
      case "received_at":
        return row.received_at ? fmt.format(new Date(row.received_at)) : "—";
      case "matched_candidate_name":
        return row.matched_candidate_id && row.matched_application_id ? (
          <ButtonBase onClick={() => navigate(`/candidates/${row.matched_application_id}`)} aria-label={t("inbox.open_candidate", { name: row.matched_candidate_name || "" })} sx={{ borderRadius: 999 }}>
            {matchChip(row)}
          </ButtonBase>
        ) : (
          matchChip(row)
        );
      case "matched_job_title":
        return row.matched_job_title || "—";
      default:
        return null;
    }
  };

  const listPane = (
    <Stack component="ul" aria-label={t("inbox.list.label")} sx={{ listStyle: "none", m: 0, p: 0 }} spacing={0.75}>
      {rows.map((row) => {
        const active = row.id === selectedId;
        return (
          <Box component="li" key={row.id}>
            <ButtonBase
              onClick={() => setSelectedId(row.id)}
              aria-current={active ? "true" : undefined}
              aria-label={t("inbox.list.item_label", { from: row.from_address, subject: row.subject || t("inbox.no_subject") })}
              sx={{
                width: "100%", textAlign: "left", display: "flex", gap: 1.25, alignItems: "flex-start", p: 1.25, borderRadius: "12px",
                bgcolor: active ? f.brandSoft : "transparent", border: `1px solid ${active ? f.brand : "transparent"}`,
                "&:hover": { bgcolor: active ? f.brandSoft : f.surface2 }, "&:focus-visible": { outline: `2px solid ${f.brand}`, outlineOffset: 1 },
              }}
            >
              <UserAvatar name={row.matched_candidate_name || row.from_address} size={36} />
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Stack direction="row" justifyContent="space-between" spacing={1}>
                  <Typography sx={{ fontWeight: 700, fontSize: 14 }} noWrap>
                    {row.matched_candidate_name || row.from_address}
                  </Typography>
                  <Typography sx={{ color: f.muted, fontSize: 12, flexShrink: 0 }}>{row.received_at ? shortFmt.format(new Date(row.received_at)) : ""}</Typography>
                </Stack>
                <Typography sx={{ fontSize: 13 }} noWrap>{row.subject || t("inbox.no_subject")}</Typography>
                <Box sx={{ mt: 0.5 }}>{matchChip(row)}</Box>
              </Box>
            </ButtonBase>
          </Box>
        );
      })}
    </Stack>
  );

  const pager = (
    <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
      <Typography variant="body2" sx={{ color: f.muted }}>
        {t("inbox.list.showing", { start: pageStart, end: pageEnd, count: total })}
      </Typography>
      <Stack direction="row" spacing={2} alignItems="center">
        <FormControl size="small" sx={{ minWidth: 130 }}>
          <InputLabel id="hr-inbox-rows-per-page-label">{t("interviews.list.rows_per_page")}</InputLabel>
          <Select labelId="hr-inbox-rows-per-page-label" label={t("interviews.list.rows_per_page")} value={pageSize} onChange={handlePageSizeChange}>
            {ROWS_PER_PAGE_OPTIONS.map((size) => (
              <MenuItem key={size} value={size}>
                {size}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <Pagination count={pageCount} page={page} onChange={(_e, value) => setPage(value)} size="small" color="primary" />
      </Stack>
    </Stack>
  );

  return (
    <Box>
      <PageHeader
        emoji="inbox"
        title={t("inbox.title")}
        purpose={t("inbox.purpose")}
        tourKey="hr-inbox"
        extra={
          <Button variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={handleExportCsv} disabled={total === 0}>
            {t("inbox.export_all")}
          </Button>
        }
        primary={
          unmatchedTotal ? (
            <Button
              variant="contained"
              startIcon={<Emoji name="link" size={18} />}
              onClick={() => {
                setMatchedFilter("unmatched");
                changeView("panes");
              }}
            >
              {t("inbox.assign_queue", { count: unmatchedTotal })}
            </Button>
          ) : undefined
        }
      />

      <Card sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ xs: "stretch", md: "center" }} justifyContent="space-between">
          <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
            <TextField
              size="small"
              placeholder={t("inbox.search")}
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }, htmlInput: { "aria-label": t("inbox.search") } }}
              sx={{ minWidth: 240 }}
            />
            <FormControl size="small" sx={{ minWidth: 190 }}>
              <InputLabel id="hr-inbox-matched-filter-label">{t("inbox.filter.label")}</InputLabel>
              <Select labelId="hr-inbox-matched-filter-label" label={t("inbox.filter.label")} value={matchedFilter} onChange={(e) => setMatchedFilter(e.target.value as MatchedFilter)}>
                <MenuItem value="">{t("inbox.filter.all")}</MenuItem>
                <MenuItem value="matched">{t("inbox.filter.matched")}</MenuItem>
                <MenuItem value="unmatched">{t("inbox.filter.unmatched")}</MenuItem>
              </Select>
            </FormControl>
          </Stack>
          <ToggleButtonGroup exclusive size="small" value={view} onChange={(_e, v: ViewMode | null) => changeView(v)} aria-label={t("interviews.list.view_label")}
            sx={{ alignSelf: { xs: "flex-start", md: "center" }, "& .MuiToggleButton-root": { textTransform: "none", fontWeight: 700, px: 1.5, gap: 0.75 } }}>
            <ToggleButton value="panes" aria-label={t("inbox.view.panes")}>
              <ViewQuiltOutlinedIcon fontSize="small" />
              {t("inbox.view.panes")}
            </ToggleButton>
            <ToggleButton value="table" aria-label={t("interviews.list.view_table")}>
              <TableRowsOutlinedIcon fontSize="small" />
              {t("interviews.list.view_table")}
            </ToggleButton>
          </ToggleButtonGroup>
        </Stack>
      </Card>

      <ListToolbar
        listKey="hr-inbox.list"
        columns={columns}
        state={viewState}
        onStateChange={onViewStateChange}
        rows={rows as unknown as Record<string, unknown>[]}
        loading={loading}
        onRefresh={handleRefresh}
      />

      {error ? (
        <FriendlyError error={error} onRetry={loadPage} />
      ) : loading && rows.length === 0 ? (
        <Card sx={{ p: 2 }}>
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} variant="rounded" height={56} sx={{ mb: 1 }} />
          ))}
        </Card>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            illustration={anyFilterActive ? "search" : "empty-mailbox"}
            title={total === 0 && !anyFilterActive ? t("inbox.empty.none") : t("inbox.empty.filtered")}
            hint={total === 0 && !anyFilterActive ? t("inbox.empty.none_hint") : undefined}
            action={
              anyFilterActive ? (
                <Button variant="outlined" onClick={handleRefresh}>{t("inbox.empty.clear")}</Button>
              ) : undefined
            }
          />
        </Card>
      ) : view === "table" ? (
        <>
          <Card>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    {shown.map((c) => (
                      <TableCell key={c.key}>{c.label}</TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.id} hover>
                      {shown.map((c) => (
                        <TableCell key={c.key}>{tableCell(row, c.key)}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Card>
          {pager}
        </>
      ) : (
        <Grid container spacing={2} alignItems="flex-start">
          <Grid size={{ xs: 12, md: 4, lg: 3.5 }}>
            <Card sx={{ p: 1.25, maxHeight: { md: "calc(100vh - 220px)" }, overflowY: "auto" }}>{listPane}</Card>
            {pager}
          </Grid>
          <Grid size={{ xs: 12, md: 8, lg: 5 }}>
            <Card sx={{ p: 2.25 }}>{selected ? <InboxThreadPane email={selected} /> : <EmptyState compact illustration="mailbox" title={t("inbox.pick")} />}</Card>
          </Grid>
          <Grid size={{ xs: 12, md: 12, lg: 3.5 }}>
            <Card sx={{ p: 2.25 }}>
              {selected ? (
                <InboxCandidatePane email={selected} onAssigned={() => setRefreshKey((k) => k + 1)} />
              ) : (
                <Typography sx={{ color: f.muted }}>{t("inbox.pick")}</Typography>
              )}
            </Card>
          </Grid>
        </Grid>
      )}
    </Box>
  );
}
