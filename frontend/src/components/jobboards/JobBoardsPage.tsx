import { useCallback, useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { candidatesApi, extractErrorMessage, http } from "../../api/client";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";
import ConfirmDialog from "../ConfirmDialog";

export type BoardCode = "linkedin" | "naukri" | "indeed" | "monster" | "shine";
interface Board {
  code: BoardCode; needs: string; fields: string[]; saved: boolean; api_ready: boolean; connected: boolean;
  state: "connected" | "saved" | "not_set_up"; last_tested_at: string | null; last_error: string | null;
}

export const jobBoardsApi = {
  list: () => http.get<{ boards: Board[]; mailbox: string | null }>("/api/v1/ui/job-boards"),
  connect: (code: string, secrets: Record<string, string>) => http.post<{ ok: boolean; error: string | null }>(`/api/v1/ui/job-boards/${code}/connect`, { secrets }),
  test: (code: string) => http.post<{ ok: boolean; error: string | null }>(`/api/v1/ui/job-boards/${code}/test`, {}),
  disconnect: (code: string) => http.del<void>(`/api/v1/ui/job-boards/${code}`),
};

/** Part 18.9: the way that works today -- upload resumes downloaded from the board (tagged with it). */
export function BoardResumeUpload({ code, onDone }: { code: BoardCode; onDone?: (count: number) => void }) {
  const t = useT();
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<{ done: number; total: number; failed: number } | null>(null);
  const pick = async (files: FileList | null) => {
    if (!files?.length) return;
    const list = Array.from(files);
    let failed = 0;
    setProgress({ done: 0, total: list.length, failed: 0 });
    for (let i = 0; i < list.length; i += 1) {
      try { await candidatesApi.upload(list[i], code); } catch { failed += 1; }
      setProgress({ done: i + 1, total: list.length, failed });
    }
    onDone?.(list.length - failed);
  };
  return (
    <Box>
      <input ref={input} type="file" hidden multiple accept=".pdf,.docx" onChange={(e) => { void pick(e.target.files); e.target.value = ""; }} />
      <Button variant="outlined" onClick={() => input.current?.click()} disabled={progress !== null && progress.done < progress.total}>
        {t("boards.upload", { board: t(`boards.name.${code}`) })}
      </Button>
      {progress && (
        <Box sx={{ mt: 1 }}>
          <LinearProgress variant="determinate" value={(progress.done / progress.total) * 100} />
          <Typography variant="caption">{t("boards.upload_progress", { done: progress.done, total: progress.total, failed: progress.failed })}</Typography>
        </Box>
      )}
    </Box>
  );
}

// Part 18.9: Settings > Integrations > Job boards -- status, connect form, test, disconnect,
// and the ways to bring candidates in today.
export default function JobBoardsPage() {
  const t = useT();
  const { can } = useMeBootstrap();
  const isAdmin = can("platform.settings.configure");
  const [data, setData] = useState<{ boards: Board[]; mailbox: string | null } | null>(null);
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<Record<string, { ok: boolean; text: string }>>({});
  const [disconnecting, setDisconnecting] = useState<BoardCode | null>(null);

  const load = useCallback(() => { jobBoardsApi.list().then(setData).catch(() => setData({ boards: [], mailbox: null })); }, []);
  useEffect(load, [load]);

  const result = (code: string, r: { ok: boolean; error: string | null }) =>
    setMsg((m) => ({ ...m, [code]: r.ok ? { ok: true, text: t("boards.test_ok") } : { ok: false, text: r.error === "API_NOT_AVAILABLE" ? t("boards.api_pending") : r.error || t("boards.err") } }));

  const save = async (b: Board) => {
    setBusy(b.code);
    try {
      result(b.code, await jobBoardsApi.connect(b.code, values[b.code] ?? {}));
      setValues((v) => ({ ...v, [b.code]: {} }));
      load();
    } catch (err) {
      setMsg((m) => ({ ...m, [b.code]: { ok: false, text: extractErrorMessage(err, t("boards.err")) } }));
    } finally { setBusy(null); }
  };
  const test = async (b: Board) => {
    setBusy(b.code);
    try { result(b.code, await jobBoardsApi.test(b.code)); load(); } catch (err) {
      setMsg((m) => ({ ...m, [b.code]: { ok: false, text: extractErrorMessage(err, t("boards.err")) } }));
    } finally { setBusy(null); }
  };

  if (!data) return null;
  return (
    <Stack spacing={2}>
      <Alert severity="info">
        <Typography sx={{ fontWeight: 700 }}>{t("boards.today_title")}</Typography>
        <Typography variant="body2">{t("boards.today_upload")}</Typography>
        <Typography variant="body2">{data.mailbox ? t("boards.today_email", { mailbox: data.mailbox }) : t("boards.today_email_no_mailbox")}</Typography>
      </Alert>
      <Grid container spacing={2}>
        {data.boards.map((b) => (
          <Grid key={b.code} size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: "100%" }}>
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
                  <Typography variant="h6">{t(`boards.name.${b.code}`)}</Typography>
                  <Chip size="small" color={b.state === "connected" ? "success" : b.state === "saved" ? "warning" : "default"}
                    label={t(`boards.state.${b.state}`)} />
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t(`boards.${b.needs}`)}</Typography>
                {isAdmin && b.fields.length > 0 && (
                  <Stack spacing={1} sx={{ mb: 1 }}>
                    {b.fields.map((f) => (
                      <TextField key={f} type="password" size="small" label={t(`boards.field.${f}`)} placeholder={b.saved ? t("boards.saved_placeholder") : t("boards.example_placeholder")}
                        value={values[b.code]?.[f] ?? ""} autoComplete="off"
                        onChange={(e) => setValues((v) => ({ ...v, [b.code]: { ...(v[b.code] ?? {}), [f]: e.target.value } }))} />
                    ))}
                    <Stack direction="row" spacing={1}>
                      <Button variant="contained" size="small" disabled={busy === b.code || b.fields.some((f) => !(values[b.code]?.[f] ?? "").trim())} onClick={() => save(b)}>
                        {b.saved ? t("boards.update") : t("boards.connect")}
                      </Button>
                      {b.saved && <Button size="small" disabled={busy === b.code} onClick={() => test(b)}>{t("boards.test")}</Button>}
                      {b.saved && <Button size="small" color="error" onClick={() => setDisconnecting(b.code)}>{t("boards.disconnect")}</Button>}
                    </Stack>
                  </Stack>
                )}
                {b.last_tested_at && <Typography variant="caption" sx={{ display: "block" }}>{t("boards.last_tested", { time: new Date(b.last_tested_at).toLocaleString() })}</Typography>}
                {msg[b.code] && <Alert severity={msg[b.code].ok ? "success" : "warning"} sx={{ my: 1 }}>{msg[b.code].text}</Alert>}
                <Box sx={{ mt: 1 }}><BoardResumeUpload code={b.code} /></Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
      <ConfirmDialog
        open={disconnecting !== null}
        title={t("boards.disconnect_title", { board: disconnecting ? t(`boards.name.${disconnecting}`) : "" })}
        message={t("boards.disconnect_body")}
        confirmLabel={t("boards.disconnect")}
        destructive
        onConfirm={async () => { if (disconnecting) { await jobBoardsApi.disconnect(disconnecting); setDisconnecting(null); load(); } }}
        onCancel={() => setDisconnecting(null)}
      />
    </Stack>
  );
}
