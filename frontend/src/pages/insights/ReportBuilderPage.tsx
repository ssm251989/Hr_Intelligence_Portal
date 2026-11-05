import { useEffect, useMemo, useState } from "react";
import { DndContext, DragOverlay, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from "@dnd-kit/core";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import LinearProgress from "@mui/material/LinearProgress";
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
import { useTheme } from "@mui/material/styles";

import { intelligenceApi, type DatasetField, type DatasetRead, type ReportDefinition, type ReportResult } from "../../api/client";
import { insightsApi } from "../../api/insightsApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { DragGhost, DropZone, FieldPill, ZoneChip, type Zone } from "../../components/insights/BuilderParts";
import { CardLoading, friendly, InsightCard, useLoaded } from "../../components/insights/InsightCard";
import ScheduleReports from "../../components/insights/ScheduleReports";
import { useT, type TFunction } from "../../i18n";
import { Cell, EmptyState, Emoji, FriendlyError, InfoTip, PageGrid, PageHeader, StatusChip } from "../../ui-kit";
import { useReducedMotion } from "../../ui-kit/motion";

// Part 15.6 R1/R2/R4: drag-and-drop report builder. Pick what to report on, drag fields into
// Columns / Filters / Group by (or use each field's + button), watch the live preview, save,
// export (Excel / CSV from the server, PDF through the browser's print), and schedule.

interface Filter { field: string; op: string; value: string }
type Measure = { agg: "count" } | { agg: "sum" | "avg"; field: string };

const OPS_BY_TYPE: Record<string, string[]> = {
  str: ["eq", "ne", "contains", "is_null", "not_null"],
  num: ["eq", "gt", "gte", "lt", "lte", "is_null", "not_null"],
  date: ["eq", "gte", "lte", "is_null", "not_null"],
  bool: ["eq"],
};
const NO_VALUE = new Set(["is_null", "not_null"]);
const PLACEHOLDER: Record<string, string> = { str: "Hyderabad", num: "5", date: "", bool: "" };
const MEASURE_AS = "value";

function dsLabel(t: TFunction, d: DatasetRead) {
  const key = `builder.ds.${d.code}`;
  const tr = t(key);
  return tr !== key ? tr : friendly(d.code, d.label);
}

function formatCell(v: unknown, type: string | undefined, key: string): React.ReactNode {
  if (v === null || v === undefined || v === "") return "—";
  if (key === "status" && typeof v === "string") return <StatusChip status={v} />;
  if (typeof v === "number") return v.toLocaleString();
  if (typeof v === "boolean") return v ? "✓" : "—";
  if (type === "date" && typeof v === "string") {
    const d = new Date(v);
    return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString();
  }
  return String(v);
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

export default function ReportBuilderPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const reduced = useReducedMotion();
  const { can } = useMeBootstrap();
  const [datasets, reloadDatasets] = useLoaded(intelligenceApi.datasets);
  const [saved, reloadSaved] = useLoaded(intelligenceApi.reports);

  const [code, setCode] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [filters, setFilters] = useState<Filter[]>([]);
  const [group, setGroup] = useState<string[]>([]);
  const [measure, setMeasure] = useState<Measure>({ agg: "count" });
  const [result, setResult] = useState<ReportResult | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<unknown>(null);
  const [dragging, setDragging] = useState<DatasetField | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [name, setName] = useState("");
  const [savedId, setSavedId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);

  const list = datasets.state === "ok" ? datasets.data : [];
  const dataset = list.find((d) => d.code === code) ?? null;
  // Record ids are internal -- people pick readable fields only.
  const fields = useMemo(() => (dataset?.fields ?? []).filter((x) => x.type !== "id"), [dataset]);
  const byKey = useMemo(() => Object.fromEntries((dataset?.fields ?? []).map((x) => [x.key, x])), [dataset]);
  const numFields = fields.filter((x) => x.type === "num");

  const pick = (next: string) => {
    const ds = list.find((d) => d.code === next);
    setCode(next);
    setColumns((ds?.fields ?? []).filter((x) => x.type !== "id").slice(0, 6).map((x) => x.key));
    setFilters([]);
    setGroup([]);
    setMeasure({ agg: "count" });
    setSavedId(null);
  };

  useEffect(() => {
    if (!code && list.length) pick(list[0].code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list.length]);

  const definition: ReportDefinition = useMemo(() => {
    const def: ReportDefinition = {
      filters: filters.filter((x) => NO_VALUE.has(x.op) || x.value.trim() !== "").map((x) => {
        const type = byKey[x.field]?.type;
        const value = NO_VALUE.has(x.op) ? undefined : type === "num" ? Number(x.value) : type === "bool" ? x.value === "true" : x.value.trim();
        return { field: x.field, op: x.op, value };
      }),
      limit: 50,
    };
    if (group.length) {
      def.group_by = group;
      def.measures = [measure.agg === "count" ? { field: "*", agg: "count", as: MEASURE_AS } : { field: measure.field, agg: measure.agg, as: MEASURE_AS }];
      def.sort = [{ field: MEASURE_AS, dir: "desc" }];
    } else {
      def.columns = columns;
    }
    return def;
  }, [columns, filters, group, measure, byKey]);

  // Live preview, lightly debounced so typing a filter value doesn't fire a query per key.
  const defKey = JSON.stringify(definition);
  useEffect(() => {
    if (!code || (!group.length && !columns.length)) {
      setResult(null);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      setRunning(true);
      intelligenceApi
        .runReport(code, definition)
        .then((r) => live && (setResult(r), setRunError(null)))
        .catch((e) => live && setRunError(e))
        .finally(() => live && setRunning(false));
    }, 350);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, defKey]);

  const add = (zone: Zone, key: string) => {
    setSavedId(null);
    if (zone === "columns") setColumns((c) => (c.includes(key) ? c : [...c, key]));
    if (zone === "group") setGroup((g) => (g.includes(key) ? g : [...g, key]));
    if (zone === "filters") setFilters((fs) => [...fs, { field: key, op: (OPS_BY_TYPE[byKey[key]?.type] ?? OPS_BY_TYPE.str)[0], value: "" }]);
  };

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor));
  const onStart = (e: DragStartEvent) => setDragging((e.active.data.current as { field?: DatasetField } | undefined)?.field ?? null);
  const onEnd = (e: DragEndEvent) => {
    const field = (e.active.data.current as { field?: DatasetField } | undefined)?.field;
    if (field && e.over) add(e.over.id as Zone, field.key);
    setDragging(null);
  };
  const labelOf = (key: string) => (key === MEASURE_AS ? measureLabel() : byKey[key]?.label ?? friendly(key));
  const measureLabel = () => (measure.agg === "count" ? t("builder.measure.count") : t(`builder.measure.${measure.agg}_of`, { name: byKey[measure.field]?.label ?? "" }));

  const doSave = () => {
    if (!name.trim() || !code) return;
    setBusy(true);
    intelligenceApi
      .saveReport({ name: name.trim(), dataset: code, definition: { ...definition, limit: undefined } })
      .then((r) => {
        setSavedId(r.id);
        setSaveOpen(false);
        setToast(t("builder.saved", { name: name.trim() }));
        reloadSaved();
      })
      .catch(setActionError)
      .finally(() => setBusy(false));
  };

  const doExport = (format: "csv" | "xlsx", id = savedId, fileName = name.trim()) => {
    if (!id) return;
    setBusy(true);
    setActionError(null);
    insightsApi
      .exportReport(id, format)
      .then((blob) => {
        if (!blob) throw new Error("export failed");
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${fileName || "report"}.${format}`;
        a.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 2000);
      })
      .catch(setActionError)
      .finally(() => setBusy(false));
  };

  // PDF = the browser's own "Save as PDF" from a clean printable page of the preview.
  const doPrint = () => {
    if (!result) return;
    const w = window.open("", "_blank", "width=900,height=700");
    if (!w) return;
    const head = result.columns.map((c) => `<th>${escapeHtml(labelOf(c))}</th>`).join("");
    const body = result.rows.map((r) => `<tr>${result.columns.map((c) => `<td>${escapeHtml(r[c] === null || r[c] === undefined ? "—" : String(r[c]))}</td>`).join("")}</tr>`).join("");
    const title = escapeHtml(name.trim() || (dataset ? dsLabel(t, dataset) : ""));
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><style>body{font-family:system-ui,sans-serif;margin:24px;color:#15211D}h1{font-size:18px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #E2E8E5;padding:6px 8px;text-align:left}th{background:#F4F6F5}</style></head><body><h1>${title}</h1><p>${escapeHtml(t("builder.rows", { count: result.total }))} · ${escapeHtml(new Date().toLocaleString())}</p><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></body></html>`);
    w.document.close();
    w.focus();
    w.print();
  };

  const canCreate = can("analytics.report.create");
  const canExport = can("analytics.report.export");

  return (
    <Box>
      <PageHeader
        emoji="bar_chart"
        title={t("builder.title")}
        purpose={t("builder.purpose")}
        tourKey="report-builder"
        primary={
          <Button variant="contained" disabled={!canCreate || !result} onClick={() => { setActionError(null); setName((n) => n || (dataset ? dsLabel(t, dataset) : "")); setSaveOpen(true); }}
            startIcon={<Emoji name="check" size={16} />}>
            {t("builder.save")}
          </Button>
        }
        extra={
          <>
            <Button variant="outlined" disabled={!savedId || !canExport || busy} onClick={() => doExport("xlsx")}>{t("builder.export.excel")}</Button>
            <Button variant="outlined" disabled={!savedId || !canExport || busy} onClick={() => doExport("csv")}>{t("builder.export.csv")}</Button>
            <Button variant="outlined" disabled={!result} onClick={doPrint}>{t("builder.export.pdf")}</Button>
          </>
        }
      />

      {datasets.state === "loading" && <CardLoading height={320} />}
      {datasets.state === "error" && <FriendlyError error={datasets.error} onRetry={reloadDatasets} />}
      {datasets.state === "forbidden" && <FriendlyError what={t("builder.no_access")} fix={t("builder.no_access_fix")} actionLabel={t("action.go_home")} actionTo="/" />}
      {datasets.state === "ok" && list.length === 0 && <EmptyState illustration="data-reports" title={t("builder.no_datasets")} />}

      {datasets.state === "ok" && list.length > 0 && (
        <DndContext sensors={sensors} onDragStart={onStart} onDragEnd={onEnd} onDragCancel={() => setDragging(null)}
          accessibility={{
            screenReaderInstructions: { draggable: t("builder.sr_instructions") },
            announcements: {
              onDragStart: ({ active }) => t("builder.sr_picked", { name: (active.data.current as { field?: DatasetField })?.field?.label ?? "" }),
              onDragOver: ({ over }) => (over ? t("builder.sr_over", { zone: t(`builder.zone.${over.id}`) }) : ""),
              onDragEnd: ({ over }) => (over ? t("builder.sr_dropped", { zone: t(`builder.zone.${over.id}`) }) : t("builder.sr_cancel")),
              onDragCancel: () => t("builder.sr_cancel"),
            },
          }}>
          <PageGrid>
            <Cell span={{ xs: 12, md: 4, xl: 3 }}>
              <InsightCard emoji="clipboard" title={t("builder.step1")} sub={t("builder.step1_sub")} dataTour="builder-fields">
                <TextField select fullWidth label={t("builder.dataset")} value={code} onChange={(e) => pick(e.target.value)} helperText={t("builder.dataset_hint")} sx={{ mb: 2 }}>
                  {list.map((d) => <MenuItem key={d.code} value={d.code}>{dsLabel(t, d)}</MenuItem>)}
                </TextField>
                <Typography sx={{ fontWeight: 700, fontSize: 13, mb: 1 }}>
                  {t("builder.fields", { count: fields.length })}
                  <InfoTip text={t("builder.fields_help")} />
                </Typography>
                <Stack spacing={0.75} sx={{ maxHeight: 520, overflowY: "auto", pr: 0.5 }}>
                  {fields.map((field) => <FieldPill key={field.key} field={field} onAdd={(z) => add(z, field.key)} />)}
                </Stack>
              </InsightCard>
            </Cell>

            <Cell span={{ xs: 12, md: 8, xl: 9 }}>
              <InsightCard emoji="pencil" title={t("builder.step2")} sub={t("builder.step2_sub")}>
                <Stack spacing={1.5}>
                  <DropZone zone="columns" emoji="page" title={t("builder.zone.columns")} hint={group.length ? t("builder.columns_grouped") : t("builder.zone.columns_hint")} empty={!columns.length}>
                    {columns.map((k) => <ZoneChip key={k} label={labelOf(k)} onRemove={() => { setSavedId(null); setColumns((c) => c.filter((x) => x !== k)); }} />)}
                  </DropZone>
                  <DropZone zone="filters" emoji="magnifier" title={t("builder.zone.filters")} hint={t("builder.zone.filters_hint")} empty={!filters.length}>
                    {filters.map((flt, i) => {
                      const type = byKey[flt.field]?.type ?? "str";
                      const update = (patch: Partial<Filter>) => { setSavedId(null); setFilters((fs) => fs.map((x, j) => (j === i ? { ...x, ...patch } : x))); };
                      return (
                        <ZoneChip key={`${flt.field}-${i}`} label={labelOf(flt.field)} onRemove={() => { setSavedId(null); setFilters((fs) => fs.filter((_, j) => j !== i)); }}>
                          <TextField select size="small" variant="standard" value={flt.op} onChange={(e) => update({ op: e.target.value })} aria-label={t("builder.op_label")} sx={{ minWidth: 90 }}>
                            {(OPS_BY_TYPE[type] ?? OPS_BY_TYPE.str).map((op) => <MenuItem key={op} value={op}>{t(`builder.op.${op}`)}</MenuItem>)}
                          </TextField>
                          {!NO_VALUE.has(flt.op) && (type === "bool" ? (
                            <TextField select size="small" variant="standard" value={flt.value} onChange={(e) => update({ value: e.target.value })} aria-label={t("builder.value_label")} sx={{ minWidth: 70 }}>
                              <MenuItem value="true">{t("builder.yes")}</MenuItem>
                              <MenuItem value="false">{t("builder.no")}</MenuItem>
                            </TextField>
                          ) : (
                            <TextField size="small" variant="standard" type={type === "num" ? "number" : type === "date" ? "date" : "text"} value={flt.value}
                              placeholder={PLACEHOLDER[type] ? t("builder.eg", { example: PLACEHOLDER[type] }) : undefined} onChange={(e) => update({ value: e.target.value })}
                              slotProps={{ htmlInput: { "aria-label": t("builder.value_label") } }} sx={{ width: 130 }} />
                          ))}
                        </ZoneChip>
                      );
                    })}
                  </DropZone>
                  <DropZone zone="group" emoji="package" title={t("builder.zone.group")} hint={t("builder.zone.group_hint")} empty={!group.length}>
                    {group.map((k) => <ZoneChip key={k} label={labelOf(k)} onRemove={() => { setSavedId(null); setGroup((g) => g.filter((x) => x !== k)); }} />)}
                  </DropZone>
                  {group.length > 0 && (
                    <TextField select label={t("builder.measure.label")} value={measure.agg === "count" ? "count" : `${measure.agg}:${measure.field}`} sx={{ maxWidth: 360 }}
                      helperText={t("builder.measure.hint")}
                      onChange={(e) => {
                        setSavedId(null);
                        const [agg, field] = e.target.value.split(":");
                        setMeasure(agg === "count" ? { agg: "count" } : { agg: agg as "sum" | "avg", field });
                      }}>
                      <MenuItem value="count">{t("builder.measure.count")}</MenuItem>
                      {numFields.flatMap((nf) => [
                        <MenuItem key={`sum:${nf.key}`} value={`sum:${nf.key}`}>{t("builder.measure.sum_of", { name: nf.label })}</MenuItem>,
                        <MenuItem key={`avg:${nf.key}`} value={`avg:${nf.key}`}>{t("builder.measure.avg_of", { name: nf.label })}</MenuItem>,
                      ])}
                    </TextField>
                  )}
                </Stack>
              </InsightCard>
            </Cell>

            <Cell span={12}>
              <InsightCard emoji="eyes" title={t("builder.preview")} sub={result ? t("builder.rows_preview", { count: result.total, shown: result.rows.length }) : t("builder.preview_sub")} dataTour="builder-preview">
                {running && <LinearProgress sx={{ mb: 1, borderRadius: 2 }} aria-label={t("builder.loading")} />}
                {runError !== null && <FriendlyError error={runError} what={t("builder.preview_failed")} fix={t("builder.preview_failed_fix")} compact />}
                {!result && !running && runError === null && <EmptyState compact illustration="data-reports" title={t("builder.preview_empty")} />}
                {result && result.rows.length === 0 && runError === null && <EmptyState compact illustration="no-data" title={t("builder.no_rows")} hint={t("builder.no_rows_hint")} />}
                {result && result.rows.length > 0 && (
                  <TableContainer sx={{ maxHeight: 480, border: `1px solid ${f.line}`, borderRadius: "12px" }}>
                    <Table size="small" stickyHeader>
                      <TableHead>
                        <TableRow>{result.columns.map((c) => <TableCell key={c}>{labelOf(c)}</TableCell>)}</TableRow>
                      </TableHead>
                      <TableBody>
                        {result.rows.map((row, i) => (
                          <TableRow key={i} hover>
                            {result.columns.map((c) => <TableCell key={c} sx={{ fontVariantNumeric: "tabular-nums" }}>{formatCell(row[c], byKey[c]?.type, c)}</TableCell>)}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                )}
                {!savedId && result && <Typography variant="caption" component="p" color="text.secondary" sx={{ mt: 1 }}>{t("builder.export_hint")}</Typography>}
                {actionError !== null && !saveOpen && <Box sx={{ mt: 1.5 }}><FriendlyError error={actionError} compact /></Box>}
              </InsightCard>
            </Cell>

            <Cell span={{ xs: 12, lg: 4 }}>
              <InsightCard emoji="file_folder" title={t("builder.saved_title")} sub={t("builder.saved_sub")}>
                {saved.state === "loading" && <CardLoading height={120} />}
                {saved.state === "error" && <FriendlyError error={saved.error} onRetry={reloadSaved} compact />}
                {saved.state === "ok" && saved.data.length === 0 && <EmptyState compact illustration="report" title={t("builder.saved_none")} />}
                {saved.state === "ok" && saved.data.length > 0 && (
                  <Stack spacing={1}>
                    {saved.data.map((r) => {
                      const ds = list.find((d) => d.code === r.dataset);
                      return (
                        <Box key={r.id} sx={{ p: "10px 12px", borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
                          <Typography sx={{ fontWeight: 700 }}>{r.name}</Typography>
                          <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
                            <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>{ds ? dsLabel(t, ds) : friendly(r.dataset)}</Typography>
                            {canExport && (
                              <>
                                <Button size="small" disabled={busy} onClick={() => doExport("xlsx", r.id, r.name)}>{t("builder.export.excel")}</Button>
                                <Button size="small" disabled={busy} onClick={() => doExport("csv", r.id, r.name)}>{t("builder.export.csv")}</Button>
                              </>
                            )}
                          </Stack>
                        </Box>
                      );
                    })}
                  </Stack>
                )}
              </InsightCard>
            </Cell>
            <Cell span={{ xs: 12, lg: 8 }}>
              <ScheduleReports reports={saved.state === "ok" ? saved.data : []} canSchedule={canExport} />
            </Cell>
          </PageGrid>
          <DragOverlay dropAnimation={reduced ? null : undefined}>{dragging ? <DragGhost label={dragging.label} /> : null}</DragOverlay>
        </DndContext>
      )}

      <Dialog open={saveOpen} onClose={() => setSaveOpen(false)} maxWidth="xs" fullWidth aria-labelledby="save-report-title">
        <DialogTitle id="save-report-title">{t("builder.save_title")}</DialogTitle>
        <DialogContent>
          <TextField autoFocus fullWidth label={t("builder.name")} value={name} onChange={(e) => setName(e.target.value)} placeholder={t("builder.name_eg")}
            helperText={t("builder.name_hint")} sx={{ mt: 1 }} onKeyDown={(e) => e.key === "Enter" && doSave()} />
          {actionError !== null && <Box sx={{ mt: 1.5 }}><FriendlyError error={actionError} compact /></Box>}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSaveOpen(false)}>{t("action.cancel")}</Button>
          <Button variant="contained" onClick={doSave} disabled={busy || !name.trim()}>{t("action.save")}</Button>
        </DialogActions>
      </Dialog>
      <Snackbar open={Boolean(toast)} autoHideDuration={4000} onClose={() => setToast(null)} message={toast ?? ""} />
    </Box>
  );
}
