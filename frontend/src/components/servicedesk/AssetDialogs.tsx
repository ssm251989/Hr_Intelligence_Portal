// Part 15.6 -- asset action dialogs: add, give to someone, take back, log a repair, hand over a request.
import { useEffect, useState, type ReactNode } from "react";
import Autocomplete from "@mui/material/Autocomplete";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage } from "../../api/client";
import { serviceDeskExtra, type Asset, type AssetMeta, type AssetRequestRow, type Category, type PersonLite } from "../../api/serviceDeskExtra";
import { useT } from "../../i18n";
import { FriendlyError } from "../../ui-kit";

function Shell({ open, title, onClose, onSubmit, submitLabel, busy, canSubmit, error, children }: {
  open: boolean; title: string; onClose: () => void; onSubmit: () => void; submitLabel: string; busy: boolean; canSubmit: boolean; error: unknown; children: ReactNode;
}) {
  const t = useT();
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {children}
          {error ? <FriendlyError error={error} compact /> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={onSubmit} disabled={busy || !canSubmit}>{busy ? t("helpdesk.common.saving") : submitLabel}</Button>
      </DialogActions>
    </Dialog>
  );
}

function useAction(onDone: (msg?: string) => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const run = async (fn: () => Promise<string | undefined>) => {
    setBusy(true);
    setError(null);
    try {
      onDone(await fn());
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run, reset: () => setError(null) };
}

const today = () => new Date().toISOString().slice(0, 10);

export function NewAssetDialog({ open, onClose, onDone, categories, onCategoriesChanged }: {
  open: boolean; onClose: () => void; onDone: (msg?: string) => void; categories: Category[]; onCategoriesChanged?: () => void;
}) {
  const t = useT();
  const a = useAction(onDone);
  const [form, setForm] = useState({ asset_tag: "", name: "", category_code: "", serial_number: "", vendor: "", purchase_date: "", warranty_until: "" });
  // Part 20.0-D: "Add asset type" inside the dropdown (also the way out when the list is empty)
  const [adding, setAdding] = useState(false);
  const [newType, setNewType] = useState("");
  const [extra, setExtra] = useState<Category[]>([]);
  const [addError, setAddError] = useState<string | null>(null);
  const options = [...categories, ...extra.filter((x) => !categories.some((c) => c.code === x.code))];
  useEffect(() => {
    if (open) {
      setForm({ asset_tag: "", name: "", category_code: categories[0]?.code ?? "", serial_number: "", vendor: "", purchase_date: "", warranty_until: "" });
      setAdding(false);
      setNewType("");
      setAddError(null);
      a.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  // the list may arrive after the dialog opened: pick the first type then (it used to stay empty)
  useEffect(() => {
    if (open && !form.category_code && categories.length) setForm((s) => ({ ...s, category_code: categories[0].code }));
  }, [open, categories, form.category_code]);
  const addType = async () => {
    setAddError(null);
    try {
      const c = await serviceDeskExtra.addCategory("asset", newType.trim());
      setExtra((x) => [...x, c]);
      setForm((s) => ({ ...s, category_code: c.code }));
      setAdding(false);
      setNewType("");
      onCategoriesChanged?.();
    } catch (e) {
      setAddError(extractErrorMessage(e, t("assets.types.add_failed")));
    }
  };
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((s) => ({ ...s, [k]: e.target.value }));
  return (
    <Shell open={open} title={t("assets.new.title")} onClose={onClose} busy={a.busy} error={a.error} submitLabel={t("assets.add")}
      canSubmit={Boolean(form.asset_tag.trim() && form.name.trim() && form.category_code)}
      onSubmit={() => a.run(async () => {
        await serviceDeskExtra.createAsset({
          asset_tag: form.asset_tag.trim(), name: form.name.trim(), category_code: form.category_code,
          serial_number: form.serial_number.trim() || null, vendor: form.vendor.trim() || null,
          purchase_date: form.purchase_date || null, warranty_until: form.warranty_until || null,
        });
        return t("assets.new.done", { tag: form.asset_tag.trim() });
      })}>
      <TextField required label={t("assets.new.tag")} placeholder={t("assets.new.tag_ph")} helperText={t("assets.new.tag_hint")} value={form.asset_tag} onChange={set("asset_tag")} />
      <TextField required label={t("assets.new.name")} placeholder={t("assets.new.name_ph")} value={form.name} onChange={set("name")} />
      <TextField required select label={t("assets.new.category")} value={options.some((c) => c.code === form.category_code) ? form.category_code : ""}
        onChange={(e) => { if (e.target.value === "__add") { setAdding(true); return; } setForm((s) => ({ ...s, category_code: e.target.value })); }}
        helperText={options.length ? undefined : t("assets.types.none")}>
        {options.length === 0 && <MenuItem disabled value="">{t("assets.types.none")}</MenuItem>}
        {options.map((c) => <MenuItem key={c.code} value={c.code}>{c.label}</MenuItem>)}
        <MenuItem value="__add" sx={{ fontWeight: 700, color: "primary.main" }}>{t("assets.types.add")}</MenuItem>
      </TextField>
      {adding && (
        <Stack direction="row" spacing={1} alignItems="flex-start">
          <TextField autoFocus size="small" fullWidth label={t("assets.types.new_label")} placeholder={t("assets.types.new_ph")} value={newType}
            onChange={(e) => setNewType(e.target.value)} error={Boolean(addError)} helperText={addError ?? undefined}
            onKeyDown={(e) => { if (e.key === "Enter" && newType.trim()) { e.preventDefault(); void addType(); } }} />
          <Button variant="contained" onClick={addType} disabled={!newType.trim()}>{t("assets.types.add_button")}</Button>
          <Button onClick={() => setAdding(false)}>{t("action.cancel")}</Button>
        </Stack>
      )}
      <TextField label={t("assets.new.serial")} placeholder={t("assets.new.serial_ph")} value={form.serial_number} onChange={set("serial_number")} />
      <TextField label={t("assets.new.vendor")} placeholder={t("assets.new.vendor_ph")} value={form.vendor} onChange={set("vendor")} />
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        <TextField type="date" label={t("assets.new.purchase")} value={form.purchase_date} onChange={set("purchase_date")} InputLabelProps={{ shrink: true }} fullWidth />
        <TextField type="date" label={t("assets.new.warranty")} value={form.warranty_until} onChange={set("warranty_until")} InputLabelProps={{ shrink: true }} fullWidth />
      </Stack>
    </Shell>
  );
}

/** Employee search box (name or code). */
export function PersonPicker({ value, onChange }: { value: PersonLite | null; onChange: (p: PersonLite | null) => void }) {
  const t = useT();
  const [input, setInput] = useState("");
  const [options, setOptions] = useState<PersonLite[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setLoading(true);
    const id = window.setTimeout(() => {
      serviceDeskExtra.people({ q: input.trim() || undefined }).then(setOptions).catch(() => setOptions([])).finally(() => setLoading(false));
    }, 300);
    return () => window.clearTimeout(id);
  }, [input]);
  return (
    <Autocomplete
      options={options}
      value={value}
      loading={loading}
      onChange={(_, v) => onChange(v)}
      onInputChange={(_, v) => setInput(v)}
      filterOptions={(x) => x}
      isOptionEqualToValue={(a, b) => a.id === b.id}
      getOptionLabel={(p) => `${p.name ?? ""} (${p.code})`}
      noOptionsText={t("assets.allocate.no_match")}
      renderInput={(params) => (
        <TextField {...params} required label={t("assets.allocate.person")} placeholder={t("assets.allocate.person_ph")} helperText={t("assets.allocate.person_hint")} />
      )}
    />
  );
}

export function AllocateDialog({ asset, onClose, onDone }: { asset: Asset | null; onClose: () => void; onDone: (msg?: string) => void }) {
  const t = useT();
  const a = useAction(onDone);
  const [person, setPerson] = useState<PersonLite | null>(null);
  useEffect(() => { setPerson(null); a.reset(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [asset]);
  return (
    <Shell open={Boolean(asset)} title={t("assets.allocate.title", { name: asset?.name ?? "" })} onClose={onClose} busy={a.busy} error={a.error}
      submitLabel={t("assets.allocate")} canSubmit={Boolean(person)}
      onSubmit={() => a.run(async () => {
        await serviceDeskExtra.allocate(asset!.id, person!.id);
        return t("assets.allocate.done", { name: person!.name ?? person!.code });
      })}>
      <PersonPicker value={person} onChange={setPerson} />
    </Shell>
  );
}

export function ReturnDialog({ asset, meta, onClose, onDone }: { asset: Asset | null; meta?: AssetMeta; onClose: () => void; onDone: (msg?: string) => void }) {
  const t = useT();
  const a = useAction(onDone);
  const [condition, setCondition] = useState<"good" | "damaged" | "lost">("good");
  const [notes, setNotes] = useState("");
  useEffect(() => { setCondition("good"); setNotes(""); a.reset(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [asset]);
  return (
    <Shell open={Boolean(asset)} title={t("assets.return.title", { name: asset?.name ?? "" })} onClose={onClose} busy={a.busy} error={a.error}
      submitLabel={t("assets.return")} canSubmit={Boolean(meta?.allocation_id)}
      onSubmit={() => a.run(async () => {
        await serviceDeskExtra.returnAsset(meta!.allocation_id, condition, notes.trim() || undefined);
        return t("assets.return.done");
      })}>
      {meta?.employee_name && <Typography>{t("assets.col.holder")}: <strong>{meta.employee_name}</strong></Typography>}
      <Typography component="label" id="sd-cond" sx={{ fontWeight: 700 }}>{t("assets.return.condition")}</Typography>
      <RadioGroup aria-labelledby="sd-cond" value={condition} onChange={(e) => setCondition(e.target.value as typeof condition)}>
        {(["good", "damaged", "lost"] as const).map((c) => <FormControlLabel key={c} value={c} control={<Radio />} label={t(`assets.cond.${c}`)} />)}
      </RadioGroup>
      <TextField label={t("assets.return.notes")} placeholder={t("assets.return.notes_ph")} value={notes} onChange={(e) => setNotes(e.target.value)} multiline minRows={2} />
    </Shell>
  );
}

export function MaintenanceDialog({ asset, onClose, onDone }: { asset: Asset | null; onClose: () => void; onDone: (msg?: string) => void }) {
  const t = useT();
  const a = useAction(onDone);
  const [form, setForm] = useState({ performed_on: today(), description: "", cost: "", vendor: "" });
  useEffect(() => { setForm({ performed_on: today(), description: "", cost: "", vendor: "" }); a.reset(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [asset]);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((s) => ({ ...s, [k]: e.target.value }));
  return (
    <Shell open={Boolean(asset)} title={t("assets.maint.title", { name: asset?.name ?? "" })} onClose={onClose} busy={a.busy} error={a.error}
      submitLabel={t("assets.maint")} canSubmit={Boolean(form.performed_on && form.description.trim())}
      onSubmit={() => a.run(async () => {
        await serviceDeskExtra.maintenance(asset!.id, {
          performed_on: form.performed_on, description: form.description.trim(),
          cost: form.cost ? Number(form.cost) : null, vendor: form.vendor.trim() || null,
        });
        return t("assets.maint.done");
      })}>
      <TextField required type="date" label={t("assets.maint.date")} value={form.performed_on} onChange={set("performed_on")} InputLabelProps={{ shrink: true }} />
      <TextField required label={t("assets.maint.what")} placeholder={t("assets.maint.what_ph")} value={form.description} onChange={set("description")} />
      <TextField type="number" label={t("assets.maint.cost")} placeholder={t("assets.maint.cost_ph")} value={form.cost} onChange={set("cost")} inputProps={{ min: 0 }} />
      <TextField label={t("assets.maint.vendor")} placeholder={t("assets.maint.vendor_ph")} value={form.vendor} onChange={set("vendor")} />
    </Shell>
  );
}

export function FulfilDialog({ request, onClose, onDone, categoryLabel }: { request: AssetRequestRow | null; onClose: () => void; onDone: (msg?: string) => void; categoryLabel: (c: string) => string }) {
  const t = useT();
  const a = useAction(onDone);
  const [stock, setStock] = useState<Asset[]>([]);
  const [assetId, setAssetId] = useState("");
  useEffect(() => {
    setAssetId("");
    a.reset();
    if (request) serviceDeskExtra.assets({ status: "in_stock", category: request.category_code }).then((r) => setStock(r.items)).catch(() => setStock([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);
  return (
    <Shell open={Boolean(request)} onClose={onClose} busy={a.busy} error={a.error} canSubmit
      title={t("assets.reqs.fulfil_title", { category: request ? categoryLabel(request.category_code) : "", name: request?.employee_name ?? "" })}
      submitLabel={t("assets.reqs.fulfil")}
      onSubmit={() => a.run(async () => {
        await serviceDeskExtra.fulfil(request!.id, assetId || null);
        return t("assets.reqs.fulfilled");
      })}>
      <TextField select label={t("assets.reqs.fulfil_pick")} value={assetId} onChange={(e) => setAssetId(e.target.value)} helperText={t("assets.reqs.fulfil_hint")}>
        <MenuItem value="">{t("assets.reqs.fulfil_auto")}</MenuItem>
        {stock.map((s) => <MenuItem key={s.id} value={s.id}>{`${s.asset_tag} — ${s.name}`}</MenuItem>)}
      </TextField>
    </Shell>
  );
}
