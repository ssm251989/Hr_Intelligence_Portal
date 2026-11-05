import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useParams } from "react-router-dom";

import { extractErrorMessage } from "../../api/client";
import { bgvVendorApi, type VendorView } from "../../api/bgvVendorApi";
import { LanguagePicker } from "../../components/careers/PublicAuthLayout";
import { useT } from "../../i18n";

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "");

// Part 21.4: the BGV vendor's secure link (/bgv-vendor/:token). Public -- no login. The vendor sees
// the candidate, the checks asked for, the due date and the documents; uploads one report (+ note).
export default function BgvVendorPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { token = "" } = useParams<{ token: string }>();
  const [view, setView] = useState<VendorView | null>(null);
  const [gone, setGone] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    bgvVendorApi.vendorView(token).then(setView).catch(() => setGone(true));
  }, [token]);
  useEffect(() => { load(); }, [load]);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    try {
      await bgvVendorApi.vendorReport(token, file, note);
      setMsg({ ok: true, text: t("bvp.uploaded") }); setFile(null); setNote(""); load();
    } catch (err) {
      setMsg({ ok: false, text: extractErrorMessage(err, t("bv21.err")) });
    } finally { setBusy(false); }
  };

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default", px: 2, py: 4 }}>
      <Box sx={{ maxWidth: 720, mx: "auto" }}>
        <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1 }}><LanguagePicker /></Stack>
        {gone ? (
          <Card sx={{ p: 3 }}><Alert severity="warning">{t("bvp.expired")}</Alert></Card>
        ) : !view ? (
          <Box sx={{ display: "grid", placeItems: "center", py: 8 }}><CircularProgress /></Box>
        ) : (
          <Card sx={{ p: 3 }}>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>{t("bvp.title")}</Typography>
            {view.company && <Typography sx={{ color: f.muted }}>{t("bvp.from", { company: view.company })}{view.vendor ? ` - ${view.vendor}` : ""}</Typography>}
            <Stack spacing={0.5} sx={{ mt: 2 }}>
              <Typography><b>{t("bvp.candidate")}:</b> {view.candidate}</Typography>
              {view.job_title && <Typography><b>{t("bvp.job")}:</b> {view.job_title}</Typography>}
              {view.due_date && <Typography sx={{ fontWeight: 600 }}>{t("bvp.due", { date: day(view.due_date) })}</Typography>}
            </Stack>
            <Typography sx={{ fontWeight: 600, mt: 2 }}>{t("bvp.checks")}</Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
              {view.checks.map((c) => <Chip key={c} label={t(`ag21.check.${c}`)} />)}
            </Stack>

            <Typography sx={{ fontWeight: 600, mt: 2.5 }}>{t("bvp.docs")}</Typography>
            <Stack spacing={0.75} sx={{ mt: 0.5 }}>
              {view.documents.map((d) => (
                <Stack key={d.id} direction="row" spacing={1.5} alignItems="center" justifyContent="space-between"
                  sx={{ p: 1, borderRadius: "8px", border: `1px solid ${f.line}` }}>
                  <Typography sx={{ fontSize: 14 }}>{d.label}</Typography>
                  {d.available
                    ? <Button size="small" href={bgvVendorApi.vendorFileUrl(token, d.id)} target="_blank" rel="noopener">{t("bvp.download")}</Button>
                    : <Typography sx={{ fontSize: 13, color: f.muted }}>{t("bvp.missing")}</Typography>}
                </Stack>
              ))}
            </Stack>

            <Typography sx={{ fontWeight: 600, mt: 2.5 }}>{t("bvp.upload_title")}</Typography>
            {view.report && <Alert severity="success" sx={{ mt: 1 }}>{t("bvp.report_on", { name: view.report.name })} - {day(view.report.uploaded_at)}</Alert>}
            {msg && <Alert severity={msg.ok ? "success" : "error"} sx={{ mt: 1 }}>{msg.text}</Alert>}
            {view.can_upload && (
              <Stack spacing={1.5} sx={{ mt: 1.5 }}>
                {view.report && <Typography sx={{ fontSize: 13, color: f.muted }}>{t("bvp.replace")}</Typography>}
                <Button variant="outlined" component="label" sx={{ alignSelf: "flex-start" }}>
                  {file ? file.name : t("bvp.choose")}
                  <input hidden type="file" aria-label={t("bvp.choose")} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                </Button>
                <TextField label={t("bvp.note")} value={note} onChange={(e) => setNote(e.target.value)} multiline minRows={2} />
                <Button variant="contained" onClick={upload} disabled={!file || busy} sx={{ alignSelf: "flex-start" }}>{t("bvp.upload")}</Button>
              </Stack>
            )}
            <Typography sx={{ fontSize: 12, color: f.muted, mt: 2.5 }}>{t("bvp.expires", { date: day(view.link_expires_at) })}</Typography>
          </Card>
        )}
      </Box>
    </Box>
  );
}
