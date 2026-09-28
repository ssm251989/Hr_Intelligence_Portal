import { useCallback, useEffect, useState } from "react";
import EventAvailableOutlinedIcon from "@mui/icons-material/EventAvailableOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useParams } from "react-router-dom";

import { apiUrl, extractErrorMessage } from "../../api/client";
import { BrandMark, LanguagePicker } from "../../components/careers/PublicAuthLayout";
import { useT } from "../../i18n";

interface View { candidate_first_name: string; job_title: string; dates: string[]; chosen: string | null; note: string | null }

// Part 18.19: the candidate picks one of the 3 joining dates HR proposed -- one click.
export default function JoiningDatePage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { token = "" } = useParams();
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const url = apiUrl(`/api/v1/public/joining/${encodeURIComponent(token)}`)!;
  const load = useCallback(async () => {
    try {
      const r = await fetch(url);
      const b = await r.json();
      if (!r.ok) throw new Error(typeof b.detail === "string" ? b.detail : t("joinpick.err"));
      setView(b);
    } catch (e) { setError(extractErrorMessage(e, t("joinpick.err"))); }
  }, [url, t]);
  useEffect(() => { void load(); }, [load]);

  const choose = async (d: string) => {
    setBusy(d); setError(null);
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date: d }) });
      const b = await r.json();
      if (!r.ok) throw new Error(typeof b.detail === "string" ? b.detail : t("joinpick.err"));
      await load();
    } catch (e) { setError(extractErrorMessage(e, t("joinpick.err"))); } finally { setBusy(null); }
  };
  const nice = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: f.ground }}>
      <Box component="header" sx={{ bgcolor: f.surface, boxShadow: f.shadow }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ maxWidth: 640, mx: "auto", px: 2, py: 1.5 }}>
          <BrandMark size={34} /><LanguagePicker />
        </Stack>
      </Box>
      <Box sx={{ maxWidth: 640, mx: "auto", px: 2, py: 4 }}>
        {!view && !error && <Box sx={{ display: "grid", placeItems: "center", py: 8 }}><CircularProgress /></Box>}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {view && (
          <Card sx={{ p: { xs: 2.5, sm: 4 } }}>
            <Typography component="h1" sx={{ fontWeight: 800, fontSize: { xs: 24, sm: 28 } }}>{t("joinpick.title", { name: view.candidate_first_name })}</Typography>
            <Typography sx={{ color: f.muted, mt: 0.75, mb: 3 }}>{t("joinpick.intro", { job: view.job_title })}</Typography>
            {view.note && <Alert severity="info" sx={{ mb: 2 }}>{view.note}</Alert>}
            {view.chosen ? (
              <Alert severity="success" icon={<EventAvailableOutlinedIcon />}>{t("joinpick.done", { date: nice(view.chosen) })}</Alert>
            ) : (
              <Stack spacing={1.5}>
                {view.dates.map((d) => (
                  <Button key={d} variant="outlined" size="large" disabled={busy !== null} onClick={() => choose(d)} sx={{ justifyContent: "flex-start", py: 1.5 }}
                    startIcon={<EventAvailableOutlinedIcon />}>{busy === d ? t("joinpick.saving") : nice(d)}</Button>
                ))}
              </Stack>
            )}
          </Card>
        )}
      </Box>
    </Box>
  );
}
