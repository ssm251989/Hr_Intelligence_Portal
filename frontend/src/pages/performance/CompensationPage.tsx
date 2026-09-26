import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { performanceExtraApi, type CompCycle, type CompGrid as Grid, type CompRow } from "../../api/performanceExtra";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import BudgetMeter from "../../components/performance/BudgetMeter";
import CompGrid from "../../components/performance/CompGrid";
import { NoAccess, useDateFormat, useFresh, useMoneyFormat } from "../../components/performance/shared";
import { useT } from "../../i18n";
import { Cell, EmptyState, Emoji, FriendlyError, PageGrid, PageHeader, StatTile, explainError } from "../../ui-kit";

// Part 15.6 (spec L F7): pay review worksheet as a spreadsheet grid + budget meter.
// Salary is sensitive: the page needs compensation.planning.view, bands need
// view_sensitive, and field security can hide any figure (shown with a lock).

export default function CompensationPage() {
  const t = useT();
  const f = useFresh();
  const date = useDateFormat();
  const { can, loading: bootLoading } = useMeBootstrap();
  const allowed = can("compensation.planning.view");
  const canEdit = can("compensation.planning.edit");
  const canCreate = can("compensation.planning.create");
  const canExport = can("compensation.planning.export");

  const [cycles, setCycles] = useState<CompCycle[] | null>(null);
  const [cycleId, setCycleId] = useState("");
  const [department, setDepartment] = useState("");
  const [grid, setGrid] = useState<Grid | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);
  const [justify, setJustify] = useState<{ row: CompRow; text: string } | null>(null);
  const money = useMoneyFormat(grid?.cycle.currency ?? cycles?.find((c) => c.id === cycleId)?.currency);

  useEffect(() => {
    if (!allowed) return;
    performanceExtraApi
      .compCycles()
      .then((list) => {
        setCycles(list);
        const open = list.find((c) => c.status !== "closed") ?? list[0];
        if (open) setCycleId(open.id);
      })
      .catch(setError);
  }, [allowed]);

  const loadGrid = useCallback(() => {
    if (!cycleId) return;
    setLoading(true);
    setError(null);
    performanceExtraApi
      .compGrid(cycleId, department || undefined)
      .then(setGrid)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [cycleId, department]);

  useEffect(loadGrid, [loadGrid]);

  const showError = (err: unknown) => {
    const e = explainError(err);
    setToast({ ok: false, text: `${e.what} ${e.fix}` });
  };

  const change = async (row: CompRow, patch: { merit_pct?: number; bonus_amount?: number }) => {
    setBusyId(row.id);
    try {
      await performanceExtraApi.updateProposal(row.id, patch);
      loadGrid(); // budget + guideline flags are worked out by the server
    } catch (err) {
      showError(err);
      loadGrid();
    } finally {
      setBusyId(null);
    }
  };

  const submit = async (row: CompRow, reason?: string) => {
    if (row.outside_guideline && !row.justification && !reason) {
      setJustify({ row, text: "" });
      return;
    }
    setBusyId(row.id);
    try {
      if (reason) await performanceExtraApi.updateProposal(row.id, { justification: reason });
      await performanceExtraApi.submitProposal(row.id);
      setToast({ ok: true, text: t("compensation.submitted", { name: row.name }) });
      loadGrid();
    } catch (err) {
      showError(err);
    } finally {
      setBusyId(null);
    }
  };

  const addPeople = async () => {
    if (!grid || !grid.not_in_worksheet.length) return;
    setBuilding(true);
    try {
      const added = await performanceExtraApi.buildWorksheet(grid.cycle.id, grid.not_in_worksheet);
      setToast({ ok: true, text: t("compensation.added", { count: added.length }) });
      loadGrid();
    } catch (err) {
      showError(err);
    } finally {
      setBuilding(false);
    }
  };

  const exportCsv = async () => {
    if (!grid) return;
    const blob = await performanceExtraApi.exportCycle(grid.cycle.id).catch(() => null);
    if (!blob) {
      setToast({ ok: false, text: t("compensation.export_failed") });
      return;
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${grid.cycle.name.replace(/[^\w-]+/g, "_")}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (bootLoading) return null;
  const toAdd = grid?.not_in_worksheet.length ?? 0;
  const header = (
    <PageHeader
      emoji="money"
      title={t("compensation.title")}
      purpose={t("compensation.purpose")}
      tourKey="compensation"
      extra={canExport && grid ? <Button variant="outlined" onClick={exportCsv}>{t("compensation.export")}</Button> : undefined}
      primary={canCreate && grid && toAdd > 0 ? (
        <Button variant="contained" onClick={addPeople} disabled={building} startIcon={<Emoji name="people" size={16} />}>
          {building ? t("compensation.adding") : t("compensation.add_people", { count: toAdd })}
        </Button>
      ) : undefined}
    />
  );
  if (!allowed) {
    return (
      <Box>
        {header}
        <NoAccess what={t("compensation.title")} />
      </Box>
    );
  }

  const rows = grid?.rows ?? [];
  const outside = rows.filter((r) => r.outside_guideline).length;
  const drafts = rows.filter((r) => r.status === "draft").length;

  return (
    <Box>
      {header}
      {error && !grid ? (
        <FriendlyError error={error} onRetry={loadGrid} />
      ) : cycles && cycles.length === 0 ? (
        <Card>
          <EmptyState illustration="data-reports" title={t("compensation.no_cycles")} hint={t("compensation.no_cycles_hint")} />
        </Card>
      ) : (
        <>
          <Card sx={{ p: 2, mb: 2.25 }}>
            <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ xs: "stretch", md: "center" }}>
              <TextField select size="small" label={t("compensation.cycle")} value={cycleId} onChange={(e) => { setCycleId(e.target.value); setDepartment(""); }} sx={{ minWidth: 260 }}
                helperText={t("compensation.cycle_hint")}>
                {(cycles ?? []).map((c) => (
                  <MenuItem key={c.id} value={c.id}>{c.name} · {t("compensation.effective", { date: date(c.effective_date) })}</MenuItem>
                ))}
              </TextField>
              <TextField select size="small" label={t("compensation.department")} value={department} onChange={(e) => setDepartment(e.target.value)} sx={{ minWidth: 220 }}
                helperText={t("compensation.department_hint")}>
                <MenuItem value="">{t("compensation.all_departments")}</MenuItem>
                {(grid?.departments ?? []).map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
              </TextField>
              <Box sx={{ flex: 1 }} />
              {!canEdit && <Typography sx={{ color: f.muted, fontSize: 13 }}><Emoji name="lock" size={14} /> {t("compensation.read_only")}</Typography>}
            </Stack>
          </Card>

          {grid && (
            <PageGrid sx={{ mb: 2.25 }}>
              <Cell span={{ xs: 12, md: 4 }}>
                <BudgetMeter title={t("compensation.budget.merit")} tip={t("compensation.budget.merit_tip")} used={grid.budget.merit_used} pool={grid.budget.merit_pool} money={money} />
              </Cell>
              <Cell span={{ xs: 12, md: 4 }}>
                <BudgetMeter title={t("compensation.budget.bonus")} tip={t("compensation.budget.bonus_tip")} used={grid.budget.bonus_used} pool={grid.budget.bonus_pool} money={money} />
              </Cell>
              <Cell span={{ xs: 6, md: 2 }}><StatTile emoji="people" value={rows.length} label={t("compensation.stat.people", { count: rows.length })} /></Cell>
              <Cell span={{ xs: 6, md: 2 }}><StatTile emoji="warning" value={outside} label={t("compensation.stat.outside", { count: outside })} tone={outside ? "sun" : "ok"} trend={t("compensation.stat.drafts", { count: drafts })} trendDirection="flat" /></Cell>
            </PageGrid>
          )}

          <Card sx={{ p: { xs: 1, md: 2 } }} data-tour="comp-grid">
            {loading && !grid ? (
              <Typography sx={{ p: 2, color: f.muted }}>{t("performance.loading")}</Typography>
            ) : rows.length === 0 ? (
              <EmptyState
                illustration="empty"
                title={t("compensation.empty")}
                hint={canCreate ? t("compensation.empty_hint") : t("compensation.empty_hint_view")}
                action={canCreate && toAdd > 0 ? <Button variant="contained" onClick={addPeople} disabled={building}>{t("compensation.add_people", { count: toAdd })}</Button> : undefined}
              />
            ) : (
              <>
                <Typography sx={{ color: f.muted, fontSize: 13, px: 1, pb: 1 }}>{canEdit ? t("compensation.grid.howto") : t("compensation.read_only")}</Typography>
                <CompGrid rows={rows} money={money} canEdit={canEdit} canSeeBands={Boolean(grid?.can_see_bands)} onChange={change} onSubmit={(r) => submit(r)} busyId={busyId} />
              </>
            )}
          </Card>
        </>
      )}

      <Dialog open={Boolean(justify)} onClose={() => setJustify(null)} fullWidth maxWidth="sm">
        <DialogTitle>{t("compensation.justify.title")}</DialogTitle>
        <DialogContent>
          <Typography sx={{ mb: 2 }}>{t("compensation.justify.body", { name: justify?.row.name ?? "" })}</Typography>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={3}
            label={t("compensation.justify.label")}
            placeholder={t("compensation.justify.placeholder")}
            helperText={t("compensation.justify.hint")}
            value={justify?.text ?? ""}
            onChange={(e) => setJustify((j) => (j ? { ...j, text: e.target.value } : j))}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setJustify(null)}>{t("action.cancel")}</Button>
          <Button
            variant="contained"
            disabled={!justify?.text.trim()}
            onClick={() => {
              if (!justify) return;
              const { row, text } = justify;
              setJustify(null);
              void submit(row, text.trim());
            }}
          >
            {t("compensation.grid.submit")}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar open={Boolean(toast)} autoHideDuration={6000} onClose={() => setToast(null)} anchorOrigin={{ vertical: "bottom", horizontal: "center" }}>
        <Alert severity={toast?.ok ? "success" : "error"} onClose={() => setToast(null)}>{toast?.text}</Alert>
      </Snackbar>
    </Box>
  );
}
