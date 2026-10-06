import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { bgvVendorApi, saveBlob, type BgvAssignment, type BgvVendor } from "../../api/bgvVendorApi";
import { useT } from "../../i18n";
import { Inset } from "../offers/shared";
import { localISO } from "../servicedesk/shared";

const OPEN = ["assigned", "in_progress", "report_received"];
const TONE: Record<string, "default" | "info" | "warning" | "success" | "error"> = {
  assigned: "info", in_progress: "warning", report_received: "success", decided: "default", cancelled: "default",
};
const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "");

// Part 21.4: on a candidate's BGV card -- Download all (ZIP + summary Excel) and the BGV vendor:
// assign (secure link emailed), status, copy link, report, reassign, cancel.
export default function BgvVendorCard({ applicationId, name, canEdit }: { applicationId: string; name: string; canEdit: boolean }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [items, setItems] = useState<BgvAssignment[]>([]);
  const [vendors, setVendors] = useState<BgvVendor[]>([]);
  const [dialog, setDialog] = useState<"assign" | "cancel" | null>(null);
  const [agencyId, setAgencyId] = useState("");
  const [checks, setChecks] = useState<Set<string>>(new Set());
  const [due, setDue] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    bgvVendorApi.assignments(applicationId).then((r) => setItems(r.items)).catch(() => setItems([]));
  }, [applicationId]);
  useEffect(() => { load(); }, [load]);

  const current = items.find((a) => OPEN.includes(a.status)) ?? null;
  const earlier = items.filter((a) => a !== current);

  const pickVendor = (id: string, list = vendors) => {
    setAgencyId(id);
    const v = list.find((x) => x.id === id);
    setChecks(new Set((v?.checks ?? []).map((c) => c.check)));
    if (v?.turnaround_days) { const d = new Date(); d.setDate(d.getDate() + v.turnaround_days); setDue(localISO(d)); }
  };
  const openAssign = async () => {
    setMsg(null);
    const r = await bgvVendorApi.vendors().catch(() => ({ items: [] as BgvVendor[] }));
    setVendors(r.items);
    const first = current?.agency_id && r.items.some((v) => v.id !== current.agency_id) ? r.items.find((v) => v.id !== current.agency_id)!.id : r.items[0]?.id ?? "";
    setDue("");
    pickVendor(first, r.items);
    setDialog("assign");
  };
  const vendor = vendors.find((v) => v.id === agencyId);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try { await fn(); } catch (err) { setMsg({ ok: false, text: extractErrorMessage(err, t("bv21.err")) }); } finally { setBusy(false); }
  };
  const assign = () => run(async () => {
    const r = await bgvVendorApi.assign(applicationId, { agency_id: agencyId, checks: [...checks], due_date: due || null });
    setDialog(null);
    setMsg({ ok: true, text: r.email ? t("bv21.sent") : t("bv21.sent_noemail") });
    load();
  });
  const cancel = () => run(async () => {
    if (!current) return;
    await bgvVendorApi.cancel(current.id, reason || undefined);
    setDialog(null); setReason(""); load();
  });
  const downloadAll = () => run(async () => {
    const blob = await bgvVendorApi.downloadAllBlob(applicationId);
    if (!blob) throw new Error(t("bv21.err"));
    saveBlob(blob, `${name} - BGV documents.zip`);
  });
  const report = (a: BgvAssignment) => run(async () => {
    const blob = await bgvVendorApi.reportBlob(a.id);
    if (!blob) throw new Error(t("bv21.err"));
    saveBlob(blob, a.report_name ?? "report.pdf");
  });

  return (
    <Inset title={t("bv21.title")}>
      <Stack spacing={1.25} data-testid={`bgv-vendor-${applicationId}`}>
        {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}
        {current ? (
          <Box>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography sx={{ fontWeight: 600 }}>{current.agency}</Typography>
              <Chip size="small" color={TONE[current.status]} label={t(`bv21.st.${current.status}`)} />
              {current.overdue && <Chip size="small" color="error" label={t("bv21.overdue")} />}
              {current.due_date && <Typography sx={{ fontSize: 13, color: f.muted }}>{t("bv21.due_on", { date: day(current.due_date) })}</Typography>}
            </Stack>
            <Typography sx={{ fontSize: 13, color: f.muted, mt: 0.5 }}>
              {current.checks.map((c) => t(`ag21.check.${c}`)).join(", ")}
            </Typography>
            {current.report_uploaded_at && (
              <Typography sx={{ fontSize: 13, mt: 0.5 }}>{t("bv21.report_on", { date: day(current.report_uploaded_at) })}{current.report_name ? ` - ${current.report_name}` : ""}</Typography>
            )}
            {current.report_note && <Typography sx={{ fontSize: 13, color: f.muted }}>{t("bv21.vendor_note", { note: current.report_note })}</Typography>}
          </Box>
        ) : (
          <Typography sx={{ fontSize: 14, color: f.muted }}>{t("bv21.none")}</Typography>
        )}
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Button size="small" variant="outlined" onClick={downloadAll} disabled={busy}>{t("bv21.download_all")}</Button>
          {current?.report_name && <Button size="small" variant="outlined" onClick={() => report(current)} disabled={busy}>{t("bv21.report")}</Button>}
          {current?.link && (
            <Button size="small" onClick={() => { void navigator.clipboard?.writeText(current.link ?? ""); setMsg({ ok: true, text: t("bv21.copied") }); }}>{t("bv21.copy_link")}</Button>
          )}
          {canEdit && (
            <Button size="small" variant={current ? "text" : "contained"} onClick={() => void openAssign()} disabled={busy}>
              {current ? t("bv21.reassign") : t("bv21.assign")}
            </Button>
          )}
          {canEdit && current && <Button size="small" color="error" onClick={() => { setReason(""); setDialog("cancel"); }} disabled={busy}>{t("bv21.cancel")}</Button>}
        </Stack>
        {earlier.length > 0 && (
          <Box>
            <Typography sx={{ fontSize: 13, fontWeight: 600, mt: 0.5 }}>{t("bv21.history")}</Typography>
            {earlier.map((a) => (
              <Stack key={a.id} direction="row" spacing={1} alignItems="center" sx={{ fontSize: 13 }}>
                <Typography sx={{ fontSize: 13 }}>{a.agency} - {t(`bv21.st.${a.status}`)}{a.decision ? ` (${a.decision})` : ""} - {day(a.created_at)}</Typography>
                {a.report_name && <Button size="small" onClick={() => report(a)}>{t("bv21.report")}</Button>}
              </Stack>
            ))}
          </Box>
        )}
      </Stack>

      <Dialog open={dialog === "assign"} onClose={() => setDialog(null)} fullWidth maxWidth="sm">
        <DialogTitle>{current ? t("bv21.reassign") : t("bv21.assign")}</DialogTitle>
        <DialogContent>
          {vendors.length === 0 ? (
            <Alert severity="info" sx={{ mt: 1 }}>{t("bv21.no_vendors")}</Alert>
          ) : (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <TextField select label={t("bv21.vendor")} value={agencyId} onChange={(e) => pickVendor(e.target.value)} size="small">
                {vendors.map((v) => <MenuItem key={v.id} value={v.id}>{v.name}{v.email ? ` (${v.email})` : ""}</MenuItem>)}
              </TextField>
              <Box>
                <Typography sx={{ fontSize: 13, fontWeight: 600 }}>{t("bv21.checks")}</Typography>
                {(vendor?.checks ?? []).map((c) => (
                  <FormControlLabel key={c.check} label={`${t(`ag21.check.${c.check}`)}${c.price != null ? ` - ${c.price}` : ""}`}
                    control={<Checkbox size="small" checked={checks.has(c.check)} onChange={(e) => setChecks((s) => {
                      const n = new Set(s); if (e.target.checked) n.add(c.check); else n.delete(c.check); return n;
                    })} />} />
                ))}
              </Box>
              <TextField type="date" label={t("bv21.due")} value={due} onChange={(e) => setDue(e.target.value)} size="small" slotProps={{ inputLabel: { shrink: true } }} />
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(null)}>{t("bv21.close")}</Button>
          <Button variant="contained" onClick={assign} disabled={busy || !agencyId || checks.size === 0}>{t("bv21.send")}</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={dialog === "cancel"} onClose={() => setDialog(null)} fullWidth maxWidth="xs">
        <DialogTitle>{t("bv21.cancel")}</DialogTitle>
        <DialogContent>
          <TextField label={t("bv21.cancel_reason")} value={reason} onChange={(e) => setReason(e.target.value)} fullWidth multiline minRows={2} sx={{ mt: 1 }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(null)}>{t("bv21.close")}</Button>
          <Button color="error" variant="contained" onClick={cancel} disabled={busy}>{t("bv21.cancel_confirm")}</Button>
        </DialogActions>
      </Dialog>
    </Inset>
  );
}
