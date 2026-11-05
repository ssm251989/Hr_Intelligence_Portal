import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Link as RouterLink } from "react-router-dom";

import { candidatesApi, extractErrorMessage } from "../api/client";
import type { CandidateRead } from "../api/types";
import { useModuleActive } from "../components/modules/ByModule";
import { useT } from "../i18n";
import { EmptyState, PageHeader } from "../ui-kit";

// Part 19.1: Candidates without the Jobs module -- one talent pool. Resumes are uploaded (one or
// many) and read by AI straight away; no job is needed and no job fields are shown.
const ACCEPT = ".pdf,.doc,.docx,.png,.jpg,.jpeg";

export default function TalentPoolPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const screeningOn = useModuleActive("screening");
  const [rows, setRows] = useState<CandidateRead[] | null>(null);
  const [q, setQ] = useState("");
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    candidatesApi.list().then(setRows).catch((err) => setError(extractErrorMessage(err, t("pool.err"))));
  }, [t]);
  useEffect(load, [load]);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    const list = Array.from(files);
    setProblems([]);
    setProgress({ done: 0, total: list.length });
    const bad: string[] = [];
    for (const [i, file] of list.entries()) {
      try {
        const c = await candidatesApi.upload(file, "manual");
        try {
          await candidatesApi.parseResume(c.id);
        } catch (err) {
          bad.push(t("pool.parse_failed", { file: file.name, reason: extractErrorMessage(err, "") }));
        }
      } catch (err) {
        bad.push(`${file.name}: ${extractErrorMessage(err, t("pool.err"))}`);
      }
      setProgress({ done: i + 1, total: list.length });
    }
    setProblems(bad);
    setProgress(null);
    if (input.current) input.current.value = "";
    load();
  };

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle || !rows) return rows ?? [];
    return rows.filter((c) => [c.full_name, c.email, c.location, ...(c.parsed_fields?.skills ?? [])].some((v) => (v ?? "").toLowerCase().includes(needle)));
  }, [rows, q]);

  return (
    <Box>
      <PageHeader emoji="technologist" title={t("pool.title")} purpose={t("pool.purpose")}
        primary={<Button variant="contained" disabled={progress !== null} onClick={() => input.current?.click()}>{t("pool.upload")}</Button>}
        extra={screeningOn ? <Button component={RouterLink} to="/screening/dashboard">{t("pool.score_link")}</Button> : undefined} />
      <input ref={input} type="file" multiple accept={ACCEPT} hidden onChange={(e) => void upload(e.target.files)} />

      {progress && (
        <Card sx={{ p: 2, mb: 2 }}>
          <Typography variant="body2" sx={{ mb: 1 }}>{t("pool.uploading", { done: progress.done, total: progress.total })}</Typography>
          <LinearProgress variant="determinate" value={(progress.done / progress.total) * 100} />
        </Card>
      )}
      {problems.length > 0 && <Alert severity="warning" sx={{ mb: 2 }} onClose={() => setProblems([])}>{problems.map((p) => <div key={p}>{p}</div>)}</Alert>}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Card>
        <Box sx={{ p: 2 }}>
          <TextField size="small" placeholder={t("pool.search")} value={q} onChange={(e) => setQ(e.target.value)} sx={{ width: { xs: "100%", sm: 320 } }} />
        </Box>
        {rows && rows.length === 0 ? (
          <EmptyState illustration="void" title={t("pool.empty")} />
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t("pool.col.name")}</TableCell>
                  <TableCell>{t("pool.col.experience")}</TableCell>
                  <TableCell>{t("pool.col.skills")}</TableCell>
                  <TableCell>{t("pool.col.location")}</TableCell>
                  <TableCell>{t("pool.col.added")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(rows === null ? [] : shown).map((c) => (
                  <TableRow key={c.id} hover>
                    <TableCell>
                      <Typography sx={{ fontWeight: 600 }}>{c.full_name || t("pool.unnamed")}</Typography>
                      <Typography variant="body2" sx={{ color: f.muted }}>{c.email || "—"}</Typography>
                    </TableCell>
                    <TableCell>
                      {c.parsed_fields
                        ? (c.parsed_fields.total_experience_years != null ? t("pool.years", { n: c.parsed_fields.total_experience_years }) : "—")
                        : <Chip size="small" label={t("pool.not_read")} sx={{ bgcolor: f.sunSoft, color: f.sunInk }} />}
                    </TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
                        {(c.parsed_fields?.skills ?? []).slice(0, 5).map((s) => <Chip key={s} size="small" label={s} variant="outlined" />)}
                      </Stack>
                    </TableCell>
                    <TableCell>{c.location || "—"}</TableCell>
                    <TableCell>{new Date(c.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
        {rows === null && !error && <LinearProgress />}
      </Card>
    </Box>
  );
}
