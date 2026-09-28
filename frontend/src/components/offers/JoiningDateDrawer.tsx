import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Drawer from "@mui/material/Drawer";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, http } from "../../api/client";
import { useT } from "../../i18n";

interface Info { status: string; proposed?: string[]; proposed_at?: string; chosen?: string | null; chosen_at?: string | null; note?: string | null }

// Part 18.19: after BGV passed -- HR picks 3 tentative joining dates; the candidate is emailed
// and chooses one. Shows the chosen date; HR can propose new dates at any time.
export default function JoiningDateDrawer({ applicationId, name, onClose, onChanged }: { applicationId: string | null; name?: string | null; onClose: () => void; onChanged: () => void }) {
  const t = useT();
  const [info, setInfo] = useState<Info | null>(null);
  const [dates, setDates] = useState(["", "", ""]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    if (!applicationId) return;
    http.get<Info>(`/api/v1/ui/joining/${applicationId}`).then(setInfo).catch(() => setInfo(null));
  }, [applicationId]);
  useEffect(() => { setDates(["", "", ""]); setNote(""); setMsg(null); load(); }, [load]);

  const send = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await http.post<{ sent: boolean; link: string | null }>(`/api/v1/ui/joining/${applicationId}/propose`, { dates, note: note || null });
      setMsg({ ok: true, text: r.sent ? t("joining.sent") : t("joining.link", { link: r.link ?? "" }) });
      load(); onChanged();
    } catch (e) { setMsg({ ok: false, text: extractErrorMessage(e, t("joinpick.err")) }); } finally { setBusy(false); }
  };
  const nice = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString();
  const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);

  return (
    <Drawer anchor="right" open={applicationId !== null} onClose={onClose} slotProps={{ paper: { sx: { width: { xs: "100%", sm: 420 }, p: 2.5 } } }}>
      <Stack spacing={2}>
        <Typography variant="h6">{t("joining.title", { name: name ?? "" })}</Typography>
        {info?.chosen && <Alert severity="success">{t("joining.chosen", { date: nice(info.chosen) })}</Alert>}
        {info?.proposed?.length && !info.chosen ? <Alert severity="info">{t("joining.waiting", { dates: info.proposed.map(nice).join(", ") })}</Alert> : null}
        <Typography variant="body2" color="text.secondary">{info?.proposed?.length ? t("joining.new_dates") : t("joining.intro")}</Typography>
        {dates.map((d, i) => (
          <TextField key={i} type="date" label={t("joining.option", { n: i + 1 })} value={d} onChange={(e) => setDates((x) => x.map((y, j) => (j === i ? e.target.value : y)))}
            slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: tomorrow } }} />
        ))}
        <TextField label={t("joining.note")} value={note} onChange={(e) => setNote(e.target.value)} multiline minRows={2} />
        {msg && <Alert severity={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
        <Button variant="contained" disabled={busy || dates.some((d) => !d) || new Set(dates).size < 3} onClick={send}>{t("joining.send")}</Button>
        <Button onClick={onClose}>{t("salaryx.close")}</Button>
      </Stack>
    </Drawer>
  );
}
