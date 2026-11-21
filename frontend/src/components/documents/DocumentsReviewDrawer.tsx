import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import Drawer from "@mui/material/Drawer";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage, http } from "../../api/client";
import { useT } from "../../i18n";

interface DocFile { id: string; code: string; name: string | null; level: string | null; reasons: { level: string; code: string; [k: string]: unknown }[]; hr_status: string; hr_note: string | null }
interface Item { code: string; label: string; required: boolean; files: DocFile[]; received: boolean; approved: boolean; level: string | null }
interface Review { items: Item[]; missing: string[]; all_received: boolean; all_approved: boolean; reds: number; ambers: number; status: string; cross_checks: { code: string; [k: string]: unknown }[] }

// Part 18.17: HR's documents review -- every file with the agent's green / amber / red and the
// reason; approve all or per document; ask for specific documents again (the candidate is
// emailed the list + note). When everything required is approved the candidate moves to BGV.
export default function DocumentsReviewDrawer({ applicationId, name, onClose, onChanged }: {
  applicationId: string | null; name?: string | null; onClose: () => void; onChanged: () => void;
}) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [data, setData] = useState<Review | null>(null);
  const [again, setAgain] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    if (!applicationId) return;
    http.get<Review>(`/api/v1/ui/documents/${applicationId}`).then(setData).catch((e) => setMsg({ ok: false, text: extractErrorMessage(e, t("docrev.err")) }));
  }, [applicationId, t]);
  useEffect(() => { setData(null); setAgain(new Set()); setNote(""); setMsg(null); load(); }, [load]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); load(); onChanged(); } catch (e) { setMsg({ ok: false, text: extractErrorMessage(e, t("docrev.err")) }); } finally { setBusy(false); }
  };
  // B1 (Part 27): "sent" only when the email really went; otherwise say so and offer the link to share
  const send = async (fn: () => Promise<{ sent: boolean; link?: string | null }>, ok: string) => {
    setBusy(true); setMsg(null);
    try {
      const r = await fn();
      setMsg(r.sent ? { ok: true, text: ok } : { ok: false, text: t("docrev.not_sent") });
      load(); onChanged();
    } catch (e) { setMsg({ ok: false, text: extractErrorMessage(e, t("docrev.err")) }); } finally { setBusy(false); }
  };
  const [copied, setCopied] = useState(false);
  const copyLink = async () => {
    try {
      const r = await http.get<{ link: string }>(`/api/v1/ui/documents/${applicationId}/link`);
      await navigator.clipboard.writeText(r.link);
      setCopied(true); setTimeout(() => setCopied(false), 2500);
    } catch (e) { setMsg({ ok: false, text: extractErrorMessage(e, t("docrev.err")) }); }
  };
  const uploadFor = (code: string, file: File | undefined) => {
    if (!file || !applicationId) return;
    const form = new FormData(); form.append("file", file);
    void act(() => http.postForm(`/api/v1/ui/documents/${applicationId}/files/${code}`, form), t("docrev.uploaded_for"));
  };
  const colour = (lvl: string | null) => (lvl === "red" ? "error" : lvl === "amber" ? "warning" : lvl === "green" ? "success" : "default") as "error" | "warning" | "success" | "default";
  const openFile = async (id: string, fileName: string | null) => {
    const blob = await http.fetchBlob(`/api/v1/ui/documents/file/${id}`);
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.target = "_blank"; a.download = fileName ?? "document"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  };

  return (
    <Drawer anchor="right" open={applicationId !== null} onClose={onClose} slotProps={{ paper: { sx: { width: { xs: "100%", sm: 520 }, p: 2.5 } } }}>
      <Stack spacing={2}>
        <Box>
          <Typography variant="h6">{t("docrev.title", { name: name ?? "" })}</Typography>
          {data && (
            <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
              <Chip size="small" color={data.all_received ? "success" : "warning"} label={data.all_received ? t("docrev.all_in") : t("docrev.missing", { count: data.missing.length })} />
              {data.reds > 0 && <Chip size="small" color="error" label={t("docrev.reds", { count: data.reds })} />}
              {data.ambers > 0 && <Chip size="small" color="warning" label={t("docrev.ambers", { count: data.ambers })} />}
            </Stack>
          )}
        </Box>
        {msg && <Alert severity={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
        {data?.cross_checks.map((c, i) => <Alert key={i} severity="warning">{t(`docrev.cross.${c.code}`)}</Alert>)}
        {data?.items.map((it) => (
          <Box key={it.code} sx={{ p: 1.5, borderRadius: 3, bgcolor: it.level === "red" ? f.coralSoft : it.level === "amber" ? f.sunSoft : it.received ? f.okSoft : f.surface2 }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <Checkbox size="small" checked={again.has(it.code)} onChange={() => setAgain((s) => { const n = new Set(s); if (n.has(it.code)) n.delete(it.code); else n.add(it.code); return n; })}
                inputProps={{ "aria-label": t("docrev.ask_again_one", { doc: it.label }) }} />
              <Typography sx={{ fontWeight: 700, flex: 1 }}>{it.label}{!it.required && ` (${t("docform.optional")})`}</Typography>
              {it.approved ? <Chip size="small" color="success" label={t("docrev.approved")} /> : !it.received ? <Chip size="small" label={t("docrev.not_received")} /> : null}
              {!it.approved && (
                <Button size="small" component="label" disabled={busy}>
                  {t("docrev.upload_for")}
                  <input hidden type="file" onChange={(e) => { uploadFor(it.code, e.target.files?.[0]); e.target.value = ""; }} />
                </Button>
              )}
            </Stack>
            {it.files.map((file) => (
              <Stack key={file.id} spacing={0.5} sx={{ pl: 5, mt: 0.75, opacity: file.hr_status === "reupload" ? 0.55 : 1 }}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip size="small" color={colour(file.level)} label={t(`docrev.level.${file.level ?? "none"}`)} />
                  <Link component="button" onClick={() => openFile(file.id, file.name)}>{file.name ?? t("docrev.file")}</Link>
                  {file.hr_status === "pending" && (
                    <Button size="small" disabled={busy} onClick={() => act(() => http.post(`/api/v1/ui/documents/${applicationId}/approve`, { doc_ids: [file.id] }), t("docrev.done_one"))}>{t("docrev.approve_one")}</Button>
                  )}
                  {file.hr_status === "reupload" && <Typography variant="caption">{t("docrev.asked_again")}</Typography>}
                </Stack>
                {file.reasons.map((r, i) => <Typography key={i} variant="body2" sx={{ color: r.level === "red" ? f.coral : f.sunInk }}>• {t(`docrev.reason.${r.code}`)}</Typography>)}
              </Stack>
            ))}
          </Box>
        ))}
        {data && (
          <Stack spacing={1}>
            <Button variant="contained" color="success" disabled={busy || !data.all_received}
              onClick={() => act(() => http.post(`/api/v1/ui/documents/${applicationId}/approve`, {}), t("docrev.done_all"))}>{t("docrev.approve_all")}</Button>
            <TextField size="small" label={t("docrev.note")} value={note} onChange={(e) => setNote(e.target.value)} multiline minRows={2} />
            {again.size > 0 ? (
              <Button variant="outlined" disabled={busy}
                onClick={() => send(() => http.post<{ sent: boolean; link?: string | null }>(`/api/v1/ui/documents/${applicationId}/reupload`, { codes: Array.from(again), note: note || null }), t("docrev.done_again"))}>
                {t("docrev.ask_again", { count: again.size })}
              </Button>
            ) : <Typography variant="caption" sx={{ color: f.muted }}>{t("docrev.ask_again_hint")}</Typography>}
            <Stack direction="row" spacing={1}>
              <Button disabled={busy} onClick={() => send(() => http.post<{ sent: boolean; link?: string | null }>(`/api/v1/ui/documents/${applicationId}/send-form`, {}), t("docrev.done_send"))}>{t("docrev.send_link")}</Button>
              <Button disabled={busy} onClick={copyLink}>{copied ? t("docrev.copied") : t("docrev.copy_link")}</Button>
            </Stack>
          </Stack>
        )}
        <Button onClick={onClose}>{t("salaryx.close")}</Button>
      </Stack>
    </Drawer>
  );
}
