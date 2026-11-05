import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
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
import Tooltip from "@mui/material/Tooltip";

import { extractErrorMessage } from "../../api/client";
import { employeesApi, type AppAccount, type EmpStatus, type EmployeeFacets, type EmployeeProfile, type EmployeeRow } from "../../api/employeesApi";
import { serviceDeskExtra, type Category } from "../../api/serviceDeskExtra";
import { useT } from "../../i18n";
import { StatusChip, type Tone } from "../../ui-kit";

// Part 20.1: dialogs and chips shared by the Employees list and the employee profile.

const STATUS_TONE: Record<EmpStatus, { tone: Tone; emoji: string }> = {
  active: { tone: "ok", emoji: "check" }, notice: { tone: "sun", emoji: "hourglass" }, exited: { tone: "muted", emoji: "door" }, absconded: { tone: "coral", emoji: "warning" },
};
const ACCOUNT_TONE: Record<AppAccount, Tone> = { active: "ok", invited: "sky", disabled: "muted", none: "muted" };

export function EmpStatusChip({ status }: { status: EmpStatus }) {
  const t = useT();
  const s = STATUS_TONE[status] ?? STATUS_TONE.active;
  return <StatusChip tone={s.tone} emoji={s.emoji} label={t(`emp.status.${status}`)} />;
}

export function AccountChip({ account, long }: { account: AppAccount; long?: boolean }) {
  const t = useT();
  const state = t(`emp.account.${account}`);
  return <StatusChip tone={ACCOUNT_TONE[account]} emoji="key" label={long ? t("emp.account_label", { state }) : state} />;
}

/** A company email with the grey TEST chip when it is a test-provider (dummy) mailbox (20.2b). */
export function CompanyEmail({ email, test }: { email: string | null; test: boolean }) {
  const t = useT();
  if (!email) return <>—</>;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      {email}
      {test && (
        <Tooltip title={t("emp.test_chip_hint")}>
          <Chip size="small" label="TEST" sx={{ height: 18, fontSize: 10, fontWeight: 800, bgcolor: "action.selected", color: "text.secondary" }} />
        </Tooltip>
      )}
    </span>
  );
}

export function EditEmployeeDialog({ employee, facets, people, onClose, onSaved }: {
  employee: EmployeeProfile | null; facets: EmployeeFacets | null; people: EmployeeRow[]; onClose: () => void; onSaved: (p: EmployeeProfile) => void;
}) {
  const t = useT();
  const [form, setForm] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!employee) return;
    setError(null);
    setForm({
      first_name: employee.first_name ?? "", last_name: employee.last_name ?? "", preferred_name: employee.personal.preferred_name ?? "",
      phone: employee.phone ?? "", personal_email: employee.personal_email ?? "", designation: employee.job.designation ?? "",
      department_id: employee.job.department_id ?? "", location_id: employee.job.location_id ?? "", manager_id: employee.job.manager_id ?? "",
      employment_type: employee.job.employment_type ?? "", joined_on: employee.job.joined_on ?? "",
      previous_years: employee.previous_experience_months != null ? String(Math.round((employee.previous_experience_months / 12) * 10) / 10) : "",
    });
  }, [employee]);
  if (!employee) return null;
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const { previous_years, joined_on, ...rest } = form;
      const body: Record<string, unknown> = { ...rest, joined_on: joined_on || null,
        previous_experience_months: previous_years === "" ? null : Math.round(Number(previous_years) * 12) };
      onSaved(await employeesApi.update(employee.id, body));
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("emp.edit.title", { name: employee.name })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label={t("emp.edit.code")} value={employee.employee_code} disabled helperText={t("emp.edit.code_hint")} />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
            <TextField fullWidth required label={t("emp.edit.first_name")} value={form.first_name ?? ""} onChange={set("first_name")} />
            <TextField fullWidth label={t("emp.edit.last_name")} value={form.last_name ?? ""} onChange={set("last_name")} />
          </Stack>
          <TextField label={t("emp.edit.preferred_name")} value={form.preferred_name ?? ""} onChange={set("preferred_name")} />
          <TextField label={t("emp.edit.designation")} value={form.designation ?? ""} onChange={set("designation")} />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
            <TextField select fullWidth label={t("emp.col.department")} value={form.department_id ?? ""} onChange={set("department_id")}>
              <MenuItem value="">—</MenuItem>
              {(facets?.departments ?? []).map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
            </TextField>
            <TextField select fullWidth label={t("emp.col.location")} value={form.location_id ?? ""} onChange={set("location_id")}>
              <MenuItem value="">—</MenuItem>
              {(facets?.locations ?? []).map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
            </TextField>
          </Stack>
          <TextField select label={t("emp.col.manager")} value={form.manager_id ?? ""} onChange={set("manager_id")}>
            <MenuItem value="">—</MenuItem>
            {people.filter((p) => p.id !== employee.id && p.status !== "exited" && p.status !== "absconded")
              .map((p) => <MenuItem key={p.id} value={p.id}>{`${p.name} (${p.employee_code})`}</MenuItem>)}
          </TextField>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
            <TextField select fullWidth label={t("emp.col.type")} value={form.employment_type ?? ""} onChange={set("employment_type")}>
              <MenuItem value="">—</MenuItem>
              {["full_time", "part_time", "contract", "intern", "consultant"].map((k) => <MenuItem key={k} value={k}>{t(`emp.type.${k}`)}</MenuItem>)}
            </TextField>
            <TextField fullWidth type="date" label={t("emp.col.joined")} value={form.joined_on ?? ""} onChange={set("joined_on")} InputLabelProps={{ shrink: true }} />
          </Stack>
          <TextField type="number" label={t("emp.edit.previous_years")} value={form.previous_years ?? ""} onChange={set("previous_years")}
            helperText={t("emp.edit.previous_hint")} inputProps={{ min: 0, max: 50, step: 0.5 }} />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
            <TextField fullWidth label={t("emp.col.phone")} value={form.phone ?? ""} onChange={set("phone")} />
            <TextField fullWidth label={t("emp.edit.personal_email")} value={form.personal_email ?? ""} onChange={set("personal_email")} />
          </Stack>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={busy || !(form.first_name ?? "").trim()}>{t("emp.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}

export function GiveAssetDialog({ employee, onClose, onDone }: { employee: { id: string; name: string } | null; onClose: () => void; onDone: (msg: string) => void }) {
  const t = useT();
  const [mode, setMode] = useState<"stock" | "new">("stock");
  const [stock, setStock] = useState<{ id: string; tag: string; name: string; category_code: string }[] | null>(null);
  const [types, setTypes] = useState<Category[]>([]);
  const [assetId, setAssetId] = useState("");
  const [form, setForm] = useState({ category_code: "", asset_tag: "", name: "", serial_number: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!employee) return;
    setError(null);
    setAssetId("");
    setForm({ category_code: "", asset_tag: "", name: "", serial_number: "" });
    employeesApi.inStock().then((s) => { setStock(s); setMode(s.length ? "stock" : "new"); }).catch(() => { setStock([]); setMode("new"); });
    serviceDeskExtra.categories("asset").then((c) => { setTypes(c); setForm((f) => ({ ...f, category_code: f.category_code || c[0]?.code || "" })); }).catch(() => setTypes([]));
  }, [employee]);
  if (!employee) return null;
  const typeLabel = (code: string) => types.find((c) => c.code === code)?.label ?? code;
  const ok = mode === "stock" ? Boolean(assetId) : Boolean(form.category_code && form.asset_tag.trim() && form.name.trim());
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await employeesApi.giveAsset(employee.id, mode === "stock" ? { asset_id: assetId } : form);
      onDone(t("emp.asset.given", { tag: r.tag, name: employee.name }));
    } catch (e) {
      setError(extractErrorMessage(e, ""));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("emp.asset.title", { name: employee.name })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <RadioGroup row value={mode} onChange={(e) => setMode(e.target.value as "stock" | "new")}>
            <FormControlLabel value="stock" control={<Radio />} label={t("emp.asset.from_stock", { n: stock?.length ?? 0 })} disabled={!stock?.length} />
            <FormControlLabel value="new" control={<Radio />} label={t("emp.asset.new")} />
          </RadioGroup>
          {mode === "stock" ? (
            <TextField select label={t("emp.asset.pick")} value={assetId} onChange={(e) => setAssetId(e.target.value)}>
              {(stock ?? []).map((a) => <MenuItem key={a.id} value={a.id}>{`${a.tag} - ${a.name} (${typeLabel(a.category_code)})`}</MenuItem>)}
            </TextField>
          ) : (
            <>
              <TextField select required label={t("assets.new.category")} value={form.category_code} onChange={(e) => setForm({ ...form, category_code: e.target.value })}
                helperText={types.length ? undefined : t("assets.types.none")}>
                {types.map((c) => <MenuItem key={c.code} value={c.code}>{c.label}</MenuItem>)}
              </TextField>
              <TextField required label={t("assets.new.tag")} value={form.asset_tag} onChange={(e) => setForm({ ...form, asset_tag: e.target.value })} />
              <TextField required label={t("assets.new.name")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              <TextField label={t("assets.new.serial")} value={form.serial_number} onChange={(e) => setForm({ ...form, serial_number: e.target.value })} />
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={busy || !ok}>{t("emp.asset.give")}</Button>
      </DialogActions>
    </Dialog>
  );
}
