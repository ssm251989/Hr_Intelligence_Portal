import { useEffect, useState } from "react";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import SearchIcon from "@mui/icons-material/Search";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import FormControl from "@mui/material/FormControl";
import InputAdornment from "@mui/material/InputAdornment";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Pagination from "@mui/material/Pagination";
import Paper from "@mui/material/Paper";
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
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useNavigate } from "react-router-dom";

import { extractErrorMessage, hrInboxApi } from "../api/client";
import type { HrInboundEmailRead } from "../api/types";
import RefreshButton from "../components/RefreshButton";
import { downloadCsv } from "../utils/csv";

const ROWS_PER_PAGE_OPTIONS = [10, 20, 30, 40, 50];
const DEFAULT_PAGE_SIZE = 10;
const SEARCH_DEBOUNCE_MS = 300;
const COLUMN_COUNT = 5;

type MatchedFilter = "" | "matched" | "unmatched";

// The "HR Inbox" -- every message the shared HR mailbox has received (matched to a
// candidate or not), same List architecture as the Screening/Shortlisting/Interview
// modules, minus a Dashboard: there's no meaningful trend/stats view for a raw inbox the
// way there is for a pipeline stage, so this is List-only by design.
export default function HrInboxListPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<HrInboundEmailRead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [matchedFilter, setMatchedFilter] = useState<MatchedFilter>("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [refreshKey, setRefreshKey] = useState(0);
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
      })
      .catch((err) => setError(extractErrorMessage(err, "Failed to load the HR Inbox")))
      .finally(() => setLoading(false));
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
        ["From", "To", "Subject", "Received At", "Matched Candidate", "Matched Job"],
        result.map((row) => [
          row.from_address,
          row.to_address,
          row.subject,
          row.received_at,
          row.matched_candidate_name,
          row.matched_job_title,
        ]),
      );
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to export the HR Inbox"));
    }
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4">HR Inbox</Typography>
          <Typography variant="body2" color="text.secondary">
            {total} message{total === 1 ? "" : "s"}
          </Typography>
        </Box>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
          <TextField
            size="small"
            placeholder="Search by sender or subject"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
            sx={{ minWidth: 240 }}
          />
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel id="hr-inbox-matched-filter-label">Match status</InputLabel>
            <Select
              labelId="hr-inbox-matched-filter-label"
              label="Match status"
              value={matchedFilter}
              onChange={(e) => setMatchedFilter(e.target.value as MatchedFilter)}
            >
              <MenuItem value="">All</MenuItem>
              <MenuItem value="matched">Matched</MenuItem>
              <MenuItem value="unmatched">Unmatched</MenuItem>
            </Select>
          </FormControl>
          <Button variant="outlined" startIcon={<DownloadOutlinedIcon />} onClick={handleExportCsv} disabled={total === 0}>
            Export
          </Button>
          <RefreshButton loading={loading} onRefresh={handleRefresh} />
        </Stack>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading ? (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>From</TableCell>
                <TableCell>Subject</TableCell>
                <TableCell>Received</TableCell>
                <TableCell>Matched Candidate</TableCell>
                <TableCell>Matched Job</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: COLUMN_COUNT }).map((__, j) => (
                    <TableCell key={j}>
                      <Skeleton variant="text" />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : rows.length === 0 ? (
        <Typography color="text.secondary">
          {total === 0 && !anyFilterActive ? "No mail received yet." : "No messages match the current filters."}
        </Typography>
      ) : (
        <>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>From</TableCell>
                  <TableCell>Subject</TableCell>
                  <TableCell>Received</TableCell>
                  <TableCell>Matched Candidate</TableCell>
                  <TableCell>Matched Job</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id} hover>
                    <TableCell>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography variant="body2" fontWeight={600} noWrap>
                          {row.from_address}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell sx={{ maxWidth: 260 }}>
                      {row.subject ? (
                        <Tooltip title={row.subject}>
                          <Typography variant="body2" noWrap>
                            {row.subject}
                          </Typography>
                        </Tooltip>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell>{row.received_at ? new Date(row.received_at).toLocaleString() : "—"}</TableCell>
                    <TableCell>
                      {row.matched_candidate_id ? (
                        <Chip
                          label={row.matched_candidate_name || "Matched candidate"}
                          size="small"
                          color="success"
                          variant="outlined"
                          onClick={() =>
                            row.matched_application_id && navigate(`/candidates/${row.matched_application_id}`)
                          }
                          clickable={Boolean(row.matched_application_id)}
                        />
                      ) : (
                        <Chip label="Unmatched" size="small" variant="outlined" />
                      )}
                    </TableCell>
                    <TableCell>{row.matched_job_title || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
            <Typography variant="body2" color="text.secondary">
              Showing {pageStart} to {pageEnd} of {total} messages
            </Typography>
            <Stack direction="row" spacing={2} alignItems="center">
              <FormControl size="small" sx={{ minWidth: 130 }}>
                <InputLabel id="hr-inbox-rows-per-page-label">Rows per page</InputLabel>
                <Select
                  labelId="hr-inbox-rows-per-page-label"
                  label="Rows per page"
                  value={pageSize}
                  onChange={handlePageSizeChange}
                >
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
        </>
      )}
    </Box>
  );
}
