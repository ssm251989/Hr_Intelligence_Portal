import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import IconButton from "@mui/material/IconButton";
import LinearProgress from "@mui/material/LinearProgress";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import { useNavigate, useSearchParams } from "react-router-dom";

import { extractErrorMessage } from "../../api/client";
import { employeesApi, type AgentCard, type EmployeeFilters, type EmployeeList, type EmployeeProfile, type EmployeeRow, type ItTodo } from "../../api/employeesApi";
import { EmployeeApprovalCard, ItTodoCard } from "../../components/employees/EmployeeApprovalCard";
import ListToolbar, { type ListColumn, type ListViewState } from "../../components/ListToolbar";
import { AccountChip, CompanyEmail, EditEmployeeDialog, EmpStatusChip, GiveAssetDialog } from "../../components/employees/EmployeeDialogs";
import { employeeActionsRegistry } from "../../components/employees/registry";
import { useT } from "../../i18n";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import AssignRolesDialog from "../../components/employees/AssignRolesDialog";
import { EmptyState, FriendlyError, PageHeader, UserAvatar } from "../../ui-kit";

// Part 20.1: Employees -- everyone who has finished onboarding. Column chooser, saved views, filters,
// search, Excel export, bulk "resend app invite"; row click opens the profile; "..." has the actions.

const DEFAULT_COLUMNS = ["code", "name", "designation", "department", "manager", "location", "joined", "exp_company", "exp_total", "email", "status", "account", "roles"];

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function EmployeesPage() {
  const t = useT();
  const navigate = useNavigate();
  const [data, setData] = useState<EmployeeList | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<EmployeeFilters>({});
  const [q, setQ] = useState("");
  const [view, setView] = useState<ListViewState>({ columns: DEFAULT_COLUMNS, filters: {} });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // Part 22.4: Assign roles (HR Admin by default: iam.role_assignments.configure)
  const { can } = useMeBootstrap();
  const canRoles = can("iam.role_assignments.configure");
  const [rolesFor, setRolesFor] = useState<string[] | null>(null);
  const [menu, setMenu] = useState<{ anchor: HTMLElement; row: EmployeeRow } | null>(null);
  const [editing, setEditing] = useState<EmployeeProfile | null>(null);
  const [giving, setGiving] = useState<EmployeeRow | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [extra, setExtra] = useState<ReactNode>(null);
  // Part 20.2: the Onboarding agent's approval cards and IT to-dos (?card=<id> from the inbox highlights one)
  const [cards, setCards] = useState<AgentCard[]>([]);
  const [itTodos, setItTodos] = useState<ItTodo[]>([]);
  const [params] = useSearchParams();
  const focusCard = params.get("card");
  const loadCards = useCallback(() => { employeesApi.agentPending().then((r) => { setCards(r.cards); setItTodos(r.it_todos); }).catch(() => undefined); }, []);
  useEffect(loadCards, [loadCards]);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    employeesApi.list({ ...filters, q: q.trim() || undefined }).then(setData).catch(setError).finally(() => setLoading(false));
  }, [filters, q]);
  useEffect(() => {
    const id = window.setTimeout(load, q ? 300 : 0);
    return () => window.clearTimeout(id);
  }, [load, q]);

  const columns: ListColumn[] = useMemo(() => [
    { key: "code", label: t("emp.col.code") }, { key: "name", label: t("emp.col.name") }, { key: "designation", label: t("emp.col.designation") },
    { key: "department", label: t("emp.col.department") }, { key: "manager", label: t("emp.col.manager") }, { key: "location", label: t("emp.col.location") },
    { key: "joined", label: t("emp.col.joined") }, { key: "exp_company", label: t("emp.col.exp_company") }, { key: "exp_total", label: t("emp.col.exp_total") },
    { key: "email", label: t("emp.col.email") }, { key: "phone", label: t("emp.col.phone") }, { key: "type", label: t("emp.col.type") },
    { key: "status", label: t("emp.col.status") }, { key: "account", label: t("emp.col.account") }, { key: "roles", label: t("emp.col.roles") },
  ], [t]);
  const col = (k: string) => view.columns.includes(k);
  const items = data?.items ?? [];
  const exportRows = items.map((r) => ({
    code: r.employee_code, name: r.name, designation: r.designation ?? "", department: r.department ?? "", manager: r.manager ?? "", location: r.location ?? "",
    joined: r.joined_on ?? "", exp_company: r.experience_company, exp_total: r.experience_total, email: r.company_email ?? "", phone: r.phone ?? "",
    type: r.employment_type ? t(`emp.type.${r.employment_type}`) : "", status: t(`emp.status.${r.status}`), account: t(`emp.account.${r.app_account}`), roles: r.roles.join(", "),
  }));
  const EXPORT_KEYS: Record<string, string> = { code: "employee_code", name: "name", designation: "designation", department: "department", manager: "manager",
    location: "location", joined: "joined_on", exp_company: "experience_company", exp_total: "experience_total", email: "company_email", phone: "phone",
    type: "employment_type", status: "status", account: "app_account", roles: "roles" };

  const exportXlsx = async () => {
    const blob = await employeesApi.exportXlsx({ ...filters, q: q.trim() || undefined }, view.columns.map((c) => EXPORT_KEYS[c]).filter(Boolean));
    if (blob) saveBlob(blob, `employees-${new Date().toISOString().slice(0, 10)}.xlsx`);
  };
  const invite = async (ids: string[]) => {
    try {
      const r = await employeesApi.invites(ids);
      const failed = r.results.filter((x) => x.error || (x.email_status ?? "").startsWith("failed"));
      setToast(failed.length ? t("emp.invite.some_failed", { n: failed.length, list: failed.map((x) => x.name).join(", ") }) : t("emp.invite.sent", { n: r.results.length }));
      setSelected(new Set());
      load();
    } catch (e) {
      setToast(extractErrorMessage(e, ""));
    }
  };
  const openEdit = async (row: EmployeeRow) => setEditing(await employeesApi.get(row.id));
  const setFilter = (k: keyof EmployeeFilters, v: string) => setFilters((f) => ({ ...f, [k]: v || undefined }));
  const actions = employeeActionsRegistry.items;

  return (
    <Box>
      <PageHeader emoji="id_card" title={t("emp.title")} purpose={t("emp.purpose")} tourKey="employees" />
      {data?.test_mode && <Alert severity="info" sx={{ mb: 2 }} data-testid="emp-test-banner">{t("emp.test_banner")}</Alert>}
      {cards.length > 0 && (
        <Box sx={{ mb: 2 }}>
          <Typography component="h2" sx={{ fontWeight: 800, fontSize: 17, mb: 1 }}>{t("emp.card.section", { n: cards.length })}</Typography>
          <Stack spacing={1.5}>
            {cards.map((c) => <EmployeeApprovalCard key={c.id} card={c} facets={data?.facets ?? null} highlight={c.id === focusCard}
              onChanged={() => { loadCards(); load(); setToast(t("emp.card.done_toast")); }} />)}
          </Stack>
        </Box>
      )}
      {itTodos.length > 0 && (
        <Box sx={{ mb: 2 }}>
          <Typography component="h2" sx={{ fontWeight: 800, fontSize: 17, mb: 1 }}>{t("emp.it.section", { n: itTodos.length })}</Typography>
          <Stack spacing={1}>{itTodos.map((x) => <ItTodoCard key={x.id} todo={x} onChanged={() => { loadCards(); load(); setToast(t("emp.it.done_toast")); }} />)}</Stack>
        </Box>
      )}
      <Card sx={{ p: { xs: 1.5, md: 2 } }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mb: 1.5 }} flexWrap="wrap" useFlexGap>
          <TextField size="small" label={t("emp.search")} value={q} onChange={(e) => setQ(e.target.value)} sx={{ minWidth: 220 }} />
          <TextField size="small" select label={t("emp.col.department")} value={filters.department_id ?? ""} onChange={(e) => setFilter("department_id", e.target.value)} sx={{ minWidth: 160 }}>
            <MenuItem value="">{t("emp.any")}</MenuItem>
            {(data?.facets.departments ?? []).map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
          </TextField>
          <TextField size="small" select label={t("emp.col.location")} value={filters.location_id ?? ""} onChange={(e) => setFilter("location_id", e.target.value)} sx={{ minWidth: 150 }}>
            <MenuItem value="">{t("emp.any")}</MenuItem>
            {(data?.facets.locations ?? []).map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
          </TextField>
          <TextField size="small" select label={t("emp.col.status")} value={filters.status ?? ""} onChange={(e) => setFilter("status", e.target.value)} sx={{ minWidth: 140 }}>
            <MenuItem value="">{t("emp.any")}</MenuItem>
            {(["active", "notice", "exited", "absconded"] as const).map((s) => <MenuItem key={s} value={s}>{t(`emp.status.${s}`)}</MenuItem>)}
          </TextField>
          <TextField size="small" select label={t("emp.col.roles")} value={filters.role ?? ""} onChange={(e) => setFilter("role", e.target.value)} sx={{ minWidth: 140 }}>
            <MenuItem value="">{t("emp.any")}</MenuItem>
            {(data?.facets.roles ?? []).map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
          </TextField>
          <TextField size="small" type="date" label={t("emp.joined_from")} value={filters.joined_from ?? ""} onChange={(e) => setFilter("joined_from", e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField size="small" type="date" label={t("emp.joined_to")} value={filters.joined_to ?? ""} onChange={(e) => setFilter("joined_to", e.target.value)} InputLabelProps={{ shrink: true }} />
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
          <Box sx={{ flex: 1 }}>
            <ListToolbar listKey="employees.list" columns={columns} state={view} onStateChange={setView} rows={exportRows} loading={loading} onRefresh={load}
              selectedCount={selected.size}
              bulkActions={data?.can_edit || canRoles ? (
                <Stack direction="row" spacing={1}>
                  {data?.can_edit && <Button size="small" variant="outlined" onClick={() => invite([...selected])}>{t("emp.invite.bulk", { n: selected.size })}</Button>}
                  {canRoles && <Button size="small" variant="contained" onClick={() => setRolesFor([...selected])}>{t("roles22.button_many", { n: selected.size })}</Button>}
                </Stack>
              ) : undefined} />
          </Box>
          {canRoles && (
            <Button size="small" variant="outlined" disabled={!selected.size} onClick={() => setRolesFor([...selected])}>{t("roles22.button")}</Button>
          )}
          <Button size="small" variant="outlined" onClick={exportXlsx} disabled={!items.length}>{t("emp.export")}</Button>
        </Stack>
        {loading && <LinearProgress sx={{ mb: 1 }} />}
        {error ? <FriendlyError error={error} onRetry={load} compact /> : items.length === 0 && !loading ? (
          <EmptyState illustration="meet-the-team" title={Object.keys(filters).length || q ? t("emp.empty_filtered") : t("emp.empty")} hint={t("emp.empty_hint")} />
        ) : (
          <TableContainer>
            <Table size="small" data-testid="employees-table">
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox">
                    <Checkbox checked={items.length > 0 && selected.size === items.length} indeterminate={selected.size > 0 && selected.size < items.length}
                      onChange={(e) => setSelected(e.target.checked ? new Set(items.map((r) => r.id)) : new Set())} inputProps={{ "aria-label": t("emp.select_all") }} />
                  </TableCell>
                  {columns.filter((c) => col(c.key)).map((c) => <TableCell key={c.key}>{c.label}</TableCell>)}
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((r) => (
                  <TableRow key={r.id} hover sx={{ cursor: "pointer" }} onClick={() => navigate(`/employees/${r.id}`)}>
                    <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                      <Checkbox checked={selected.has(r.id)} onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(r.id); else n.delete(r.id); return n; })}
                        inputProps={{ "aria-label": r.name }} />
                    </TableCell>
                    {col("code") && <TableCell sx={{ whiteSpace: "nowrap", fontWeight: 600 }}>{r.employee_code}</TableCell>}
                    {col("name") && (
                      <TableCell>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <UserAvatar name={r.name} size={28} />
                          <Typography sx={{ fontWeight: 600, fontSize: 14 }}>{r.name}</Typography>
                        </Stack>
                      </TableCell>
                    )}
                    {col("designation") && <TableCell>{r.designation ?? "—"}</TableCell>}
                    {col("department") && <TableCell>{r.department ?? "—"}</TableCell>}
                    {col("manager") && <TableCell>{r.manager ?? "—"}</TableCell>}
                    {col("location") && <TableCell>{r.location ?? "—"}</TableCell>}
                    {col("joined") && <TableCell sx={{ whiteSpace: "nowrap" }}>{r.joined_on ? new Date(`${r.joined_on}T00:00:00`).toLocaleDateString() : "—"}</TableCell>}
                    {col("exp_company") && <TableCell sx={{ whiteSpace: "nowrap" }}>{r.experience_company || "—"}</TableCell>}
                    {col("exp_total") && <TableCell sx={{ whiteSpace: "nowrap" }}>{r.experience_total || "—"}</TableCell>}
                    {col("email") && <TableCell><CompanyEmail email={r.company_email} test={r.company_email_test} /></TableCell>}
                    {col("phone") && <TableCell sx={{ whiteSpace: "nowrap" }}>{r.phone ?? "—"}</TableCell>}
                    {col("type") && <TableCell>{r.employment_type ? t(`emp.type.${r.employment_type}`) : "—"}</TableCell>}
                    {col("status") && <TableCell><EmpStatusChip status={r.status} /></TableCell>}
                    {col("account") && <TableCell><AccountChip account={r.app_account} /></TableCell>}
                    {col("roles") && <TableCell sx={{ fontSize: 13 }}>{r.roles.join(", ") || "—"}</TableCell>}
                    <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                      <IconButton aria-label={t("emp.actions", { name: r.name })} onClick={(e) => setMenu({ anchor: e.currentTarget, row: r })}><MoreVertIcon /></IconButton>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Card>

      <Menu anchorEl={menu?.anchor} open={Boolean(menu)} onClose={() => setMenu(null)}>
        {menu && <MenuItem onClick={() => { navigate(`/employees/${menu.row.id}`); setMenu(null); }}>{t("emp.menu.view")}</MenuItem>}
        {menu && data?.can_edit && <MenuItem onClick={() => { void openEdit(menu.row); setMenu(null); }}>{t("emp.menu.edit")}</MenuItem>}
        {menu && canRoles && <MenuItem onClick={() => { setRolesFor([menu.row.id]); setMenu(null); }}>{t("roles22.button")}</MenuItem>}
        {menu && data?.can_edit && menu.row.status !== "exited" && <MenuItem onClick={() => { setGiving(menu.row); setMenu(null); }}>{t("emp.menu.asset")}</MenuItem>}
        {menu && data?.can_edit && actions.filter((a) => a.visible(menu.row)).map((a) => (
          <MenuItem key={a.key} onClick={() => { const row = menu.row; setMenu(null); setExtra(a.render(row, () => { setExtra(null); load(); }, setToast)); }}>{t(a.labelKey)}</MenuItem>
        ))}
        {menu && data?.can_edit && menu.row.status !== "exited" && menu.row.status !== "absconded" && (
          <MenuItem onClick={() => { const id = menu.row.id; setMenu(null); void invite([id]); }}>{t("emp.menu.invite")}</MenuItem>
        )}
      </Menu>

      <EditEmployeeDialog employee={editing} facets={data?.facets ?? null} people={items} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); setToast(t("emp.saved")); load(); }} />
      <GiveAssetDialog employee={giving} onClose={() => setGiving(null)} onDone={(m) => { setGiving(null); setToast(m); load(); }} />
      {extra}
      {rolesFor && <AssignRolesDialog employeeIds={rolesFor} onClose={() => setRolesFor(null)}
        onDone={(m) => { setRolesFor(null); setToast(m); load(); }} />}
      <Snackbar open={Boolean(toast)} autoHideDuration={6000} onClose={() => setToast(null)} message={toast} anchorOrigin={{ vertical: "bottom", horizontal: "center" }} />
    </Box>
  );
}
