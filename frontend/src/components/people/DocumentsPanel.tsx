import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
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

import { peopleApi, type DocumentRow } from "../../api/peopleApi";
import { useT } from "../../i18n";
import { EmptyState, FriendlyError, InfoTip, StatusChip } from "../../ui-kit";
import { SectionCard, useFormatDate } from "./shared";

// Documents tab: the employee's document register (type, dates, who can see it) with expiry
// status. Adding one records it in the register through the existing Core HR API.

const DOC_TYPES = ["id_proof", "address_proof", "education", "experience", "passport", "visa", "contract", "other"];
const VISIBILITY = ["hr", "manager", "employee"];

function expiryChip(expiry: string | null, t: (k: string, v?: Record<string, string | number>) => string) {
  if (!expiry) return <StatusChip tone="muted" emoji="check" label={t("people.docs.no_expiry")} />;
  const days = Math.ceil((new Date(`${expiry}T00:00:00`).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return <StatusChip status="overdue" label={t("people.docs.expired")} />;
  if (days <= 30) return <StatusChip status="due_soon" label={t("people.docs.expires_in", { count: days })} />;
  return <StatusChip tone="ok" emoji="check" label={t("people.docs.valid")} />;
}

export default function DocumentsPanel({ employeeId, canAdd }: { employeeId: string; canAdd: boolean }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const fmt = useFormatDate();
  const [docs, setDocs] = useState<DocumentRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState(false);

  const load = () => {
    setError(null);
    peopleApi.documents(employeeId).then(setDocs).catch(setError);
  };
  useEffect(load, [employeeId]);

  const typeName = (k: string) => {
    const v = t(`people.doc_type.${k}`);
    return v === `people.doc_type.${k}` ? k.replace(/[_-]+/g, " ") : v;
  };

  return (
    <SectionCard emoji="file_folder" title={t("people.docs.title", { count: docs?.length ?? 0 })}
      action={canAdd ? <Button variant="outlined" size="small" onClick={() => setOpen(true)}>{t("people.docs.add")}</Button> : undefined}>
      {error != null ? <FriendlyError compact error={error} what={t("people.docs.load_failed")} onRetry={load} />
        : docs === null ? <Skeleton variant="rounded" height={120} />
          : docs.length === 0 ? (
            <EmptyState compact illustration="files-uploading" title={t("people.docs.none")}
              action={canAdd ? <Button variant="contained" onClick={() => setOpen(true)}>{t("people.docs.add_first")}</Button> : undefined} />
          ) : (
            <TableContainer sx={{ border: `1px solid ${f.line}`, borderRadius: "12px" }}>
              <Table size="small" aria-label={t("people.docs.table")}>
                <TableHead>
                  <TableRow>
                    <TableCell>{t("people.docs.col.type")}</TableCell>
                    <TableCell>{t("people.docs.col.issued")}</TableCell>
                    <TableCell>{t("people.docs.col.expiry")}</TableCell>
                    <TableCell>{t("people.docs.col.status")}</TableCell>
                    <TableCell>{t("people.docs.col.visibility")}<InfoTip text={t("people.docs.visibility_tip")} /></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {docs.map((d) => (
                    <TableRow key={d.id} hover>
                      <TableCell sx={{ fontWeight: 700 }}>{typeName(d.type)}</TableCell>
                      <TableCell>{fmt(d.issued_date)}</TableCell>
                      <TableCell>{fmt(d.expiry_date)}</TableCell>
                      <TableCell>{expiryChip(d.expiry_date, t)}</TableCell>
                      <TableCell>{t(`people.visibility.${d.visibility}`)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
      <AddDocumentDialog open={open} employeeId={employeeId} typeName={typeName} onClose={() => setOpen(false)} onSaved={() => { setOpen(false); load(); }} />
    </SectionCard>
  );
}

function AddDocumentDialog({ open, employeeId, typeName, onClose, onSaved }: { open: boolean; employeeId: string; typeName: (k: string) => string; onClose: () => void; onSaved: () => void }) {
  const t = useT();
  const [type, setType] = useState("id_proof");
  const [issued, setIssued] = useState("");
  const [expiry, setExpiry] = useState("");
  const [visibility, setVisibility] = useState("hr");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (open) {
      setType("id_proof");
      setIssued("");
      setExpiry("");
      setVisibility("hr");
      setError(null);
    }
  }, [open]);
  const badDates = Boolean(issued && expiry && expiry < issued);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await peopleApi.addDocument(employeeId, { doc_type: type, issued_date: issued || undefined, expiry_date: expiry || undefined, visibility });
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("people.docs.add_title")}</DialogTitle>
      <DialogContent>
        <Typography sx={{ mb: 2, fontSize: 14 }}>{t("people.docs.add_intro")}</Typography>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select fullWidth label={t("people.docs.col.type")} value={type} onChange={(e) => setType(e.target.value)} helperText={t("people.docs.type_hint")}>
              {DOC_TYPES.map((k) => <MenuItem key={k} value={k}>{typeName(k)}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select fullWidth label={t("people.docs.col.visibility")} value={visibility} onChange={(e) => setVisibility(e.target.value)} helperText={t("people.docs.visibility_hint")}>
              {VISIBILITY.map((k) => <MenuItem key={k} value={k}>{t(`people.visibility.${k}`)}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField type="date" fullWidth label={t("people.docs.col.issued")} value={issued} onChange={(e) => setIssued(e.target.value)} helperText={t("people.docs.issued_hint")} slotProps={{ inputLabel: { shrink: true } }} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField type="date" fullWidth label={t("people.docs.col.expiry")} value={expiry} onChange={(e) => setExpiry(e.target.value)} error={badDates}
              helperText={badDates ? t("people.docs.bad_dates") : t("people.docs.expiry_hint")} slotProps={{ inputLabel: { shrink: true } }} />
          </Grid>
        </Grid>
        {error != null && <Box sx={{ mt: 2 }}><FriendlyError compact error={error} /></Box>}
      </DialogContent>
      <DialogActions>
        <Stack direction="row" spacing={1}>
          <Button onClick={onClose}>{t("action.cancel")}</Button>
          <Button variant="contained" onClick={save} disabled={busy || badDates}>{busy ? t("people.saving") : t("people.docs.save")}</Button>
        </Stack>
      </DialogActions>
    </Dialog>
  );
}
