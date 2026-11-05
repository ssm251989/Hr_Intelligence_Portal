import { useEffect, useState } from "react";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, platformSettingsApi } from "../../api/client";
import { useT } from "../../i18n";
import PlatformSettingsPanel from "../PlatformSettingsPanel";

interface Doc { code: string; label: string; required: boolean; types: string[]; max_mb: number; job_types?: string[] }
const KEY = "recruitment.documents.required";
const ALL_TYPES = ["pdf", "jpg", "png", "docx"];

// Part 18.16: Settings > Hiring > Required documents -- the list the candidate is asked for after
// the salary is approved: each document required/optional, allowed file types, max size, and
// (optionally) only for some job types. Plus the auto-send and reminder settings.
export default function RequiredDocumentsPage() {
  const t = useT();
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    Promise.all([platformSettingsApi.values(), platformSettingsApi.definitions("recruitment")]).then(([vals, defs]) => {
      const v = vals.find((x) => x.key === KEY)?.value ?? defs.find((d) => d.key === KEY)?.default;
      setDocs(Array.isArray(v) ? (v as Doc[]) : []);
    }).catch((err) => setMsg({ ok: false, text: extractErrorMessage(err, t("reqdocs.err")) }));
  }, [t]);

  const change = (i: number, patch: Partial<Doc>) => setDocs((d) => (d ?? []).map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const save = async () => {
    if (!docs) return;
    const clean = docs.filter((d) => d.label.trim()).map((d) => ({
      ...d, label: d.label.trim(), code: d.code || d.label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40),
      types: d.types.length ? d.types : ["pdf"], max_mb: Math.max(1, Math.min(50, Number(d.max_mb) || 5)),
      job_types: d.job_types?.length ? d.job_types : undefined,
    }));
    try {
      await platformSettingsApi.update(KEY, clean);
      setDocs(clean);
      setMsg({ ok: true, text: t("reqdocs.saved") });
    } catch (err) { setMsg({ ok: false, text: extractErrorMessage(err, t("reqdocs.err")) }); }
  };

  return (
    <Stack spacing={2}>
      <Card>
        <CardContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t("reqdocs.intro")}</Typography>
          {msg && <Alert severity={msg.ok ? "success" : "error"} sx={{ mb: 1.5 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}
          {docs && (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t("reqdocs.col.document")}</TableCell>
                    <TableCell>{t("reqdocs.col.required")}</TableCell>
                    <TableCell>{t("reqdocs.col.types")}</TableCell>
                    <TableCell>{t("reqdocs.col.size")}</TableCell>
                    <TableCell>{t("reqdocs.col.job_types")}</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {docs.map((d, i) => (
                    <TableRow key={i}>
                      <TableCell><TextField size="small" value={d.label} onChange={(e) => change(i, { label: e.target.value })} sx={{ minWidth: 200 }} /></TableCell>
                      <TableCell><Switch checked={d.required} onChange={(e) => change(i, { required: e.target.checked })} /></TableCell>
                      <TableCell>
                        {ALL_TYPES.map((ty) => (
                          <FormControlLabel key={ty} label={ty.toUpperCase()} sx={{ mr: 1 }}
                            control={<Checkbox size="small" checked={d.types.includes(ty)}
                              onChange={(e) => change(i, { types: e.target.checked ? [...d.types, ty] : d.types.filter((x) => x !== ty) })} />} />
                        ))}
                      </TableCell>
                      <TableCell><TextField size="small" type="number" value={d.max_mb} onChange={(e) => change(i, { max_mb: Number(e.target.value) })} sx={{ width: 80 }}
                        slotProps={{ htmlInput: { min: 1, max: 50 } }} /></TableCell>
                      <TableCell><TextField size="small" placeholder={t("reqdocs.all_jobs")} value={(d.job_types ?? []).join(", ")}
                        onChange={(e) => change(i, { job_types: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} sx={{ minWidth: 160 }} /></TableCell>
                      <TableCell><IconButton aria-label={t("reqdocs.remove")} onClick={() => setDocs((x) => (x ?? []).filter((_y, j) => j !== i))}><DeleteOutlineIcon fontSize="small" /></IconButton></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
          <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
            <Button onClick={() => setDocs((d) => [...(d ?? []), { code: "", label: "", required: true, types: ["pdf", "jpg", "png"], max_mb: 5 }])}>{t("reqdocs.add")}</Button>
            <Button variant="contained" onClick={save} disabled={!docs}>{t("lock.save")}</Button>
          </Stack>
        </CardContent>
      </Card>
      <PlatformSettingsPanel prefixes={["recruitment.documents.auto_send", "recruitment.documents.reminder_hours"]} title={t("reqdocs.when")} />
    </Stack>
  );
}
