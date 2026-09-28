import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import SearchIcon from "@mui/icons-material/Search";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import InputAdornment from "@mui/material/InputAdornment";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import TableSortLabel from "@mui/material/TableSortLabel";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { http, jobsApi } from "../../api/client";
import type { JobRoleRead } from "../../api/types";
import { useT } from "../../i18n";
import { downloadCsv } from "../../utils/csv";
import StatusChip from "../StatusChip";

export type Stage = "salary" | "bgv" | "offers";
export interface StageRow {
  application_id: string; candidate_id: string; name: string | null; email: string | null; job_id: string; job: string;
  department: string | null; location: string | null; status: string; days_in_stage: number | null; updated_at: string | null;
  documents?: number; documents_ok?: number; offer_signed?: boolean; joining_date?: string | null; offer_expires?: string | null;
  expected_salary?: number | null; approved_salary?: number | null; salary_state?: string | null;
  // Part 18.14 salary rows
  current_ctc?: number | null; hike_pct?: number | null; band_min?: number | null; band_max?: number | null; budget_after?: number | null;
  budget_configured?: boolean; reasons?: { code: string; [k: string]: unknown }[]; salary_status?: string; counter?: number | null; form_open?: boolean;
}
interface StagePage { total: number; statuses: string[]; status_counts: Record<string, number>; departments: string[]; items: StageRow[] }
export type SortKey = "name" | "job" | "days" | "status" | "hike";

// Part 18.11: every candidate at this stage, across ALL jobs, in one table -- job is a
// column and a filter; search, status chips (with counts), sorting, paging up to 500 rows,
// select + bulk actions, export (all matching rows, or just the selected ones).
export default function StageTable({ stage, onOpen, bulkActions, refreshSignal = 0, extraColumns, rowTone }: {
  stage: Stage;
  onOpen: (row: StageRow) => void;
  bulkActions?: (selected: StageRow[], clear: () => void) => ReactNode;
  refreshSignal?: number;
  extraColumns?: { key: string; label: string; render: (r: StageRow) => ReactNode; sortKey?: SortKey }[];
  /** Part 18.14: tint rows that need attention */
  rowTone?: (r: StageRow) => string | undefined;
}) {
  const t = useT();
  const [jobs, setJobs] = useState<JobRoleRead[]>([]);
  const [data, setData] = useState<StagePage | null>(null);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState({ search: "", job: "", department: "", status: "" });
  const [searchInput, setSearchInput] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "days", dir: "desc" });
  const [page, setPage] = useState(0);
  const [perPage, setPerPage] = useState(50);
  const [selected, setSelected] = useState<Map<string, StageRow>>(new Map());

  useEffect(() => { jobsApi.list().then(setJobs).catch(() => setJobs([])); }, []);
  useEffect(() => { const h = setTimeout(() => setQ((v) => ({ ...v, search: searchInput.trim() })), 350); return () => clearTimeout(h); }, [searchInput]);
  useEffect(() => { setPage(0); }, [q, sort, perPage]);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    if (q.search) p.set("search", q.search);
    if (q.job) p.set("job_role_id", q.job);
    if (q.department) p.set("department", q.department);
    if (q.status) p.set("status", q.status);
    return p;
  }, [q]);

  useEffect(() => {
    let alive = true;
    const p = new URLSearchParams(params);
    p.set("page", String(page + 1));
    p.set("page_size", String(perPage));
    p.set("sort", sort.key);
    p.set("dir", sort.dir);
    setLoading(true);
    http.get<StagePage>(`/api/v1/ui/stage-table/${stage}?${p}`).then((r) => { if (alive) setData(r); }).catch(() => { if (alive) setData(null); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [stage, params, page, perPage, sort, refreshSignal]);

  const rows = data?.items ?? [];
  const exportRows = (list: StageRow[]) => downloadCsv(`${stage}-candidates.csv`,
    [t("stage.col.name"), "Email", t("stage.col.job"), t("stage.col.department"), t("stage.col.status"), t("stage.col.days")],
    list.map((r) => [r.name, r.email, r.job, r.department, r.status, r.days_in_stage]));
  const exportAll = async () => {
    const blob = await http.fetchBlob(`/api/v1/ui/stage-table/${stage}/export?${params}`);
    if (!blob) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${stage}-candidates.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const toggle = (r: StageRow) => setSelected((prev) => { const n = new Map(prev); if (n.has(r.application_id)) n.delete(r.application_id); else n.set(r.application_id, r); return n; });
  const allOnPage = rows.length > 0 && rows.every((r) => selected.has(r.application_id));
  const head = (key: SortKey, label: string) => (
    <TableCell sortDirection={sort.key === key ? sort.dir : false}>
      <TableSortLabel active={sort.key === key} direction={sort.key === key ? sort.dir : "asc"}
        onClick={() => setSort((s) => ({ key, dir: s.key === key && s.dir === "desc" ? "asc" : "desc" }))}>{label}</TableSortLabel>
    </TableCell>
  );

  return (
    <Card sx={{ mb: 3 }}>
      <Box sx={{ p: 2, pb: 1 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }} flexWrap="wrap" useFlexGap>
          <TextField size="small" placeholder={t("stage.search")} value={searchInput} onChange={(e) => setSearchInput(e.target.value)} sx={{ minWidth: 240 }}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
          <TextField select size="small" label={t("stage.col.job")} value={q.job} onChange={(e) => setQ((v) => ({ ...v, job: e.target.value }))} sx={{ minWidth: 200 }}>
            <MenuItem value="">{t("stage.all_jobs")}</MenuItem>
            {jobs.map((j) => <MenuItem key={j.id} value={j.id}>{j.title}</MenuItem>)}
          </TextField>
          {(data?.departments.length ?? 0) > 0 && (
            <TextField select size="small" label={t("stage.col.department")} value={q.department} onChange={(e) => setQ((v) => ({ ...v, department: e.target.value }))} sx={{ minWidth: 170 }}>
              <MenuItem value="">{t("stage.all_departments")}</MenuItem>
              {data!.departments.map((d) => <MenuItem key={d} value={d}>{d}</MenuItem>)}
            </TextField>
          )}
          <Box sx={{ flex: 1 }} />
          <Button size="small" startIcon={<DownloadOutlinedIcon />} onClick={exportAll} disabled={!data?.total}>{t("stage.export_all", { count: data?.total ?? 0 })}</Button>
        </Stack>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.5 }}>
          <Chip label={t("stage.all_count", { count: Object.values(data?.status_counts ?? {}).reduce((a, b) => a + b, 0) })} clickable
            color={q.status === "" ? "primary" : "default"} variant={q.status === "" ? "filled" : "outlined"} onClick={() => setQ((v) => ({ ...v, status: "" }))} />
          {(data?.statuses ?? []).map((s) => (
            <Chip key={s} clickable label={`${t(`stage.status.${s}`)} · ${data?.status_counts[s] ?? 0}`}
              color={q.status === s ? "primary" : "default"} variant={q.status === s ? "filled" : "outlined"} onClick={() => setQ((v) => ({ ...v, status: v.status === s ? "" : s }))} />
          ))}
        </Stack>
      </Box>
      {selected.size > 0 && (
        <Stack direction="row" spacing={1} alignItems="center" sx={{ px: 2, py: 1, bgcolor: "action.selected" }}>
          <Typography variant="body2" sx={{ fontWeight: 700 }}>{t("stage.selected", { count: selected.size })}</Typography>
          <Button size="small" startIcon={<DownloadOutlinedIcon />} onClick={() => exportRows(Array.from(selected.values()))}>{t("stage.export_selected")}</Button>
          {bulkActions?.(Array.from(selected.values()), () => setSelected(new Map()))}
          <Button size="small" onClick={() => setSelected(new Map())}>{t("stage.clear")}</Button>
        </Stack>
      )}
      {loading && <LinearProgress sx={{ height: 3, borderRadius: 0 }} />}
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox checked={allOnPage} indeterminate={!allOnPage && rows.some((r) => selected.has(r.application_id))}
                  onChange={() => setSelected((prev) => { const n = new Map(prev); rows.forEach((r) => (allOnPage ? n.delete(r.application_id) : n.set(r.application_id, r))); return n; })} />
              </TableCell>
              {head("name", t("stage.col.name"))}
              {head("job", t("stage.col.job"))}
              <TableCell>{t("stage.col.department")}</TableCell>
              {head("status", t("stage.col.status"))}
              {(extraColumns ?? []).map((c) => (c.sortKey ? <Fragment key={c.key}>{head(c.sortKey, c.label)}</Fragment> : <TableCell key={c.key}>{c.label}</TableCell>))}
              {head("days", t("stage.col.days"))}
              <TableCell align="right" />
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.application_id} hover selected={selected.has(r.application_id)} sx={{ cursor: "pointer", ...(rowTone?.(r) ? { bgcolor: rowTone(r) } : {}) }} onClick={() => onOpen(r)}>
                <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                  <Checkbox checked={selected.has(r.application_id)} onChange={() => toggle(r)} />
                </TableCell>
                <TableCell>
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>{r.name || "—"}</Typography>
                  <Typography variant="caption">{r.email}</Typography>
                </TableCell>
                <TableCell>{r.job}</TableCell>
                <TableCell>{r.department || "—"}</TableCell>
                <TableCell><StatusChip status={r.status} /></TableCell>
                {(extraColumns ?? []).map((c) => <TableCell key={c.key}>{c.render(r)}</TableCell>)}
                <TableCell>{r.days_in_stage ?? "—"}</TableCell>
                <TableCell align="right"><Button size="small" onClick={(e) => { e.stopPropagation(); onOpen(r); }}>{t("stage.open")}</Button></TableCell>
              </TableRow>
            ))}
            {!loading && rows.length === 0 && (
              <TableRow><TableCell colSpan={7 + (extraColumns?.length ?? 0)}><Typography variant="body2" color="text.secondary">{t("stage.empty")}</Typography></TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
      <TablePagination component="div" count={data?.total ?? 0} page={page} rowsPerPage={perPage} rowsPerPageOptions={[25, 50, 100, 250, 500]}
        onPageChange={(_e, p) => setPage(p)} onRowsPerPageChange={(e) => setPerPage(Number(e.target.value))} />
    </Card>
  );
}
