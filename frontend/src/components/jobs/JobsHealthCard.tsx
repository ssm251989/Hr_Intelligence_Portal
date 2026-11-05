import { useMemo, useState } from "react";
import SearchIcon from "@mui/icons-material/Search";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import Collapse from "@mui/material/Collapse";
import InputAdornment from "@mui/material/InputAdornment";
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

import type { JobHealthRow, JobsHealth } from "../../api/automationApi";
import { useT } from "../../i18n";
import { Emoji, InfoTip } from "../../ui-kit";
import JobHealthChip, { issueText } from "./JobHealthChip";

type ChipFilter = "all" | "no_applicants" | "slow_stage" | "red";
type SortKey = "level" | "title" | "days" | "applicants";
const LEVEL_ORDER = { red: 0, amber: 1, green: 2 } as const;

// Part 18.7: "Jobs need attention" for 100+ jobs -- summary chips (click = filter), then a
// compact, sortable, searchable, paged table (job, issue, days, health, action). The long
// reasons + suggestions live in the health chip's hover. Hidden when every job is fine.
export default function JobsHealthCard({ data, onOpenJob }: { data: JobsHealth | null; onOpenJob: (jobId: string) => void }) {
  const t = useT();
  const [open, setOpen] = useState(true);
  const [chip, setChip] = useState<ChipFilter>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "level", dir: "asc" });
  const [page, setPage] = useState(0);
  const [perPage, setPerPage] = useState(10);

  const rows = useMemo(() => {
    const needing = (data?.jobs ?? []).filter((j) => j.level !== "green");
    const q = query.trim().toLowerCase();
    const days = (j: JobHealthRow) => Math.max(0, ...j.issues.map((i) => i.days));
    const filtered = needing.filter((j) =>
      (chip === "all" || (chip === "red" ? j.level === "red" : j.issues.some((i) => i.kind === chip)))
      && (!q || [j.title, j.department, j.location].some((v) => v?.toLowerCase().includes(q))));
    const cmp: Record<SortKey, (a: JobHealthRow, b: JobHealthRow) => number> = {
      level: (a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level] || days(b) - days(a),
      title: (a, b) => a.title.localeCompare(b.title),
      days: (a, b) => days(a) - days(b),
      applicants: (a, b) => a.applicants_total - b.applicants_total,
    };
    const sorted = [...filtered].sort(cmp[sort.key]);
    return sort.dir === "desc" ? sorted.reverse() : sorted;
  }, [data, chip, query, sort]);

  if (!data || data.summary.need_attention === 0) return null;
  const s = data.summary;
  const chips: { key: ChipFilter; label: string; count: number; color: "default" | "error" | "warning" | "info" }[] = [
    { key: "all", label: t("jobhealth.chip.need_attention", { count: s.need_attention }), count: s.need_attention, color: "warning" },
    { key: "red", label: t("jobhealth.chip.red", { count: s.red }), count: s.red, color: "error" },
    { key: "no_applicants", label: t("jobhealth.chip.no_applicants", { count: s.no_applicants }), count: s.no_applicants, color: "info" },
    { key: "slow_stage", label: t("jobhealth.chip.waiting", { count: s.waiting_too_long }), count: s.jobs_with_waiting, color: "default" },
  ];
  const sortBy = (key: SortKey) => setSort((prev) => ({ key, dir: prev.key === key && prev.dir === "asc" ? "desc" : "asc" }));
  const head = (key: SortKey, label: string, align?: "right") => (
    <TableCell align={align} sortDirection={sort.key === key ? sort.dir : false}>
      <TableSortLabel active={sort.key === key} direction={sort.key === key ? sort.dir : "asc"} onClick={() => sortBy(key)}>{label}</TableSortLabel>
    </TableCell>
  );

  return (
    <Card sx={{ mb: 2 }}>
      <Box sx={{ p: 2, pb: open ? 1 : 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }} justifyContent="space-between">
          <Stack direction="row" spacing={1} alignItems="center">
            <Emoji name="bell" size={22} />
            <Typography sx={{ fontWeight: 800 }}>{t("autom.health.title")}</Typography>
            <InfoTip text={t("autom.health.info")} />
          </Stack>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
            {chips.filter((c) => c.key === "all" || c.count > 0).map((c) => (
              <Chip key={c.key} label={c.label} color={c.color} variant={chip === c.key ? "filled" : "outlined"} clickable
                onClick={() => { setChip(c.key); setPage(0); setOpen(true); }} />
            ))}
            <Button size="small" onClick={() => setOpen((v) => !v)}>{open ? t("autom.health.show_less") : t("jobhealth.show")}</Button>
          </Stack>
        </Stack>
      </Box>
      <Collapse in={open}>
        <Box sx={{ px: 2, pb: 1 }}>
          <TextField size="small" placeholder={t("jobhealth.search")} value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} sx={{ minWidth: 260 }} />
        </Box>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                {head("title", t("jobhealth.col.job"))}
                <TableCell>{t("jobhealth.col.issue")}</TableCell>
                {head("days", t("jobhealth.col.days"), "right")}
                {head("applicants", t("jobhealth.col.applicants"), "right")}
                {head("level", t("jobhealth.col.health"))}
                <TableCell align="right" />
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.slice(page * perPage, page * perPage + perPage).map((j) => (
                <TableRow key={j.job_id} hover>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 700 }}>{j.title}</Typography>
                    <Typography variant="caption">{[j.department, j.location].filter(Boolean).join(" · ")}</Typography>
                  </TableCell>
                  <TableCell>{j.issues.map((i) => <Typography key={i.kind} variant="body2">{issueText(t, i)}</Typography>)}</TableCell>
                  <TableCell align="right">{Math.max(0, ...j.issues.map((i) => i.days))}</TableCell>
                  <TableCell align="right">{t("jobhealth.applicants_cell", { week: j.applicants_7d, total: j.applicants_total })}</TableCell>
                  <TableCell><JobHealthChip row={j} /></TableCell>
                  <TableCell align="right"><Button size="small" variant="outlined" onClick={() => onOpenJob(j.job_id)}>{t("autom.health.open")}</Button></TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && (
                <TableRow><TableCell colSpan={6}><Typography variant="body2" color="text.secondary">{t("jobhealth.none_match")}</Typography></TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
        {rows.length > 10 && (
          <TablePagination component="div" count={rows.length} page={page} rowsPerPage={perPage} rowsPerPageOptions={[10, 25, 50, 100]}
            onPageChange={(_e, p) => setPage(p)} onRowsPerPageChange={(e) => { setPerPage(Number(e.target.value)); setPage(0); }} />
        )}
      </Collapse>
    </Card>
  );
}
