// Part 15.6 -- /assets (L T5, T6, T7). Register with filters, a QR code per asset and a
// printable label sheet; give / take back / repair; catalogue + request with approval and
// hand-over; the employee's electronic receipt confirmation.
import { useCallback, useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import LinearProgress from "@mui/material/LinearProgress";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import QrCode2Icon from "@mui/icons-material/QrCode2";
import { useTheme } from "@mui/material/styles";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import { serviceDeskExtra, type Asset, type AssetMeta, type AssetRequestRow, type CatalogueItem, type MyAsset } from "../../api/serviceDeskExtra";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import ListToolbar, { type ListColumn, type ListViewState } from "../../components/ListToolbar";
import { AllocateDialog, FulfilDialog, MaintenanceDialog, NewAssetDialog, ReturnDialog } from "../../components/servicedesk/AssetDialogs";
import { LabelSheetDialog, QrDialog } from "../../components/servicedesk/AssetQr";
import { AssetStatusChip, RequestStatusChip, Section, useCategories, useDateFmt, useToast } from "../../components/servicedesk/shared";
import { useI18n, useT } from "../../i18n";
import { Cell, EmptyState, Emoji, FriendlyError, PageGrid, PageHeader, StatTile, StatusChip } from "../../ui-kit";

type TabKey = "register" | "requests" | "mine" | "catalogue";
const ASSET_STATUSES = ["in_stock", "allocated", "in_repair", "lost", "retired"];
const CATEGORY_EMOJI: Record<string, string> = { laptop: "laptop", phone: "speech", mobile: "speech", monitor: "laptop", id_card: "id_card", sim: "key", furniture: "building" };

// ---- register (HR / IT) ----

function Register({ initialSearch, canEdit, canCreate, reloadKey, onToast }: {
  initialSearch: string; canEdit: boolean; canCreate: boolean; reloadKey: number; onToast: (m: string) => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const cats = useCategories("asset");
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState(initialSearch);
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<Asset[]>([]);
  const [total, setTotal] = useState(0);
  const [meta, setMeta] = useState<Record<string, AssetMeta>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [labelsOpen, setLabelsOpen] = useState(false);
  const [qr, setQr] = useState<Asset | null>(null);
  const [menu, setMenu] = useState<{ el: HTMLElement; asset: Asset } | null>(null);
  const [allocate, setAllocate] = useState<Asset | null>(null);
  const [giveBack, setGiveBack] = useState<Asset | null>(null);
  const [repair, setRepair] = useState<Asset | null>(null);
  const [adding, setAdding] = useState(false);
  const [innerKey, setInnerKey] = useState(0);

  const columns: ListColumn[] = useMemo(() => [
    { key: "tag", label: t("assets.col.tag") }, { key: "name", label: t("assets.col.name") }, { key: "category", label: t("assets.col.category") },
    { key: "serial", label: t("assets.col.serial") }, { key: "status", label: t("assets.col.status") }, { key: "holder", label: t("assets.col.holder") },
    { key: "warranty", label: t("assets.col.warranty") }, { key: "value", label: t("assets.col.value") },
  ], [t]);
  const [view, setView] = useState<ListViewState>({ columns: ["tag", "name", "category", "status", "holder", "warranty"], filters: {} });
  const col = (k: string) => view.columns.includes(k);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    serviceDeskExtra.assets({ status: status || undefined, category: category || undefined, page: page + 1 })
      .then((res) => {
        setRows(res.items);
        setTotal(res.total);
        const out = res.items.filter((a) => a.allocated_to).map((a) => a.id);
        if (out.length) return serviceDeskExtra.assetsMeta(out).then(setMeta);
        setMeta({});
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [status, category, page]);
  useEffect(load, [load, reloadKey, innerKey]);

  const q = search.trim().toLowerCase();
  const visible = q ? rows.filter((a) => [a.asset_tag, a.name, a.serial_number, a.vendor, meta[a.id]?.employee_name].some((v) => v?.toLowerCase().includes(q))) : rows;
  const labelAssets = selected.size ? rows.filter((a) => selected.has(a.id)) : visible;
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const done = (msg?: string) => {
    setAllocate(null); setGiveBack(null); setRepair(null); setAdding(false);
    if (msg) onToast(msg);
    setInnerKey((k) => k + 1);
  };

  const out = rows.filter((a) => a.status === "allocated").length;
  const stock = rows.filter((a) => a.status === "in_stock").length;
  const unconfirmed = Object.values(meta).filter((m) => !m.acknowledged_at).length;

  const exportRows = visible.map((a) => ({
    tag: a.asset_tag, name: a.name, category: cats.label(a.category_code), serial: a.serial_number ?? "", status: t(`assets.status.${a.status}`),
    holder: meta[a.id]?.employee_name ?? "", warranty: a.warranty_until ?? "", value: a.book_value ?? "",
  }));

  return (
    <>
      <PageGrid sx={{ mb: 2.25 }}>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="laptop" value={total} label={t("assets.stat.total", { count: total })} loading={loading} /></Cell>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="handshake" value={out} label={t("assets.stat.page_out")} tone="sky" loading={loading} /></Cell>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="package" value={stock} label={t("assets.stat.page_stock")} tone="ok" loading={loading} /></Cell>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="hourglass" value={unconfirmed} label={t("assets.stat.unconfirmed")} tone="sun" loading={loading} /></Cell>
      </PageGrid>
      <Card sx={{ p: { xs: 1.5, md: 2 } }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ mb: 1 }} alignItems={{ md: "center" }} flexWrap="wrap" useFlexGap>
          <TextField size="small" label={t("assets.filter.search")} placeholder={t("assets.filter.search_ph")} value={search} onChange={(e) => setSearch(e.target.value)} sx={{ minWidth: 240 }} />
          <TextField select size="small" label={t("assets.filter.status")} value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }} sx={{ minWidth: 180 }}>
            <MenuItem value="">{t("assets.filter.any_status")}</MenuItem>
            {ASSET_STATUSES.map((s) => <MenuItem key={s} value={s}>{t(`assets.status.${s}`)}</MenuItem>)}
          </TextField>
          <TextField select size="small" label={t("assets.filter.category")} value={category} onChange={(e) => { setCategory(e.target.value); setPage(0); }} sx={{ minWidth: 180 }}>
            <MenuItem value="">{t("assets.filter.any_category")}</MenuItem>
            {(cats.list ?? []).map((c) => <MenuItem key={c.code} value={c.code}>{c.label}</MenuItem>)}
          </TextField>
          <Box sx={{ flex: 1 }} />
          <Button variant="outlined" startIcon={<Emoji name="label" size={16} />} onClick={() => setLabelsOpen(true)} disabled={!visible.length && !selected.size}>
            {selected.size ? t("assets.print", { count: selected.size }) : t("assets.print_page")}
          </Button>
          {canCreate && <Button variant="text" onClick={() => setAdding(true)}>{t("assets.add")}</Button>}
        </Stack>
        <ListToolbar listKey="assets.register" columns={columns} state={view} onStateChange={setView} rows={exportRows} loading={loading} onRefresh={load} />
        {loading && <LinearProgress aria-label={t("helpdesk.common.loading")} sx={{ mb: 1 }} />}
        {error ? <FriendlyError error={error} onRetry={load} compact /> : visible.length === 0 && !loading ? (
          total === 0 && !status && !category ? (
            <EmptyState illustration="empty" title={t("assets.empty")} hint={t("assets.empty_hint")}
              action={canCreate ? <Button variant="contained" onClick={() => setAdding(true)}>{t("assets.add")}</Button> : undefined} />
          ) : <EmptyState compact illustration="search" title={t("assets.empty_filtered")} />
        ) : (
          <TableContainer>
            <Table size="small" aria-label={t("assets.tab.register")}>
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox">
                    <Checkbox inputProps={{ "aria-label": t("assets.col.select") }} checked={visible.length > 0 && visible.every((a) => selected.has(a.id))}
                      indeterminate={visible.some((a) => selected.has(a.id)) && !visible.every((a) => selected.has(a.id))}
                      onChange={(e) => setSelected(e.target.checked ? new Set(visible.map((a) => a.id)) : new Set())} />
                  </TableCell>
                  {col("tag") && <TableCell>{t("assets.col.tag")}</TableCell>}
                  {col("name") && <TableCell>{t("assets.col.name")}</TableCell>}
                  {col("category") && <TableCell>{t("assets.col.category")}</TableCell>}
                  {col("serial") && <TableCell>{t("assets.col.serial")}</TableCell>}
                  {col("status") && <TableCell>{t("assets.col.status")}</TableCell>}
                  {col("holder") && <TableCell>{t("assets.col.holder")}</TableCell>}
                  {col("warranty") && <TableCell>{t("assets.col.warranty")}</TableCell>}
                  {col("value") && <TableCell align="right">{t("assets.col.value")}</TableCell>}
                  <TableCell align="right">{t("assets.col.actions")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visible.map((a) => {
                  const m = meta[a.id];
                  return (
                    <TableRow key={a.id} hover selected={selected.has(a.id)}>
                      <TableCell padding="checkbox">
                        <Checkbox checked={selected.has(a.id)} onChange={() => toggle(a.id)} inputProps={{ "aria-label": `${t("assets.col.select")}: ${a.asset_tag}` }} />
                      </TableCell>
                      {col("tag") && <TableCell sx={{ fontWeight: 700, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{a.asset_tag}</TableCell>}
                      {col("name") && <TableCell>{a.name}</TableCell>}
                      {col("category") && <TableCell>{cats.label(a.category_code)}</TableCell>}
                      {col("serial") && <TableCell>{a.serial_number ?? "—"}</TableCell>}
                      {col("status") && <TableCell><AssetStatusChip status={a.status} /></TableCell>}
                      {col("holder") && (
                        <TableCell>
                          {m ? (
                            <Stack spacing={0.5} alignItems="flex-start">
                              <span>{m.employee_name ?? "—"}</span>
                              {m.acknowledged_at
                                ? <StatusChip tone="ok" emoji="writing_hand" label={t("assets.handover.done")} />
                                : <StatusChip tone="sun" emoji="hourglass" label={t("assets.handover.pending")} />}
                            </Stack>
                          ) : "—"}
                        </TableCell>
                      )}
                      {col("warranty") && <TableCell sx={{ whiteSpace: "nowrap" }}>{fmt.date(a.warranty_until)}</TableCell>}
                      {col("value") && <TableCell align="right" sx={{ fontVariantNumeric: "tabular-nums" }}>{fmt.money(a.book_value)}</TableCell>}
                      <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                        <IconButton size="small" aria-label={t("assets.qr.title", { tag: a.asset_tag })} onClick={() => setQr(a)}><QrCode2Icon fontSize="small" /></IconButton>
                        {canEdit && (
                          <IconButton size="small" aria-label={`${t("helpdesk.common.more")}: ${a.asset_tag}`} onClick={(e) => setMenu({ el: e.currentTarget, asset: a })}>
                            <MoreVertIcon fontSize="small" />
                          </IconButton>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
        <TablePagination component="div" count={total} page={page} onPageChange={(_, p) => { setPage(p); setSelected(new Set()); }} rowsPerPage={25} rowsPerPageOptions={[25]}
          labelDisplayedRows={({ from, to, count }) => t("helpdesk.common.rows", { from, to, count })} />
        <Typography sx={{ fontSize: 12, color: f.muted }}>{t("assets.qr.hint")}</Typography>
      </Card>

      <Menu anchorEl={menu?.el} open={Boolean(menu)} onClose={() => setMenu(null)}>
        {menu?.asset.status === "in_stock" && <MenuItem onClick={() => { setAllocate(menu.asset); setMenu(null); }}>{t("assets.allocate")}</MenuItem>}
        {menu && meta[menu.asset.id] && <MenuItem onClick={() => { setGiveBack(menu.asset); setMenu(null); }}>{t("assets.return")}</MenuItem>}
        {menu && <MenuItem onClick={() => { setRepair(menu.asset); setMenu(null); }}>{t("assets.maint")}</MenuItem>}
        {menu && <MenuItem onClick={() => { setQr(menu.asset); setMenu(null); }}>{t("assets.qr.show")}</MenuItem>}
      </Menu>
      <QrDialog asset={qr} onClose={() => setQr(null)} />
      <LabelSheetDialog assets={labelAssets} open={labelsOpen} onClose={() => setLabelsOpen(false)} categoryLabel={cats.label} />
      <AllocateDialog asset={allocate} onClose={() => setAllocate(null)} onDone={done} />
      <ReturnDialog asset={giveBack} meta={giveBack ? meta[giveBack.id] : undefined} onClose={() => setGiveBack(null)} onDone={done} />
      <MaintenanceDialog asset={repair} onClose={() => setRepair(null)} onDone={done} />
      <NewAssetDialog open={adding} onClose={() => setAdding(false)} onDone={done} categories={cats.list ?? []} onCategoriesChanged={cats.reload} />
    </>
  );
}

// ---- requests (approvers / IT) ----

function Requests({ canApprove, canFulfil, onToast }: { canApprove: boolean; canFulfil: boolean; onToast: (m: string) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const cats = useCategories("asset");
  const [showDone, setShowDone] = useState(false);
  const [rows, setRows] = useState<AssetRequestRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [fulfil, setFulfil] = useState<AssetRequestRow | null>(null);

  const load = useCallback(() => {
    setError(null);
    serviceDeskExtra.requests(showDone ? undefined : "requested,approved").then(setRows).catch(setError);
  }, [showDone]);
  useEffect(load, [load]);

  const decide = async (r: AssetRequestRow, approve: boolean) => {
    setBusy(r.id);
    try {
      await serviceDeskExtra.decide(r.id, approve);
      onToast(t("assets.reqs.decided"));
      load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  const waiting = rows?.filter((r) => r.status === "requested").length ?? 0;
  const toHand = rows?.filter((r) => r.status === "approved").length ?? 0;

  return (
    <>
      <PageGrid sx={{ mb: 2.25 }}>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="hourglass" value={waiting} label={t("assets.reqs.stat.waiting")} tone="sun" loading={rows === null} /></Cell>
        <Cell span={{ xs: 6, md: 3 }}><StatTile emoji="package" value={toHand} label={t("assets.reqs.stat.to_hand")} tone="sky" loading={rows === null} /></Cell>
      </PageGrid>
      <Section emoji="clipboard" title={t("assets.reqs.title")} hint={t("assets.reqs.purpose")}
        action={<FormControlLabel control={<Switch checked={showDone} onChange={(e) => setShowDone(e.target.checked)} />} label={t("assets.reqs.show_done")} />}>
        {error ? <FriendlyError error={error} onRetry={load} compact /> : rows === null ? <LinearProgress /> : rows.length === 0 ? (
          <EmptyState compact illustration="done" title={t("assets.reqs.empty")} />
        ) : (
          <TableContainer>
            <Table size="small" aria-label={t("assets.reqs.title")}>
              <TableHead>
                <TableRow>
                  <TableCell>{t("assets.reqs.col.person")}</TableCell>
                  <TableCell>{t("assets.reqs.col.what")}</TableCell>
                  <TableCell>{t("assets.reqs.col.why")}</TableCell>
                  <TableCell>{t("assets.reqs.col.when")}</TableCell>
                  <TableCell>{t("assets.reqs.col.status")}</TableCell>
                  <TableCell align="right">{t("assets.col.actions")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.id} hover>
                    <TableCell sx={{ fontWeight: 600 }}>{r.employee_name ?? "—"}</TableCell>
                    <TableCell>{cats.label(r.category_code)}{r.fulfilled_asset ? <Typography sx={{ fontSize: 12, color: f.muted }}>{r.fulfilled_asset.asset_tag} — {r.fulfilled_asset.name}</Typography> : null}</TableCell>
                    <TableCell sx={{ maxWidth: 320 }}>{r.reason ?? "—"}</TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{fmt.date(r.created_at)}</TableCell>
                    <TableCell><RequestStatusChip status={r.status} /></TableCell>
                    <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                      {r.status === "requested" && canApprove && (
                        <Stack direction="row" spacing={1} justifyContent="flex-end">
                          <Button size="small" variant="contained" disabled={busy === r.id} onClick={() => decide(r, true)}>{t("assets.reqs.approve")}</Button>
                          <Button size="small" variant="outlined" color="error" disabled={busy === r.id} onClick={() => decide(r, false)}>{t("assets.reqs.decline")}</Button>
                        </Stack>
                      )}
                      {r.status === "approved" && canFulfil && (
                        <Button size="small" variant="contained" onClick={() => setFulfil(r)}>{t("assets.reqs.fulfil")}</Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Section>
      <FulfilDialog request={fulfil} onClose={() => setFulfil(null)} categoryLabel={cats.label}
        onDone={(msg) => { setFulfil(null); if (msg) onToast(msg); load(); }} />
    </>
  );
}

// ---- employee: my things + acknowledgement (T7) ----

function MyThings({ reloadKey, onAsk, onToast }: { reloadKey: number; onAsk?: () => void; onToast: (m: string) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useDateFmt();
  const cats = useCategories("asset");
  const [rows, setRows] = useState<MyAsset[] | null>(null);
  const [reqs, setReqs] = useState<AssetRequestRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notLinked, setNotLinked] = useState(false);
  const [confirm, setConfirm] = useState<MyAsset | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<unknown>(null);

  const load = useCallback(() => {
    setError(null);
    setNotLinked(false);
    serviceDeskExtra.myAssets().then(setRows).catch((e) => {
      if (e instanceof ApiError && e.status === 404) { setNotLinked(true); setRows([]); } else setError(e);
    });
    serviceDeskExtra.myRequests().then(setReqs).catch(() => setReqs([]));
  }, []);
  useEffect(load, [load, reloadKey]);

  const acknowledge = async () => {
    if (!confirm) return;
    setBusy(true);
    setConfirmError(null);
    try {
      await serviceDeskExtra.acknowledge(confirm.allocation_id, t("assets.mine.confirm_text", { name: confirm.name, tag: confirm.asset_tag }));
      setConfirm(null);
      onToast(t("assets.mine.confirmed"));
      load();
    } catch (e) {
      setConfirmError(e);
    } finally {
      setBusy(false);
    }
  };

  if (notLinked) return <FriendlyError what={t("assets.mine.not_linked")} fix={t("error.generic_fix")} />;

  return (
    <PageGrid>
      <Cell span={{ md: 12, lg: 7 }}>
        <Section emoji="laptop" title={t("assets.mine.title")}>
          {error ? <FriendlyError error={error} onRetry={load} compact /> : rows === null ? <LinearProgress /> : rows.length === 0 ? (
            <EmptyState compact illustration="empty" title={t("assets.mine.empty")} hint={t("assets.mine.empty_hint")}
              action={onAsk ? <Button variant="contained" onClick={onAsk}>{t("assets.ask")}</Button> : undefined} />
          ) : (
            <Stack spacing={1} component="ul" sx={{ listStyle: "none", p: 0, m: 0 }}>
              {rows.map((a) => (
                <Box component="li" key={a.allocation_id} sx={{ border: `1px solid ${a.acknowledged ? f.line : f.sun}`, bgcolor: a.acknowledged ? f.surface2 : f.sunSoft, borderRadius: "12px", p: 1.5 }}>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
                    <Emoji name={CATEGORY_EMOJI[a.category_code] ?? "laptop"} size={28} />
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography sx={{ fontWeight: 700 }}>{a.name}</Typography>
                      <Typography sx={{ fontSize: 13, color: f.muted }}>
                        {a.asset_tag} · {cats.label(a.category_code)}{a.serial_number ? ` · ${a.serial_number}` : ""}{a.warranty_until ? ` · ${t("assets.col.warranty")} ${fmt.date(a.warranty_until)}` : ""}
                      </Typography>
                    </Box>
                    {a.acknowledged ? (
                      <StatusChip tone="ok" emoji="writing_hand" label={t("assets.handover.done")} />
                    ) : (
                      <Stack spacing={0.5} alignItems={{ sm: "flex-end" }}>
                        <StatusChip tone="sun" emoji="hourglass" label={t("assets.mine.needs_confirm")} />
                        <Button variant="contained" size="small" onClick={() => { setAgreed(false); setConfirm(a); }}>{t("assets.mine.confirm")}</Button>
                      </Stack>
                    )}
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </Section>
      </Cell>
      <Cell span={{ md: 12, lg: 5 }}>
        <Section emoji="clipboard" title={t("assets.myreq.title")}>
          {reqs === null ? <LinearProgress /> : reqs.length === 0 ? (
            <EmptyState compact illustration="empty" title={t("assets.myreq.empty")} />
          ) : (
            <Stack spacing={1} component="ul" sx={{ listStyle: "none", p: 0, m: 0 }}>
              {reqs.map((r) => (
                <Box component="li" key={r.id} sx={{ bgcolor: f.surface2, borderRadius: "12px", p: 1.5 }}>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Typography sx={{ fontWeight: 700, flex: 1 }}>{cats.label(r.category_code)}</Typography>
                    <RequestStatusChip status={r.status} />
                  </Stack>
                  <Typography sx={{ fontSize: 13, color: f.muted }}>{fmt.date(r.created_at)}{r.reason ? ` · ${r.reason}` : ""}</Typography>
                  {r.fulfilled_asset && <Typography sx={{ fontSize: 13 }}>{r.fulfilled_asset.asset_tag} — {r.fulfilled_asset.name}</Typography>}
                </Box>
              ))}
            </Stack>
          )}
        </Section>
      </Cell>

      <Dialog open={Boolean(confirm)} onClose={busy ? undefined : () => setConfirm(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{confirm ? t("assets.mine.confirm_title", { name: confirm.name }) : ""}</DialogTitle>
        <DialogContent>
          {confirm && (
            <Stack spacing={2}>
              <Typography sx={{ bgcolor: f.surface2, p: 1.5, borderRadius: "12px", maxWidth: "70ch" }}>
                {t("assets.mine.confirm_text", { name: confirm.name, tag: confirm.asset_tag })}
              </Typography>
              <FormControlLabel control={<Checkbox checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />} label={t("assets.mine.confirm_check")} />
              {confirmError ? <FriendlyError error={confirmError} compact /> : null}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirm(null)} disabled={busy}>{t("action.cancel")}</Button>
          <Button variant="contained" onClick={acknowledge} disabled={!agreed || busy}>{busy ? t("helpdesk.common.saving") : t("assets.mine.confirm")}</Button>
        </DialogActions>
      </Dialog>
    </PageGrid>
  );
}

// ---- employee: catalogue + request (T6) ----

function Catalogue({ onSent }: { onSent: (msg: string) => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { locale } = useI18n();
  const [items, setItems] = useState<CatalogueItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [asking, setAsking] = useState<CatalogueItem | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [sendError, setSendError] = useState<unknown>(null);

  const load = useCallback(() => {
    setError(null);
    serviceDeskExtra.catalogue(locale).then(setItems).catch(setError);
  }, [locale]);
  useEffect(load, [load]);

  const send = async () => {
    if (!asking) return;
    setBusy(true);
    setSendError(null);
    try {
      const r = await serviceDeskExtra.requestAsset(asking.code, reason.trim() || undefined);
      setAsking(null);
      onSent(r.status === "approved" ? t("assets.req.sent_approved") : t("assets.req.sent"));
      load();
    } catch (e) {
      setSendError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section emoji="package" title={t("assets.cat.title")} hint={t("assets.cat.hint")}>
      {error ? <FriendlyError error={error} onRetry={load} compact /> : items === null ? (
        <Box sx={{ display: "grid", placeItems: "center", py: 4 }}><CircularProgress aria-label={t("helpdesk.common.loading")} /></Box>
      ) : items.length === 0 ? <EmptyState compact illustration="empty" title={t("assets.cat.empty")} /> : (
        <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 1.5 }}>
          {items.map((c) => (
            <Card key={c.code} sx={{ p: 2, display: "flex", flexDirection: "column", gap: 1, bgcolor: f.surface2, boxShadow: "none", border: `1px solid ${f.line}` }}>
              <Emoji name={c.emoji || CATEGORY_EMOJI[c.code] || "package"} size={32} />
              <Typography sx={{ fontWeight: 800 }}>{c.label}</Typography>
              {c.hint && <Typography sx={{ fontSize: 13, color: f.muted }}>{c.hint}</Typography>}
              {c.in_stock > 0
                ? <StatusChip tone="ok" emoji="check" label={t("assets.cat.in_stock", { count: c.in_stock })} />
                : <StatusChip tone="sun" emoji="hourglass" label={t("assets.cat.none_stock")} />}
              <Box sx={{ flex: 1 }} />
              <Button variant="contained" onClick={() => { setReason(""); setSendError(null); setAsking(c); }}>{t("assets.cat.ask")}</Button>
            </Card>
          ))}
        </Box>
      )}
      <Dialog open={Boolean(asking)} onClose={busy ? undefined : () => setAsking(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{asking ? t("assets.req.title", { name: asking.label }) : ""}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField label={t("assets.req.reason")} placeholder={t("assets.req.reason_ph")} helperText={t("assets.req.reason_hint")} value={reason}
              onChange={(e) => setReason(e.target.value)} multiline minRows={2} fullWidth />
            {sendError ? <FriendlyError error={sendError} compact /> : null}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAsking(null)} disabled={busy}>{t("action.cancel")}</Button>
          <Button variant="contained" onClick={send} disabled={busy}>{busy ? t("helpdesk.common.saving") : t("assets.req.send")}</Button>
        </DialogActions>
      </Dialog>
    </Section>
  );
}

export default function AssetsPage() {
  const t = useT();
  const { can } = useMeBootstrap();
  const [params, setParams] = useSearchParams();
  const [toast, show] = useToast();
  const [reloadKey, setReloadKey] = useState(0);
  const [adding, setAdding] = useState(false);
  const cats = useCategories("asset");

  const perms = {
    register: can("assets.asset.view"),
    requests: can("assets.asset.approve") || can("assets.asset.edit"),
    mine: can("assets.self.view"),
    catalogue: can("assets.self.create"),
  };
  const tabs = (["register", "requests", "mine", "catalogue"] as TabKey[]).filter((k) => perms[k]);
  const wanted = params.get("tab") as TabKey | null;
  const tag = params.get("tag") ?? "";
  const fallback: TabKey | undefined = tag && perms.register ? "register" : perms.register ? "register" : tabs[0];
  const tab: TabKey | undefined = wanted && tabs.includes(wanted) ? wanted : fallback;
  const setTab = (k: TabKey) => setParams((p) => { const n = new URLSearchParams(p); n.set("tab", k); n.delete("tag"); return n; });
  const hrView = perms.register || perms.requests;

  const primary = can("assets.asset.create") && tab === "register"
    ? <Button variant="contained" onClick={() => setAdding(true)} startIcon={<Emoji name="laptop" size={16} />}>{t("assets.add")}</Button>
    : perms.catalogue ? <Button variant="contained" onClick={() => setTab("catalogue")} startIcon={<Emoji name="package" size={16} />}>{t("assets.ask")}</Button>
      : undefined;

  return (
    <Box>
      <PageHeader emoji="laptop" title={t("assets.title")} purpose={t(hrView ? "assets.purpose" : "assets.purpose_me")} tourKey="assets" primary={primary} />
      {tabs.length === 0 ? (
        <FriendlyError what={t("error.no_access")} fix={t("error.no_access_fix")} actionLabel={t("action.go_home")} actionTo="/" />
      ) : (
        <>
          {tabs.length > 1 && (
            <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }} variant="scrollable" allowScrollButtonsMobile aria-label={t("assets.title")}>
              {tabs.map((k) => <Tab key={k} value={k} label={t(`assets.tab.${k}`)} />)}
            </Tabs>
          )}
          {tab === "register" && (
            <Register initialSearch={tag} canEdit={can("assets.asset.edit")} canCreate={can("assets.asset.create")} reloadKey={reloadKey} onToast={(m) => show(m)} />
          )}
          {tab === "requests" && <Requests canApprove={can("assets.asset.approve")} canFulfil={can("assets.asset.edit")} onToast={(m) => show(m)} />}
          {tab === "mine" && <MyThings reloadKey={reloadKey} onAsk={perms.catalogue ? () => setTab("catalogue") : undefined} onToast={(m) => show(m)} />}
          {tab === "catalogue" && <Catalogue onSent={(m) => { show(m); setReloadKey((k) => k + 1); }} />}
        </>
      )}
      <NewAssetDialog open={adding} onClose={() => setAdding(false)} categories={cats.list ?? []} onCategoriesChanged={cats.reload}
        onDone={(m) => { setAdding(false); if (m) show(m); setReloadKey((k) => k + 1); }} />
      {toast}
    </Box>
  );
}
