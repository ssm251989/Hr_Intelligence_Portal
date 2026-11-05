import { useCallback, useEffect, useState, type ReactNode } from "react";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useParams } from "react-router-dom";

import { apiUrl, extractErrorMessage } from "../../api/client";
import { BrandMark, LanguagePicker } from "../../components/careers/PublicAuthLayout";
import { useT } from "../../i18n";

interface Item { code: string; label: string; required: boolean; types: string[]; max_mb: number; received: boolean; reupload_note: string | null; files: number }
interface View { candidate_first_name: string; job_title: string; items: Item[]; missing: string[]; submitted: boolean }

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(apiUrl(`/api/v1/public/documents/${path}`)!, init);
  if (!r.ok) {
    let detail = r.statusText;
    try { const b = await r.json(); detail = typeof b.detail === "string" ? b.detail : detail; } catch { /* keep */ }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

// Part 18.16: the candidate's "Joining documents" page (link emailed when the salary is
// approved). One row per document from Settings; upload, see what arrived, see what HR asked
// for again and why; "Send to HR" when every required document is in.
export default function DocumentsFormPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { token = "" } = useParams();
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [done, setDone] = useState(false);

  const load = useCallback(() => {
    call<View>(encodeURIComponent(token)).then(setView).catch((e) => setError(extractErrorMessage(e, t("docform.err"))));
  }, [token, t]);
  useEffect(load, [load]);

  const upload = async (code: string, file: File) => {
    setBusy(code);
    setRowError((m) => ({ ...m, [code]: "" }));
    const form = new FormData();
    form.append("file", file);
    try { await call(`${encodeURIComponent(token)}/files/${code}`, { method: "POST", body: form }); load(); }
    catch (e) { setRowError((m) => ({ ...m, [code]: extractErrorMessage(e, t("docform.err")) })); }
    finally { setBusy(null); }
  };
  const submit = async () => {
    setBusy("submit");
    try { await call(`${encodeURIComponent(token)}/submit`, { method: "POST" }); setDone(true); load(); }
    catch (e) { setError(extractErrorMessage(e, t("docform.err"))); } finally { setBusy(null); }
  };

  const shell = (children: ReactNode) => (
    <Box sx={{ minHeight: "100vh", bgcolor: f.ground }}>
      <Box component="header" sx={{ bgcolor: f.surface, boxShadow: f.shadow }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ maxWidth: 720, mx: "auto", px: 2, py: 1.5 }}>
          <BrandMark size={34} />
          <LanguagePicker />
        </Stack>
      </Box>
      <Box sx={{ maxWidth: 720, mx: "auto", px: 2, py: 4 }}>{children}</Box>
    </Box>
  );

  if (error && !view) return shell(<Alert severity="error">{error}</Alert>);
  if (!view) return shell(<Box sx={{ display: "grid", placeItems: "center", py: 8 }}><CircularProgress /></Box>);
  const missing = view.items.filter((i) => i.required && !i.received).length;
  return shell(
    <Card sx={{ p: { xs: 2.5, sm: 4 } }}>
      <Typography component="h1" sx={{ fontWeight: 800, fontSize: { xs: 24, sm: 28 } }}>
        {view.candidate_first_name ? t("docform.hi", { name: view.candidate_first_name }) : t("docform.hi_plain")}
      </Typography>
      <Typography sx={{ color: f.muted, mt: 0.75, mb: 3 }}>{t("docform.intro", { job: view.job_title })}</Typography>
      {(done || view.submitted) && missing === 0 && <Alert severity="success" sx={{ mb: 2 }}>{t("docform.sent")}</Alert>}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Stack spacing={1.5}>
        {view.items.map((i) => (
          <Box key={i.code} sx={{ p: 1.75, borderRadius: 3, bgcolor: i.reupload_note ? f.coralSoft : i.received ? f.okSoft : f.surface2 }}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }}>
              <Box sx={{ flex: 1 }}>
                <Stack direction="row" spacing={1} alignItems="center">
                  {i.received && <CheckCircleOutlineIcon sx={{ color: f.ok }} fontSize="small" />}
                  <Typography sx={{ fontWeight: 700 }}>{i.label}</Typography>
                  <Chip size="small" label={i.required ? t("docform.required") : t("docform.optional")} variant="outlined" />
                </Stack>
                <Typography variant="caption">{t("docform.types", { types: i.types.map((x) => x.toUpperCase()).join(", "), mb: i.max_mb })}</Typography>
                {i.reupload_note && <Typography variant="body2" sx={{ color: f.coral, fontWeight: 600, mt: 0.5 }}>{t("docform.again", { note: i.reupload_note })}</Typography>}
                {i.files > 0 && !i.reupload_note && <Typography variant="body2">{t("docform.received", { count: i.files })}</Typography>}
                {rowError[i.code] && <Typography variant="body2" sx={{ color: f.coral }}>{rowError[i.code]}</Typography>}
              </Box>
              <Button variant={i.received ? "text" : "contained"} component="label" startIcon={<UploadFileOutlinedIcon />} disabled={busy !== null}>
                {busy === i.code ? t("docform.uploading") : i.received ? t("docform.add_more") : t("docform.upload")}
                <input hidden type="file" accept={i.types.map((x) => `.${x}`).join(",")}
                  onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void upload(i.code, file); }} />
              </Button>
            </Stack>
          </Box>
        ))}
      </Stack>
      <Button variant="contained" size="large" fullWidth sx={{ mt: 3 }} disabled={missing > 0 || busy !== null} onClick={submit}>
        {missing > 0 ? t("docform.missing", { count: missing }) : t("docform.submit")}
      </Button>
      <Typography sx={{ color: f.muted, fontSize: 13, textAlign: "center", mt: 1 }}>{t("docform.private")}</Typography>
    </Card>,
  );
}
