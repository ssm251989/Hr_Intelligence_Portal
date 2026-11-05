import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { peopleApi, type SensitiveField as FieldKey } from "../../api/peopleApi";
import { useT } from "../../i18n";
import { FriendlyError, InfoTip, StatusChip } from "../../ui-kit";

// E6: PAN / Aadhaar / bank account are shown masked. "Reveal" calls the existing encrypted-field
// endpoint, which writes an audit entry for every reveal; the plain value is hidden again after
// 30 seconds and never kept anywhere but this component's state.

const REVEAL_SECONDS = 30;
const PATTERNS: Partial<Record<FieldKey, RegExp>> = {
  pan: /^[A-Z]{5}[0-9]{4}[A-Z]$/,
  aadhaar: /^[0-9]{12}$/,
  bank_account: /^[0-9]{9,18}$/,
};

export default function SensitiveField({
  employeeId, field, present, masked, canReveal, canEdit, onSaved,
}: {
  employeeId: string;
  field: FieldKey;
  present: boolean;
  masked: string | null;
  canReveal: boolean;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [value, setValue] = useState<string | null>(null);
  const [left, setLeft] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [editOpen, setEditOpen] = useState(false);

  useEffect(() => {
    if (value === null) return;
    if (left <= 0) {
      setValue(null);
      return;
    }
    const id = window.setTimeout(() => setLeft((s) => s - 1), 1000);
    return () => window.clearTimeout(id);
  }, [value, left]);

  const reveal = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await peopleApi.reveal(employeeId, field);
      setValue(res.value ?? "");
      setLeft(REVEAL_SECONDS);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const label = t(`people.sensitive.${field}`);
  return (
    <Box sx={{ p: 1.5, borderRadius: "12px", bgcolor: f.surface2, border: `1px solid ${f.line}` }}>
      <Typography component="div" sx={{ fontSize: 12, fontWeight: 700, color: f.muted, textTransform: "uppercase", letterSpacing: 0.4, display: "flex", alignItems: "center" }}>
        {label}
        <InfoTip text={t("people.sensitive.tip")} />
      </Typography>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5, flexWrap: "wrap", rowGap: 1 }}>
        <Typography sx={{ fontWeight: 700, fontVariantNumeric: "tabular-nums", letterSpacing: value ? 0.5 : 1.5, flex: 1, minWidth: 120 }} aria-live="polite">
          {!present ? <Box component="span" sx={{ color: f.muted, letterSpacing: 0, fontWeight: 500 }}>{t("people.sensitive.not_added")}</Box> : value ?? masked ?? "••••••••"}
        </Typography>
        {present && canReveal && (value === null ? (
          <Button size="small" variant="outlined" onClick={reveal} disabled={busy} aria-label={t("people.sensitive.reveal_aria", { field: label })}>
            {busy ? t("people.sensitive.revealing") : t("people.sensitive.reveal")}
          </Button>
        ) : (
          <Button size="small" onClick={() => setValue(null)}>{t("people.sensitive.hide", { count: left })}</Button>
        ))}
        {canEdit && (
          <Button size="small" onClick={() => setEditOpen(true)}>{present ? t("people.sensitive.change") : t("people.sensitive.add")}</Button>
        )}
      </Stack>
      {present && !canReveal && <Typography sx={{ fontSize: 12, color: f.muted, mt: 0.5 }}>{t("people.sensitive.no_reveal")}</Typography>}
      {error != null && <Box sx={{ mt: 1 }}><FriendlyError compact error={error} what={t("people.sensitive.reveal_failed")} /></Box>}
      <EditSensitiveDialog open={editOpen} employeeId={employeeId} field={field} label={label} onClose={() => setEditOpen(false)} onSaved={() => { setEditOpen(false); setValue(null); onSaved(); }} />
    </Box>
  );
}

function EditSensitiveDialog({ open, employeeId, field, label, onClose, onSaved }: { open: boolean; employeeId: string; field: FieldKey; label: string; onClose: () => void; onSaved: () => void }) {
  const t = useT();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (open) {
      setValue("");
      setError(null);
    }
  }, [open]);
  const clean = field === "pan" ? value.trim().toUpperCase() : value.replace(/[\s-]/g, "");
  const pattern = PATTERNS[field];
  const invalid = clean.length > 0 && pattern ? !pattern.test(clean) : false;
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await peopleApi.setSensitive(employeeId, field, clean);
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{t("people.sensitive.edit_title", { field: label })}</DialogTitle>
      <DialogContent>
        <Typography sx={{ mb: 2, fontSize: 14 }}>{t("people.sensitive.edit_intro")}</Typography>
        <TextField
          autoFocus fullWidth label={label} value={value} onChange={(e) => setValue(e.target.value)}
          placeholder={t(`people.sensitive.${field}_placeholder`)}
          helperText={invalid ? t(`people.sensitive.${field}_invalid`) : t(`people.sensitive.${field}_hint`)}
          error={invalid} autoComplete="off"
        />
        {error != null && <Box sx={{ mt: 2 }}><FriendlyError compact error={error} /></Box>}
        <Box sx={{ mt: 2 }}><StatusChip tone="brand" emoji="lock" label={t("people.sensitive.saved_now")} /></Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("action.cancel")}</Button>
        <Button variant="contained" onClick={save} disabled={busy || !clean || invalid}>{busy ? t("people.saving") : t("action.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}
