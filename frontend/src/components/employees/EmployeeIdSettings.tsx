import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { extractErrorMessage } from "../../api/client";
import { employeesApi, type IdFormat } from "../../api/employeesApi";
import { useT } from "../../i18n";

// Part 20.1: Settings > Onboarding & employees > Employee ID -- prefix + running number + padding
// (e.g. CTD-0001). Changing it only changes how NEW IDs look; numbers carry on and are never reused.

export default function EmployeeIdSettings() {
  const t = useT();
  const [fmt, setFmt] = useState<IdFormat | null>(null);
  const [prefix, setPrefix] = useState("");
  const [padding, setPadding] = useState(4);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { employeesApi.idFormat().then((f) => { setFmt(f); setPrefix(f.prefix); setPadding(f.padding); }).catch(() => undefined); }, []);
  const preview = `${prefix}${String((fmt?.last_number ?? 0) + 1).padStart(padding, "0")}`;
  const save = async () => {
    setMsg(null);
    try {
      const f = await employeesApi.saveIdFormat(prefix, padding);
      setFmt(f);
      setMsg({ ok: true, text: t("emp.idfmt.saved", { next: f.next_id }) });
    } catch (e) {
      setMsg({ ok: false, text: extractErrorMessage(e, "") });
    }
  };
  return (
    <Card>
      <CardContent>
        <Typography color="text.secondary" sx={{ mb: 2 }}>{t("emp.idfmt.intro")}</Typography>
        {msg && <Alert severity={msg.ok ? "success" : "error"} sx={{ mb: 2 }}>{msg.text}</Alert>}
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "flex-start" }}>
          <TextField label={t("emp.idfmt.prefix")} value={prefix} onChange={(e) => setPrefix(e.target.value)} helperText={t("emp.idfmt.prefix_hint")} inputProps={{ maxLength: 12 }} />
          <TextField type="number" label={t("emp.idfmt.padding")} value={padding} onChange={(e) => setPadding(Math.max(1, Math.min(8, Number(e.target.value) || 1)))}
            helperText={t("emp.idfmt.padding_hint")} inputProps={{ min: 1, max: 8 }} />
          <Button variant="contained" onClick={save} sx={{ mt: { sm: 1 } }}>{t("emp.save")}</Button>
        </Stack>
        <Typography sx={{ mt: 2 }}>{t("emp.idfmt.next", { id: preview })}</Typography>
        {fmt && <Typography variant="caption" color="text.secondary">{t("emp.idfmt.last", { n: fmt.last_number })}</Typography>}
      </CardContent>
    </Card>
  );
}
