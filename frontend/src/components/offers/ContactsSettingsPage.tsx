import { useEffect, useState } from "react";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { budgetsApi } from "../../api/budgetsApi";
import { extractErrorMessage, platformSettingsApi } from "../../api/client";
import { useT } from "../../i18n";

interface Person { name: string; role: string; email: string; phone: string }
type Contacts = Record<string, Person[]>;
const KEY = "recruitment.contacts";
const empty = (): Person => ({ name: "", role: "", email: "", phone: "" });

// Part 18.20: Settings > Hiring > Contacts -- the people named in the "Congratulations" welcome
// email: the company default (e.g. HR, management) plus each department's own (e.g. its head).
export default function ContactsSettingsPage() {
  const t = useT();
  const [data, setData] = useState<Contacts | null>(null);
  const [depts, setDepts] = useState<string[]>([]);
  const [dept, setDept] = useState("default");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    platformSettingsApi.values().then((vals) => {
      const v = vals.find((x) => x.key === KEY)?.value as Contacts | undefined;
      setData(v && typeof v === "object" ? v : { default: [] });
    }).catch(() => setData({ default: [] }));
    budgetsApi.list().then((r) => setDepts(r.departments.map((d) => d.department))).catch(() => setDepts([]));
  }, []);

  if (!data) return null;
  const rows = data[dept] ?? [];
  const setRows = (next: Person[]) => setData({ ...data, [dept]: next });
  const save = async () => {
    const clean: Contacts = {};
    Object.entries(data).forEach(([k, list]) => {
      const keep = list.filter((p) => p.name.trim() || p.email.trim()).map((p) => ({ name: p.name.trim(), role: p.role.trim(), email: p.email.trim(), phone: p.phone.trim() }));
      if (keep.length || k === "default") clean[k] = keep;
    });
    try { await platformSettingsApi.update(KEY, clean); setData(clean); setMsg({ ok: true, text: t("contacts.saved") }); }
    catch (err) { setMsg({ ok: false, text: extractErrorMessage(err, t("contacts.err")) }); }
  };

  return (
    <Card>
      <CardContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{t("contacts.intro")}</Typography>
        <TextField select size="small" label={t("contacts.for")} value={dept} onChange={(e) => setDept(e.target.value)} sx={{ minWidth: 240, mb: 2 }}>
          <MenuItem value="default">{t("contacts.default")}</MenuItem>
          {depts.map((d) => <MenuItem key={d} value={d}>{d}</MenuItem>)}
        </TextField>
        {msg && <Alert severity={msg.ok ? "success" : "error"} sx={{ mb: 1.5 }} onClose={() => setMsg(null)}>{msg.text}</Alert>}
        <Stack spacing={1}>
          {rows.map((p, i) => (
            <Stack key={i} direction={{ xs: "column", md: "row" }} spacing={1} alignItems={{ md: "center" }}>
              {(["name", "role", "email", "phone"] as const).map((k) => (
                <TextField key={k} size="small" label={t(`contacts.${k}`)} value={p[k]} type={k === "email" ? "email" : "text"}
                  placeholder={t(`contacts.eg_${k}`)} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} />
              ))}
              <IconButton aria-label={t("reqdocs.remove")} onClick={() => setRows(rows.filter((_x, j) => j !== i))}><DeleteOutlineIcon fontSize="small" /></IconButton>
            </Stack>
          ))}
        </Stack>
        <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
          <Button onClick={() => setRows([...rows, empty()])}>{t("contacts.add")}</Button>
          <Button variant="contained" onClick={save}>{t("lock.save")}</Button>
        </Stack>
      </CardContent>
    </Card>
  );
}
