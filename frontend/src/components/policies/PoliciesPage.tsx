import { useCallback, useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import CloseIcon from "@mui/icons-material/Close";
import { useTheme } from "@mui/material/styles";

import { extractErrorMessage } from "../../api/client";
import { policiesApi, type PolicyList, type PolicyMeta, type PolicyRow } from "../../api/policiesApi";
import { useT } from "../../i18n";
import { EmptyState, Emoji, StatusChip, type Tone } from "../../ui-kit";

// Fix 2026-10-05: Settings > Company > Policies & handbook -- the ONE place HR uploads what the
// HR assistant answers from (works whether or not Helpdesk is switched on). Upload several
// PDF/DOCX files at once, give each a title / category / version / effective date, watch them
// go Processing -> Ready (or Failed + why), replace with a new version, preview, delete.

const CATEGORIES = ["leave", "conduct", "benefits", "it", "other"];
const ACCEPT = ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const STATUS: Record<string, { tone: Tone; emoji: string }> = {
  processing: { tone: "sky", emoji: "hourglass" }, ready: { tone: "ok", emoji: "check" }, failed: { tone: "coral", emoji: "warning" },
};

interface Queued extends PolicyMeta { key: string; file: File }

function guessCategory(name: string): string {
  const n = name.toLowerCase();
  if (/leave|holiday|vacation/.test(n)) return "leave";
  if (/conduct|ethic|harass|posh/.test(n)) return "conduct";
  if (/benefit|insurance|medical|reimburs/.test(n)) return "benefits";
  if (/\bit\b|security|device|laptop|password/.test(n)) return "it";
  return "other";
}

function titleFrom(name: string): string {
  const stem = name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  return stem ? stem.charAt(0).toUpperCase() + stem.slice(1) : name;
}

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const fmtDate = (iso: string | null) => (iso ? new Date(iso.length === 10 ? `${iso}T00:00:00` : iso).toLocaleDateString() : "—");

export default function PoliciesPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const [data, setData] = useState<PolicyList | null>(null);
  const [queue, setQueue] = useState<Queued[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [preview, setPreview] = useState<PolicyRow | null>(null);
  const [replace, setReplace] = useState<PolicyRow | null>(null);
  const [edit, setEdit] = useState<PolicyRow | null>(null);
  const [remove, setRemove] = useState<PolicyRow | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(() => policiesApi.list().then(setData).catch((err) => setMsg({ ok: false, text: extractErrorMessage(err, "") })), []);
  useEffect(() => { load(); }, [load]);
  const processing = data?.policies.some((p) => p.status === "processing");
  useEffect(() => {
    if (!processing) return undefined;
    const id = window.setInterval(load, 2000);
    return () => window.clearInterval(id);
  }, [processing, load]);

  const add = (files: FileList | File[] | null) => {
    if (!files) return;
    const next = Array.from(files).map((file) => ({ key: `${file.name}-${file.size}-${Math.random()}`, file, title: titleFrom(file.name), category: guessCategory(file.name), version: "1.0", effective_date: "" }));
    setQueue((q) => [...q, ...next]);
    setMsg(null);
  };
  const change = (key: string, patch: Partial<Queued>) => setQueue((q) => q.map((x) => (x.key === key ? { ...x, ...patch } : x)));

  const uploadAll = async () => {
    setBusy(true);
    setMsg(null);
    let done = 0;
    const failed: Queued[] = [];
    const errors: string[] = [];
    for (const item of queue) {
      try {
        await policiesApi.upload(item.file, { title: item.title, category: item.category, version: item.version, effective_date: item.effective_date });
        done += 1;
      } catch (err) {
        failed.push(item);
        errors.push(`${item.file.name}: ${extractErrorMessage(err, "")}`);
      }
    }
    setQueue(failed);
    setBusy(false);
    setMsg(errors.length ? { ok: false, text: errors.join(" · ") } : { ok: true, text: t("policies.uploaded", { n: done }) });
    load();
  };

  const sample = async () => {
    const blob = await policiesApi.sample();
    if (blob) saveBlob(blob, "sample-employee-handbook.docx");
  };

  const statusChip = (p: PolicyRow) => (
    <StatusChip tone={STATUS[p.status]?.tone ?? "muted"} emoji={STATUS[p.status]?.emoji ?? "label"} label={t(`policies.status.${p.status}`)} />
  );

  return (
    <Stack spacing={2.5}>
      <Typography color="text.secondary">{t("policies.intro")}</Typography>
      {data && !data.assistant_on && <Alert severity="info">{t("policies.assistant_off")}</Alert>}
      {msg && <Alert severity={msg.ok ? "success" : "error"} onClose={() => setMsg(null)}>{msg.text}</Alert>}

      <Card>
        <CardContent>
          <Box data-testid="policy-drop" onDragOver={(e) => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); add(e.dataTransfer.files); }}
            sx={{ border: `2px dashed ${dragOver ? f.brand : f.line}`, bgcolor: dragOver ? f.brandSoft : "transparent", borderRadius: "14px", p: 3, textAlign: "center" }}>
            <Emoji name="page" size={32} />
            <Typography sx={{ mt: 1 }}>
              {t("policies.drop")}{" "}
              <Button size="small" onClick={() => inputRef.current?.click()}>{t("policies.browse")}</Button>
            </Typography>
            <Typography variant="caption" color="text.secondary" component="div">{t("policies.drop_hint", { mb: data?.max_mb ?? 20 })}</Typography>
            <input ref={inputRef} type="file" hidden multiple accept={ACCEPT} aria-label={t("policies.browse")}
              onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
            <Button size="small" variant="text" onClick={sample} sx={{ mt: 1 }}>{t("policies.sample")}</Button>
          </Box>

          {queue.length > 0 && (
            <Box sx={{ mt: 2 }}>
              <Typography sx={{ fontWeight: 700, mb: 1 }}>{t("policies.queue.title")}</Typography>
              <Stack spacing={1.5}>
                {queue.map((q) => (
                  <Stack key={q.key} direction={{ xs: "column", md: "row" }} spacing={1} alignItems={{ md: "center" }}
                    sx={{ p: 1.5, border: `1px solid ${f.line}`, borderRadius: "10px" }}>
                    <Typography variant="body2" sx={{ minWidth: 160, wordBreak: "break-all" }}>{q.file.name}</Typography>
                    <TextField size="small" label={t("policies.field.title")} value={q.title} onChange={(e) => change(q.key, { title: e.target.value })} sx={{ flex: 2 }} />
                    <TextField size="small" select label={t("policies.field.category")} value={q.category} onChange={(e) => change(q.key, { category: e.target.value })} sx={{ minWidth: 150 }}>
                      {CATEGORIES.map((c) => <MenuItem key={c} value={c}>{t(`policies.cat.${c}`)}</MenuItem>)}
                    </TextField>
                    <TextField size="small" label={t("policies.field.version")} value={q.version} onChange={(e) => change(q.key, { version: e.target.value })} sx={{ width: 100 }} />
                    <TextField size="small" type="date" label={t("policies.field.effective")} value={q.effective_date} InputLabelProps={{ shrink: true }}
                      onChange={(e) => change(q.key, { effective_date: e.target.value })} sx={{ width: 170 }} />
                    <Tooltip title={t("policies.remove_file")}>
                      <IconButton aria-label={t("policies.remove_file")} onClick={() => setQueue((x) => x.filter((y) => y.key !== q.key))}><CloseIcon /></IconButton>
                    </Tooltip>
                  </Stack>
                ))}
              </Stack>
              {busy && <LinearProgress sx={{ mt: 1.5 }} />}
              <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                <Button variant="contained" onClick={uploadAll} disabled={busy || queue.some((q) => !q.title?.trim())}>
                  {busy ? t("policies.uploading") : t("policies.upload_n", { n: queue.length })}
                </Button>
                <Button onClick={() => setQueue([])} disabled={busy}>{t("policies.clear")}</Button>
              </Stack>
            </Box>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography sx={{ fontWeight: 800, mb: 1.5 }}>{t("policies.list.title", { n: data?.policies.length ?? 0 })}</Typography>
          {data && data.policies.length === 0 && <EmptyState compact illustration="files-uploading" title={t("policies.empty")} />}
          <Stack spacing={1.25}>
            {data?.policies.map((p) => (
              <Box key={p.id} data-testid="policy-row" sx={{ p: 1.5, border: `1px solid ${f.line}`, borderRadius: "12px" }}>
                <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ md: "center" }}>
                  <Box sx={{ minWidth: 0 }}>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                      <Typography sx={{ fontWeight: 700 }}>{p.title}</Typography>
                      {statusChip(p)}
                      <StatusChip tone="muted" emoji="label" label={t(`policies.cat.${p.category}`)} />
                    </Stack>
                    <Typography variant="body2" color="text.secondary">
                      {[p.file_name, p.version && `${t("policies.col.version")} ${p.version}`, p.effective_date && `${t("policies.col.effective")} ${fmtDate(p.effective_date)}`].filter(Boolean).join(" · ")}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">{t("policies.uploaded_by", { who: p.uploaded_by ?? "—", date: fmtDate(p.created_at) })}</Typography>
                    {p.older_versions.length > 0 && (
                      <Typography variant="caption" color="text.secondary" component="div">
                        {t("policies.older", { list: p.older_versions.map((o) => o.version ?? fmtDate(o.created_at)).join(", ") })}
                      </Typography>
                    )}
                    {p.status === "failed" && p.error && <Alert severity="error" sx={{ mt: 1 }}>{p.error}</Alert>}
                  </Box>
                  <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ flexShrink: 0 }}>
                    <Button size="small" onClick={() => setPreview(p)}>{t("policies.preview")}</Button>
                    {p.status === "failed" && <Button size="small" onClick={() => policiesApi.retry(p.id).then(load)}>{t("policies.retry")}</Button>}
                    <Button size="small" onClick={() => setReplace(p)} disabled={p.status === "processing"}>{t("policies.new_version")}</Button>
                    <Button size="small" onClick={() => setEdit(p)}>{t("policies.edit")}</Button>
                    <Button size="small" color="error" onClick={() => setRemove(p)}>{t("policies.delete")}</Button>
                  </Stack>
                </Stack>
              </Box>
            ))}
          </Stack>
        </CardContent>
      </Card>

      {preview && <PreviewDialog row={preview} onClose={() => setPreview(null)} />}
      {replace && <NewVersionDialog row={replace} onClose={() => setReplace(null)} onDone={() => { setReplace(null); load(); }} />}
      {edit && <EditDialog row={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); setMsg({ ok: true, text: t("policies.saved") }); load(); }} />}
      <Dialog open={Boolean(remove)} onClose={() => setRemove(null)}>
        <DialogTitle>{t("policies.delete.title", { title: remove?.title ?? "" })}</DialogTitle>
        <DialogContent><Typography>{t("policies.delete.body")}</Typography></DialogContent>
        <DialogActions>
          <Button onClick={() => setRemove(null)}>{t("policies.cancel")}</Button>
          <Button color="error" variant="contained" onClick={async () => {
            if (!remove) return;
            try {
              await policiesApi.remove(remove.id);
              setMsg({ ok: true, text: t("policies.deleted") });
            } catch (err) {
              setMsg({ ok: false, text: extractErrorMessage(err, "") });
            }
            setRemove(null);
            load();
          }}>{t("policies.delete.confirm")}</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

function PreviewDialog({ row, onClose }: { row: PolicyRow; onClose: () => void }) {
  const t = useT();
  const [url, setUrl] = useState<string | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [passages, setPassages] = useState<{ heading: string | null; text: string }[] | null>(null);
  useEffect(() => {
    let made: string | null = null;
    if (row.has_file) policiesApi.file(row.id).then((b) => { if (b) { setBlob(b); if (row.content_type === "application/pdf") { made = URL.createObjectURL(b); setUrl(made); } } });
    policiesApi.text(row.id).then((r) => setPassages(r.passages)).catch(() => setPassages([]));
    return () => { if (made) URL.revokeObjectURL(made); };
  }, [row]);
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>{row.title}</DialogTitle>
      <DialogContent dividers>
        {url && (
          <Box sx={{ mb: 2 }}>
            <Typography sx={{ fontWeight: 700, mb: 1 }}>{t("policies.preview.file")}</Typography>
            <Box component="iframe" title={row.title} src={url} sx={{ width: "100%", height: 420, border: 0, borderRadius: "8px" }} />
          </Box>
        )}
        <Typography sx={{ fontWeight: 700, mb: 1 }}>{t("policies.preview.text")}</Typography>
        {passages === null && <LinearProgress />}
        {passages?.length === 0 && <Typography color="text.secondary">{t("policies.preview.no_text")}</Typography>}
        <Stack spacing={1.5}>
          {passages?.map((p, i) => (
            <Box key={i}>
              {p.heading && <Typography sx={{ fontWeight: 700 }}>{p.heading}</Typography>}
              <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>{p.text}</Typography>
            </Box>
          ))}
        </Stack>
      </DialogContent>
      <DialogActions>
        {blob && <Button onClick={() => saveBlob(blob, row.file_name ?? "policy")}>{t("policies.download")}</Button>}
        <Button variant="contained" onClick={onClose}>{t("policies.close")}</Button>
      </DialogActions>
    </Dialog>
  );
}

function NewVersionDialog({ row, onClose, onDone }: { row: PolicyRow; onClose: () => void; onDone: () => void }) {
  const t = useT();
  const [file, setFile] = useState<File | null>(null);
  const [version, setVersion] = useState("");
  const [effective, setEffective] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!file) return;
    setBusy(true);
    try {
      await policiesApi.newVersion(row.id, file, { version, effective_date: effective });
      onDone();
    } catch (err) {
      setError(extractErrorMessage(err, ""));
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("policies.new_version.title", { title: row.title })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">{t("policies.new_version.body")}</Typography>
          {error && <Alert severity="error">{error}</Alert>}
          <Button variant="outlined" component="label">
            {file ? file.name : t("policies.new_version.file")}
            <input hidden type="file" accept={ACCEPT} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </Button>
          <TextField size="small" label={t("policies.field.version")} value={version} onChange={(e) => setVersion(e.target.value)} />
          <TextField size="small" type="date" label={t("policies.field.effective")} value={effective} InputLabelProps={{ shrink: true }} onChange={(e) => setEffective(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("policies.cancel")}</Button>
        <Button variant="contained" onClick={submit} disabled={!file || busy}>{busy ? t("policies.uploading") : t("policies.new_version")}</Button>
      </DialogActions>
    </Dialog>
  );
}

function EditDialog({ row, onClose, onDone }: { row: PolicyRow; onClose: () => void; onDone: () => void }) {
  const t = useT();
  const [meta, setMeta] = useState<PolicyMeta>({ title: row.title, category: row.category, version: row.version ?? "", effective_date: row.effective_date ?? "" });
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    try {
      await policiesApi.update(row.id, meta);
      onDone();
    } catch (err) {
      setError(extractErrorMessage(err, ""));
    }
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t("policies.edit")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField size="small" label={t("policies.field.title")} value={meta.title} onChange={(e) => setMeta({ ...meta, title: e.target.value })} />
          <TextField size="small" select label={t("policies.field.category")} value={meta.category} onChange={(e) => setMeta({ ...meta, category: e.target.value })}>
            {CATEGORIES.map((c) => <MenuItem key={c} value={c}>{t(`policies.cat.${c}`)}</MenuItem>)}
          </TextField>
          <TextField size="small" label={t("policies.field.version")} value={meta.version} onChange={(e) => setMeta({ ...meta, version: e.target.value })} />
          <TextField size="small" type="date" label={t("policies.field.effective")} value={meta.effective_date} InputLabelProps={{ shrink: true }}
            onChange={(e) => setMeta({ ...meta, effective_date: e.target.value })} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("policies.cancel")}</Button>
        <Button variant="contained" onClick={submit} disabled={!meta.title?.trim()}>{t("policies.save")}</Button>
      </DialogActions>
    </Dialog>
  );
}
