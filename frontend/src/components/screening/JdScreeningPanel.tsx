import { useCallback, useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { jdScreeningApi, type JdRun, type JdRunRow } from "../../api/modulesApi";
import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";

// Part 19.1: Screening without the Jobs module -- paste (or upload) a job description and score
// the talent pool against it. Results are kept so they can be opened again.
export default function JdScreeningPanel() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [title, setTitle] = useState("");
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<JdRun | null>(null);
  const [runs, setRuns] = useState<JdRunRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);

  const loadRuns = useCallback(() => { jdScreeningApi.list().then(setRuns).catch(() => undefined); }, []);
  useEffect(loadRuns, [loadRuns]);

  const fromFile = async (picked: File | undefined) => {
    if (!picked) return;
    setError(null);
    try {
      const { text } = await jdScreeningApi.textFromFile(picked);
      setJd(text);
      if (!title) setTitle(picked.name.replace(/\.[^.]+$/, ""));
    } catch (err) {
      setError(extractErrorMessage(err, t("jd.err")));
    } finally {
      if (file.current) file.current.value = "";
    }
  };

  const score = async () => {
    setBusy(true);
    setError(null);
    try {
      setRun(await jdScreeningApi.run(title.trim(), jd.trim()));
      loadRuns();
    } catch (err) {
      setError(extractErrorMessage(err, t("jd.err")));
    } finally {
      setBusy(false);
    }
  };

  const fit = (r: JdRun["results"][number]) => {
    if (r.error) return <Chip size="small" label={t("jd.failed")} sx={{ bgcolor: f.coralSoft, color: f.coral }} />;
    const tone = r.recommendation === "strong_fit" ? { bg: f.brandSoft, fg: f.brand } : r.recommendation === "possible_fit" ? { bg: f.sunSoft, fg: f.sunInk } : { bg: f.surface2, fg: f.muted };
    return <Chip size="small" label={t(`jd.fit.${r.recommendation ?? "weak_fit"}`)} sx={{ bgcolor: tone.bg, color: tone.fg, fontWeight: 700 }} />;
  };

  return (
    <Card sx={{ p: 2.5, mt: 2 }}>
      <Stack direction="row" spacing={1.25} alignItems="center" sx={{ mb: 1 }}>
        <Emoji name="page" size={26} />
        <Box>
          <Typography variant="h6">{t("jd.title")}</Typography>
          <Typography variant="body2" sx={{ color: f.muted }}>{t("jd.intro")}</Typography>
        </Box>
      </Stack>
      <Stack spacing={1.5}>
        <TextField label={t("jd.role")} value={title} onChange={(e) => setTitle(e.target.value)} size="small" inputProps={{ maxLength: 200 }} />
        <TextField label={t("jd.text")} value={jd} onChange={(e) => setJd(e.target.value)} multiline minRows={6} maxRows={16}
          helperText={jd.trim().length > 0 && jd.trim().length < 30 ? t("jd.too_short") : t("jd.text_hint")} />
        <input ref={file} type="file" hidden accept=".pdf,.doc,.docx,.txt" onChange={(e) => void fromFile(e.target.files?.[0])} />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
          <Button variant="contained" disabled={busy || !title.trim() || jd.trim().length < 30} onClick={() => void score()}>{t("jd.score")}</Button>
          <Button variant="outlined" disabled={busy} onClick={() => file.current?.click()}>{t("jd.upload")}</Button>
        </Stack>
        {busy && <Box><Typography variant="body2" sx={{ mb: 0.5 }}>{t("jd.scoring")}</Typography><LinearProgress /></Box>}
        {error && <Alert severity="error">{error}</Alert>}
      </Stack>

      {run && (
        <Box sx={{ mt: 2.5 }}>
          <Typography sx={{ fontWeight: 700, mb: 1 }}>{t("jd.results", { title: run.title, count: run.results.length })}</Typography>
          <Box sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t("pool.col.name")}</TableCell>
                  <TableCell align="right">{t("jd.col.score")}</TableCell>
                  <TableCell>{t("jd.col.fit")}</TableCell>
                  <TableCell>{t("pool.col.location")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {run.results.map((r) => (
                  <TableRow key={r.candidate_id}>
                    <TableCell><Typography sx={{ fontWeight: 600 }}>{r.name}</Typography><Typography variant="body2" sx={{ color: f.muted }}>{r.email ?? ""}</Typography></TableCell>
                    <TableCell align="right" sx={{ fontWeight: 700, fontSize: 16 }}>{r.match_score ?? "—"}</TableCell>
                    <TableCell>{fit(r)}</TableCell>
                    <TableCell>{r.location ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        </Box>
      )}

      {runs.length > 0 && (
        <Box sx={{ mt: 2.5 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>{t("jd.earlier")}</Typography>
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            {runs.slice(0, 10).map((r) => (
              <Chip key={r.id} label={`${r.title} · ${r.candidates}`} onClick={() => jdScreeningApi.get(r.id).then(setRun).catch((err) => setError(extractErrorMessage(err, t("jd.err"))))}
                variant={run?.id === r.id ? "filled" : "outlined"} />
            ))}
          </Stack>
        </Box>
      )}
    </Card>
  );
}
