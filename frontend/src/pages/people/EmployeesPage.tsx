import { useEffect, useMemo, useState } from "react";
import { Link as RouterLink, useNavigate, useSearchParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import Grid from "@mui/material/Grid";
import InputAdornment from "@mui/material/InputAdornment";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Pagination from "@mui/material/Pagination";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import SearchIcon from "@mui/icons-material/Search";

import { peopleApi, skillList, type PeopleFilters, type PersonRow } from "../../api/peopleApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import ListToolbar, { type ListColumn, type ListViewState } from "../../components/ListToolbar";
import AddPersonDialog from "../../components/people/AddPersonDialog";
import { EmployeeStatusChip, NoAccess, useFormatDate } from "../../components/people/shared";
import { useT } from "../../i18n";
import { EmptyState, Emoji, FriendlyError, PageHeader, StatTile, UserAvatar } from "../../ui-kit";

const LIST_KEY = "people.employees";
const PAGE_SIZES = [25, 50, 100];
const DEFAULT_COLUMNS = ["name", "designation", "department", "location", "manager_name", "status", "joined_on"];
type StatusTab = "all" | "active" | "pre_hire" | "on_notice" | "left";
const LEFT = ["inactive", "terminated", "rehire_eligible"];

function inTab(row: PersonRow, tab: StatusTab) {
  if (tab === "all") return true;
  if (tab === "left") return LEFT.includes(row.status);
  return row.status === tab;
}

export default function EmployeesPage({ embedded = false }: { embedded?: boolean }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useFormatDate();
  const navigate = useNavigate();
  const { can, loading: bootLoading } = useMeBootstrap();
  const canView = can("core_hr.employee.view");
  const canCreate = can("core_hr.employee.create");
  const [params, setParams] = useSearchParams();

  const [rows, setRows] = useState<PersonRow[]>([]);
  const [filters, setFilters] = useState<PeopleFilters | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [addOpen, setAddOpen] = useState(false);

  const tab = (params.get("tab") as StatusTab) || "all";
  const search = params.get("q") ?? "";
  const department = params.get("department") ?? "";
  const location = params.get("location") ?? "";
  const patch = (next: Record<string, string>) => {
    const p = new URLSearchParams(params);
    Object.entries(next).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
    setParams(p, { replace: true });
    setPage(1);
  };

  const columns: ListColumn[] = useMemo(() => [
    { key: "name", label: t("people.col.name") },
    { key: "employee_code", label: t("people.col.code") },
    { key: "designation", label: t("people.col.designation") },
    { key: "department", label: t("people.col.department") },
    { key: "location", label: t("people.col.location") },
    { key: "manager_name", label: t("people.col.manager") },
    { key: "status", label: t("people.col.status") },
    { key: "joined_on", label: t("people.col.joined") },
    { key: "work_email", label: t("people.col.email") },
    { key: "personal_phone", label: t("people.col.phone") },
  ], [t]);
  const [view, setView] = useState<ListViewState>({ columns: DEFAULT_COLUMNS, filters: {} });

  const load = () => {
    setLoading(true);
    setError(null);
    return Promise.all([peopleApi.list(), peopleApi.filters()])
      .then(([list, flt]) => {
        setRows(list.items);
        setFilters(flt);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    if (canView) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canView]);

  // Saved views carry the filters too.
  useEffect(() => {
    const vf = view.filters as Record<string, string>;
    if (vf && Object.keys(vf).length) patch({ tab: vf.tab ?? "", q: vf.q ?? "", department: vf.department ?? "", location: vf.location ?? "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.filters]);
  const viewState: ListViewState = { ...view, filters: { tab, q: search, department, location } };

  const counts = useMemo(() => ({
    all: rows.length,
    active: rows.filter((r) => r.status === "active").length,
    pre_hire: rows.filter((r) => r.status === "pre_hire").length,
    on_notice: rows.filter((r) => r.status === "on_notice").length,
    left: rows.filter((r) => LEFT.includes(r.status)).length,
  }), [rows]);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (!inTab(r, tab)) return false;
      if (department && r.department_id !== department) return false;
      if (location && r.location_id !== location) return false;
      if (!needle) return true;
      return [r.name, r.employee_code, r.designation, r.department, r.location, r.work_email, skillList(r.skills).join(" ")]
        .filter(Boolean).join(" ").toLowerCase().includes(needle);
    });
  }, [rows, tab, search, department, location]);

  const pageCount = Math.max(1, Math.ceil(visible.length / pageSize));
  const current = Math.min(page, pageCount);
  const paged = visible.slice((current - 1) * pageSize, current * pageSize);
  const shown = columns.filter((c) => view.columns.includes(c.key));
  const allOnPage = paged.length > 0 && paged.every((r) => selected.has(r.id));
  const someOnPage = paged.some((r) => selected.has(r.id));
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const togglePage = () => setSelected((s) => { const n = new Set(s); paged.forEach((r) => (allOnPage ? n.delete(r.id) : n.add(r.id))); return n; });

  const exportRows = (selected.size ? visible.filter((r) => selected.has(r.id)) : visible).map((r) => ({
    ...r, status: t(`people.status.${r.status}`), joined_on: r.joined_on ?? "", skills: skillList(r.skills).join("; "),
  })) as unknown as Record<string, unknown>[];
  const selectedEmails = visible.filter((r) => selected.has(r.id)).map((r) => r.work_email || r.personal_email).filter(Boolean) as string[];

  const bulkActions = (
    <>
      <Button size="small" variant="outlined" disabled={selectedEmails.length === 0} href={`mailto:?bcc=${encodeURIComponent(selectedEmails.join(","))}`} startIcon={<Emoji name="envelope" size={16} />}>
        {t("people.bulk.email", { count: selectedEmails.length })}
      </Button>
      <Button size="small" onClick={() => setSelected(new Set())}>{t("people.bulk.clear")}</Button>
    </>
  );

  const cell = (key: string, r: PersonRow) => {
    switch (key) {
      case "name":
        return (
          <Stack direction="row" spacing={1.25} alignItems="center">
            <UserAvatar name={r.name} src={r.photo_url} size={34} />
            <Box sx={{ minWidth: 0 }}>
              <Link component={RouterLink} to={`/employees/${r.id}`} underline="hover" sx={{ fontWeight: 700, color: f.ink }}>{r.name}</Link>
              <Typography sx={{ fontSize: 12, color: f.muted }}>{r.employee_code}</Typography>
            </Box>
          </Stack>
        );
      case "status":
        return <EmployeeStatusChip status={r.status} />;
      case "joined_on":
        return fmt(r.joined_on);
      case "manager_name":
        return r.manager_id && r.manager_name ? <Link component={RouterLink} to={`/employees/${r.manager_id}`} underline="hover">{r.manager_name}</Link> : "—";
      default: {
        const v = (r as unknown as Record<string, unknown>)[key];
        return v === null || v === undefined || v === "" ? "—" : String(v);
      }
    }
  };

  if (!bootLoading && !canView) {
    return (
      <Box>
        <PageHeader emoji="people" title={t("people.employees.title")} purpose={t("people.employees.purpose")} />
        <NoAccess />
      </Box>
    );
  }

  const hasFilters = tab !== "all" || Boolean(search || department || location);
  return (
    <Box>
      {embedded ? (
        canCreate ? (
          <Stack direction="row" justifyContent="flex-end" sx={{ mb: 2 }}>
            <Button variant="contained" onClick={() => setAddOpen(true)}>{t("people.add.button")}</Button>
          </Stack>
        ) : null
      ) : (
        <PageHeader
          emoji="people"
          title={t("people.employees.title")}
          purpose={t("people.employees.purpose")}
          tourKey="employees"
          primary={canCreate ? <Button variant="contained" onClick={() => setAddOpen(true)}>{t("people.add.button")}</Button> : undefined}
          extra={<Button variant="outlined" component={RouterLink} to="/org-chart" startIcon={<Emoji name="building" size={18} />}>{t("people.employees.org_chart")}</Button>}
        />
      )}

      <Grid container spacing={2} sx={{ mb: 2.5 }}>
        <Grid size={{ xs: 6, md: 3 }}><StatTile emoji="people" tone="brand" value={counts.all} label={t("people.stat.total", { count: counts.all })} loading={loading} /></Grid>
        <Grid size={{ xs: 6, md: 3 }}><StatTile emoji="check" tone="ok" value={counts.active} label={t("people.stat.active", { count: counts.active })} loading={loading} /></Grid>
        <Grid size={{ xs: 6, md: 3 }}><StatTile emoji="waving_hand" tone="sky" value={counts.pre_hire} label={t("people.stat.joining", { count: counts.pre_hire })} loading={loading} /></Grid>
        <Grid size={{ xs: 6, md: 3 }}><StatTile emoji="hourglass" tone="sun" value={counts.on_notice} label={t("people.stat.notice", { count: counts.on_notice })} loading={loading} /></Grid>
      </Grid>

      <Card>
        <CardContent sx={{ p: { xs: 1.5, sm: 2.5 } }}>
          <Stack direction={{ xs: "column", lg: "row" }} spacing={1.5} alignItems={{ lg: "center" }} justifyContent="space-between" sx={{ mb: 1.5 }}>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap role="group" aria-label={t("people.tabs_label")}>
              {(["all", "active", "pre_hire", "on_notice", "left"] as StatusTab[]).map((k) => (
                <Button key={k} size="small" variant={tab === k ? "contained" : "outlined"} onClick={() => patch({ tab: k === "all" ? "" : k })} aria-pressed={tab === k} sx={{ borderRadius: 999 }}>
                  {t(`people.tab.${k}`, { count: counts[k] })}
                </Button>
              ))}
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} useFlexGap flexWrap="wrap">
              <TextField size="small" placeholder={t("people.search_placeholder")} value={search} onChange={(e) => patch({ q: e.target.value })}
                slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }, htmlInput: { "aria-label": t("people.search_label") } }}
                sx={{ minWidth: 260 }} />
              <TextField select size="small" label={t("people.field.department")} value={department} onChange={(e) => patch({ department: e.target.value })} sx={{ minWidth: 180 }}>
                <MenuItem value="">{t("people.filter.all_departments")}</MenuItem>
                {(filters?.departments ?? []).filter((d) => d.count > 0).map((d) => <MenuItem key={d.id} value={d.id}>{t("people.filter.option", { name: d.name, count: d.count })}</MenuItem>)}
              </TextField>
              <TextField select size="small" label={t("people.field.location")} value={location} onChange={(e) => patch({ location: e.target.value })} sx={{ minWidth: 180 }}>
                <MenuItem value="">{t("people.filter.all_locations")}</MenuItem>
                {(filters?.locations ?? []).filter((l) => l.count > 0).map((l) => <MenuItem key={l.id} value={l.id}>{t("people.filter.option", { name: l.name, count: l.count })}</MenuItem>)}
              </TextField>
            </Stack>
          </Stack>

          <ListToolbar listKey={LIST_KEY} columns={columns} state={viewState} onStateChange={setView} rows={exportRows} loading={loading}
            onRefresh={load} selectedCount={selected.size} bulkActions={bulkActions} />

          {error != null ? (
            <FriendlyError error={error} what={t("people.employees.load_failed")} onRetry={load} />
          ) : loading && rows.length === 0 ? (
            <Stack spacing={1}>{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} variant="rounded" height={48} />)}</Stack>
          ) : visible.length === 0 ? (
            rows.length === 0 ? (
              <EmptyState illustration="meet-the-team" title={t("people.employees.empty")}
                action={canCreate ? <Button variant="contained" onClick={() => setAddOpen(true)}>{t("people.employees.empty_action")}</Button> : undefined} />
            ) : (
              <EmptyState compact illustration="people-search" title={t("people.employees.empty_filtered")}
                action={hasFilters ? <Button variant="outlined" onClick={() => patch({ tab: "", q: "", department: "", location: "" })}>{t("people.clear_filters")}</Button> : undefined} />
            )
          ) : (
            <>
              <TableContainer sx={{ border: `1px solid ${f.line}`, borderRadius: "12px" }}>
                <Table size="small" aria-label={t("people.employees.table")}>
                  <TableHead>
                    <TableRow>
                      <TableCell padding="checkbox">
                        <Checkbox indeterminate={someOnPage && !allOnPage} checked={allOnPage} onChange={togglePage} slotProps={{ input: { "aria-label": t("people.select_page") } }} />
                      </TableCell>
                      {shown.map((c) => <TableCell key={c.key} sx={{ whiteSpace: "nowrap" }}>{c.label}</TableCell>)}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {paged.map((r) => (
                      <TableRow key={r.id} hover selected={selected.has(r.id)} sx={{ cursor: "pointer" }}
                        onClick={(e) => { if (!(e.target as HTMLElement).closest("a,button,input")) navigate(`/employees/${r.id}`); }}>
                        <TableCell padding="checkbox">
                          <Checkbox checked={selected.has(r.id)} onChange={() => toggle(r.id)} slotProps={{ input: { "aria-label": t("people.select_one", { name: r.name }) } }} />
                        </TableCell>
                        {shown.map((c) => <TableCell key={c.key} sx={{ whiteSpace: c.key === "name" ? "normal" : "nowrap" }}>{cell(c.key, r)}</TableCell>)}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
              <Stack direction="row" justifyContent="space-between" alignItems="center" mt={2} flexWrap="wrap" gap={1}>
                <Typography variant="body2" sx={{ color: f.muted }}>
                  {t("people.showing", { from: (current - 1) * pageSize + 1, to: Math.min(current * pageSize, visible.length), count: visible.length })}
                </Typography>
                <Stack direction="row" spacing={2} alignItems="center">
                  <TextField select size="small" label={t("people.rows_per_page")} value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }} sx={{ minWidth: 130 }}>
                    {PAGE_SIZES.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
                  </TextField>
                  <Pagination count={pageCount} page={current} onChange={(_e, v) => setPage(v)} size="small" color="primary" />
                </Stack>
              </Stack>
            </>
          )}
        </CardContent>
      </Card>

      <AddPersonDialog open={addOpen} onClose={() => setAddOpen(false)} onCreated={(id) => { setAddOpen(false); navigate(`/employees/${id}`); }} />
    </Box>
  );
}
