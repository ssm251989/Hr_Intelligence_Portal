// Part 21.5: add or edit an agency -- Recruitment / BGV / Both. Common details, then the recruitment part (fee, payment
// terms) and/or the BGV part (checks offered + price, turnaround days, report format).
import { useEffect, useState } from "react";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { agencyApi, BGV_CHECKS, type AgencyInput, type AgencyRow, type AgencyType } from "../../api/agencyApi";
import { useT } from "../../i18n";
import { FriendlyError } from "../../ui-kit";

const empty: AgencyInput = { name: "", agency_type: "recruitment", bgv_checks: [] };

export default function AgencyFormDialog({ open, agency, onClose, onSaved }: { open: boolean; agency?: AgencyRow | null; onClose: () => void; onSaved: (a: AgencyRow) => void }) {
  const t = useT();
  const [v, setV] = useState<AgencyInput>(empty);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (!open) return;
    setError(null);
    setV(agency ? {
      name: agency.name, contact_email: agency.contact_email ?? "", notes: agency.notes ?? "", agency_type: agency.agency_type, contact_person: agency.contact_person ?? "",
      phone: agency.phone ?? "", address: agency.address ?? "", gst_pan: agency.gst_pan ?? "", contract_start: agency.contract_start ?? "", contract_end: agency.contract_end ?? "",
      fee_type: agency.fee_type ?? "", fee_value: agency.fee_value ?? undefined, payment_terms: agency.payment_terms ?? "", bgv_checks: agency.bgv_checks ?? [],
      turnaround_days: agency.turnaround_days ?? undefined, report_format: agency.report_format ?? "",
    } : empty);
  }, [open, agency]);
  const set = (p: Partial<AgencyInput>) => setV((cur) => ({ ...cur, ...p }));
  const isRec = v.agency_type !== "bgv";
  const isBgv = v.agency_type !== "recruitment";
  const checks = v.bgv_checks ?? [];
  const toggleCheck = (code: string, on: boolean) => set({ bgv_checks: on ? [...checks, { check: code, price: null }] : checks.filter((c) => c.check !== code) });
  const setPrice = (code: string, price: string) => set({ bgv_checks: checks.map((c) => (c.check === code ? { ...c, price: price === "" ? null : Number(price) } : c)) });
  const save = async () => {
    setSaving(true);
    setError(null);
    const payload: AgencyInput = {
      ...v, name: v.name.trim(), contact_email: v.contact_email?.trim() || null, contract_start: v.contract_start || null, contract_end: v.contract_end || null,
      fee_type: isRec ? (v.fee_type || null) : null, fee_value: isRec && v.fee_value != null && String(v.fee_value) !== "" ? Number(v.fee_value) : null,
      bgv_checks: isBgv ? checks : [], turnaround_days: isBgv && v.turnaround_days != null && String(v.turnaround_days) !== "" ? Number(v.turnaround_days) : null,
    };
    try {
      onSaved(agency ? await agencyApi.update(agency.id, payload) : await agencyApi.create(payload));
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open={open} onClose={saving ? undefined : onClose} fullWidth maxWidth="md" aria-labelledby="agency-form-title">
      <DialogTitle id="agency-form-title">{t(agency ? "ag21.edit_title" : "agencies.add.title")}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
            <TextField required autoFocus label={t("agencies.field.name")} value={v.name} onChange={(e) => set({ name: e.target.value })} sx={{ flex: 2 }} inputProps={{ maxLength: 255 }} />
            <TextField select label={t("ag21.type")} value={v.agency_type} onChange={(e) => set({ agency_type: e.target.value as AgencyType })} sx={{ flex: 1, minWidth: 180 }}>
              {(["recruitment", "bgv", "both"] as AgencyType[]).map((x) => <MenuItem key={x} value={x}>{t(`ag21.type.${x}`)}</MenuItem>)}
            </TextField>
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
            <TextField label={t("ag21.contact_person")} value={v.contact_person ?? ""} onChange={(e) => set({ contact_person: e.target.value })} sx={{ flex: 1 }} />
            <TextField type="email" label={t("agencies.field.contact")} value={v.contact_email ?? ""} onChange={(e) => set({ contact_email: e.target.value })} sx={{ flex: 1 }} />
            <TextField label={t("ag21.phone")} value={v.phone ?? ""} onChange={(e) => set({ phone: e.target.value })} sx={{ flex: 1 }} />
          </Stack>
          <TextField label={t("ag21.address")} value={v.address ?? ""} onChange={(e) => set({ address: e.target.value })} multiline minRows={2} />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
            <TextField label={t("ag21.gst_pan")} value={v.gst_pan ?? ""} onChange={(e) => set({ gst_pan: e.target.value })} sx={{ flex: 1 }} />
            <TextField type="date" label={t("ag21.contract_start")} value={v.contract_start ?? ""} onChange={(e) => set({ contract_start: e.target.value })} InputLabelProps={{ shrink: true }} sx={{ flex: 1 }} />
            <TextField type="date" label={t("ag21.contract_end")} value={v.contract_end ?? ""} onChange={(e) => set({ contract_end: e.target.value })} InputLabelProps={{ shrink: true }} sx={{ flex: 1 }} />
          </Stack>
          {isRec && (
            <Stack spacing={1.5} data-testid="agency-recruitment-fields">
              <Typography sx={{ fontWeight: 800 }}>{t("ag21.rec_title")}</Typography>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
                <TextField select label={t("ag21.fee_type")} value={v.fee_type ?? ""} onChange={(e) => set({ fee_type: e.target.value })} sx={{ minWidth: 200 }}>
                  <MenuItem value="">{t("ag21.fee.none")}</MenuItem>
                  <MenuItem value="percent">{t("ag21.fee.percent")}</MenuItem>
                  <MenuItem value="fixed">{t("ag21.fee.fixed")}</MenuItem>
                </TextField>
                <TextField type="number" label={t(v.fee_type === "percent" ? "ag21.fee_value_pct" : "ag21.fee_value")} value={v.fee_value ?? ""} disabled={!v.fee_type}
                  onChange={(e) => set({ fee_value: e.target.value === "" ? undefined : Number(e.target.value) })} inputProps={{ min: 0 }} />
                <TextField label={t("ag21.payment_terms")} value={v.payment_terms ?? ""} onChange={(e) => set({ payment_terms: e.target.value })} sx={{ flex: 1 }} />
              </Stack>
              <Typography sx={{ fontSize: 13, color: "text.secondary" }}>{t("ag21.rec_hint")}</Typography>
            </Stack>
          )}
          {isBgv && (
            <Stack spacing={1} data-testid="agency-bgv-fields">
              <Typography sx={{ fontWeight: 800 }}>{t("ag21.bgv_title")}</Typography>
              {BGV_CHECKS.map((code) => {
                const c = checks.find((x) => x.check === code);
                return (
                  <Stack key={code} direction="row" spacing={1.5} alignItems="center">
                    <Checkbox checked={Boolean(c)} onChange={(e) => toggleCheck(code, e.target.checked)} inputProps={{ "aria-label": t(`ag21.check.${code}`) }} />
                    <Typography sx={{ flex: 1 }}>{t(`ag21.check.${code}`)}</Typography>
                    <TextField size="small" type="number" label={t("ag21.price")} value={c?.price ?? ""} disabled={!c} onChange={(e) => setPrice(code, e.target.value)} sx={{ width: 140 }} />
                  </Stack>
                );
              })}
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
                <TextField type="number" label={t("ag21.turnaround")} value={v.turnaround_days ?? ""} onChange={(e) => set({ turnaround_days: e.target.value === "" ? undefined : Number(e.target.value) })}
                  inputProps={{ min: 0, max: 365 }} sx={{ width: 220 }} />
                <TextField label={t("ag21.report_format")} placeholder={t("ag21.report_format_ph")} value={v.report_format ?? ""} onChange={(e) => set({ report_format: e.target.value })} sx={{ flex: 1 }} />
              </Stack>
            </Stack>
          )}
          <TextField label={t("agencies.field.notes")} value={v.notes ?? ""} onChange={(e) => set({ notes: e.target.value })} multiline minRows={2} />
          {error ? <FriendlyError error={error} compact /> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>{t("agency.common.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={saving || !v.name.trim()}>{saving ? t("agencies.saving") : t(agency ? "ag21.save" : "agencies.add.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}
